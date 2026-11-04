"""Stage loop for the scene chat: prompt -> model -> scene tools, one stage at a time.

Pure Python. ``execute`` is supplied by the caller (on a worker thread it is an ``Executor``
that hands each call to Blender's main thread). Nothing here imports Blender.

Each stage starts from fresh messages: its instructions, then the request, the summaries of the steps this run
made so far (never their code) and the scene as ``read_scene`` sees it. Everything a tool returns passes through
``code_check.redact`` before the model sees it.
"""

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, replace

from . import code_check, scene_tools, thread_safety
from .api_client import ApiError
from .chat import model_calls, review as scene_review_text
from .chat.messages import EARLIER_MAX, step_summary, user_message  # noqa: F401
from .chat.model_calls import (  # noqa: F401
    BUSY,
    DEFAULT_CAP,
    MAX_TOKENS,
    ReplyCap,
    STEP_LINES,
    WithoutReasoning,
    _cut_off,
    _llm_error,
    _looks_like_code,
    _retryable,
    reasoning_optional,
    reply_cap,
    retried,
    step_size,
)
from .chat.pictures import Visual, around_message, look_message, with_pictures_fallback  # noqa: F401
from .chat.problems import (  # noqa: F401
    CAMERA_MOVING,
    CAMERA_STILL,
    FIX_MAX,
    _has_no_lights,
    _unpainted,
    camera_problems,
    loose_problems,
    overlap_problems,
    placement_problems,
    problems_line,
    verified_line,
    view_problems,
)
from .chat.stages import (  # noqa: F401
    COMPLETE,
    COMPLETE_REPEATS,
    COMPLETE_ROUNDS,
    CONCEPT_STAGES,
    DETAIL,
    EDIT,
    EDIT_ROUNDS,
    FIX,
    ORDER,
    STAGES,
    STAGE_ROUNDS,
    STAGE_TOOLS,
    TEXTURE_STAGES,
    ASSET_TOOLS,
    LOOK_TOOLS,
    TOTAL_ROUNDS,
    is_full,
)
from .chat.stages import EDIT_LOOK_ROUNDS, LOOK_AFTER, LOOK_MOVES, LOOK_ROUNDS, REPLY_STAGES  # noqa: F401
from .instructions.notes import (  # noqa: F401
    CODE_AS_TEXT,
    CONCEPT_NOTE,
    CUT_OFF,
    CUT_OFF_REPLY,
    GENERATED_RULE,
    GENERATE_RULE,
    LAST_EDIT_ROUND,
    LAST_ROUND,
    LOOK,
    LOOK_NOTES,
    LOOK_OVERVIEW,
    NO_LIGHTS,
    NO_MATERIAL,
    NO_PICTURE,
    TEXTURE_RULE,
    FREE_ASSETS_RULE,
)
from .instructions.rules import DETAIL_LATER, OVERRIDE_RULE, RULES, SHAPES  # noqa: F401
from .instructions.stages import (  # noqa: F401
    FOLLOW_UP_INSTRUCTIONS,
    INSTRUCTIONS,
    MISSING_TEXT,
    PROBLEMS_TEXT,
    _CLOSE,
    _HEAD,
)
from .chat.debug_log import LOG_ENV, _without_images, debug_log  # noqa: F401
from .chat.stages import QUICK_STAGES  # noqa: F401
from .instructions.rules import system_text  # noqa: F401
from .chat.run_types import Executor, Generation, Limits, RunResult, StopRun  # noqa: F401
from .chat.step_results import (  # noqa: F401
    CHECK_REFUSALS,
    NO_CONTEXT,
    PARTLY_DONE,
    SKIPPED_AT_CAP,
    _detail,
    _passes_filter,
    _result_error,
    _stopped_total,
    enum_hint,
    refusal_ends,
)


def run(prompt, llm, execute, post, cancel, limits=None, stages=STAGES, earlier=(), secrets=(), review=None,
        blender=None, quick_llm=None, cap=DEFAULT_CAP, generation=None, textures=0, concept=None, visual=None,
        detail=None, assets=False, routes=None, scene_review=None):
    """``earlier``: the earlier prompts of this scene, most recent first; set, the prompt is a follow-up.
    ``secrets``: replaced by ``[redacted]`` in everything a tool returns before the model sees it.
    ``review``: Code check, ``review(code) -> (allowed, reason)``; set, every step that passes the filter is
    reviewed before it runs. ``None``: Code check is off.
    ``blender``: Blender's version tuple, for the version notes in the instructions (Blender 5 when ``None``).
    ``quick_llm``: the model without its hidden reasoning, for ``QUICK_STAGES``; ``None`` uses ``llm``.
    ``cap``: the model's ``ReplyCap``; the callers send its ``tokens`` as max_tokens, and the instructions ask for
    steps of its ``lines``.
    ``generation``: a ``Generation`` when the run generates 3D objects: the layout stage gets their brief.
    ``textures``: how many generated textures the scene may still order; above 0, the materials stage gets the
    generate_texture tool.
    ``concept``: the concept picture as a ``data:`` URL; the layout and materials stages get it as an image.
    ``visual``: a ``Visual`` when the visual check is on: ``LOOK_STAGES`` get a small render
    (``execute("render_frames", {"moves": bool})``) as a picture, at most one render per stage.
    ``detail``: ``detail(scene, rounds, total) -> detail.Outcome`` runs the ``DETAIL`` stage when ``stages`` holds
    it; ``None`` skips that stage. Its rounds come on top of the total cap.
    ``assets``: the stages in ``ASSET_TOOLS`` also get the Poly Haven tools.
    ``routes``: ``stage -> Route`` (``chat.stage_models``) for a stage another model answers, else ``None``.
    ``scene_review``: a ``chat.review.Reviewer`` when the scene review is on: once the check stage is done, it judges
    the scene, and what it keeps gets one more fix stage within the rounds left."""
    limits = replace(limits or Limits())  # the detail stage raises the copy's total cap
    run_llm, run_quick, run_cap = llm, quick_llm, cap
    instructions = FOLLOW_UP_INSTRUCTIONS if earlier else INSTRUCTIONS
    rounds = 0
    failures = {}
    skipped = []  # a line per stage left partly done
    stuck_before = False  # the stage before this one was left partly done
    refusals = 0  # Code check refusals in a row
    last_reply = ""
    steps = []  # {"step", "stage", "summary"} for each run_python of this run
    extra_light = False  # the one extra light round of this run was given; the check stage gives it back
    extra_paint = False  # the one extra materials round of this run was given
    start_scene = None  # read_scene when the run began, to tell when a step stopped the camera move

    def clean(value):
        return code_check.redact(value, secrets)

    def cancelled(stage):
        return RunResult("cancelled", "Stopped. What was built is kept.", rounds, stage)

    queue = list(stages)
    missing = []  # the planned things a complete stage builds
    completes = 0  # complete stages run so far
    fixes = 0  # fix stages run so far
    fix_problems = {}  # what the next fix stage fixes
    looked = set()  # the stages that had their render
    checked = reviewed = False  # the check stage is done; the scene review ran
    review_found = []  # what the scene review kept
    review_fix = False  # the fix stage now queued or running is the review's

    def fits(needed):
        """True when ``needed`` more rounds fit, taking the shortfall from ``limits.extra_rounds``."""
        short = needed - max(0, limits.total_rounds - rounds)
        if short <= 0:
            return True
        if limits.extra_rounds >= short:
            limits.extra_rounds -= short
            limits.total_rounds += short
            return True
        return False

    def review_after():
        """After the review's fix stage: the second look, the undo when it made things worse, the done line. True
        when the fix stage was undone."""
        outcome = scene_review.again(review_found)
        undone = False
        if outcome is None:
            ended, solved = scene_review_text.UNCHECKED, None
        else:
            solved, worse = outcome
            ended = scene_review.undo() if worse else scene_review_text.FIXED
            undone = ended == scene_review_text.UNDONE
        skipped.append(scene_review_text.done_line(review_found, solved, ended))
        return undone

    def look(stage):
        """The render of the scene as a message for the model, or ``None``; once per stage."""
        if visual is None or not visual.accepted or stage in looked or cancel.is_set():
            return None
        looked.add(stage)
        post({"type": "looking", "state": True})
        try:
            if cancel.wait(visual.pause):
                return None
            found = execute("render_frames", {"moves": stage in LOOK_MOVES})
        except Exception as exc:  # the check is extra: the stage goes on without it
            found = {"images": [], "reason": clean(str(exc) or type(exc).__name__)}
        finally:
            post({"type": "looking", "state": False})
        found = found if isinstance(found, dict) else {}
        debug_log({"stage": stage, "look": {k: found.get(k) for k in ("frames", "seconds", "overview", "reason")}},
                  secrets)
        if not found.get("images"):
            return None
        visual.renders += len(found["images"])
        return look_message(found, stage)

    def room(needed):
        """True when one more stage can run: rounds remain within the total, or ``limits.extra_rounds`` still hold
        ``needed`` of them, which then raise the total."""
        if rounds < limits.total_rounds:
            return True
        if limits.extra_rounds >= needed:
            limits.extra_rounds -= needed
            limits.total_rounds = rounds + needed
            return True
        return False

    def measured():
        """The scene's placement problems as the add-on measures them, or ``{}``."""
        try:
            return placement_problems(clean(execute("placement_problems", {})))
        except Exception:  # a safety net; the run goes on without it
            return {}

    def settle_props(stage):
        """Old versions of rebuilt parts go, then small loose props come down onto what is under them, before
        anything is measured."""
        try:
            pruned = execute("prune", {})
        except Exception:  # a safety net; the run goes on without it
            pruned = []
        if pruned:
            debug_log({"stage": stage, "replaced": pruned}, secrets)
        try:
            moved = execute("settle", {})
        except Exception:  # a safety net; the run goes on without it
            return
        if moved:
            debug_log({"stage": stage, "settled": moved}, secrets)

    def fix_if_needed():
        """Put a fix stage first in the queue when measured problems remain and a stage still fits."""
        nonlocal fixes, fix_problems
        if fixes >= FIX_MAX or cancel.is_set():
            return
        found = measured()
        if found and room(COMPLETE_ROUNDS):
            fix_problems = found
            fixes += 1
            queue.insert(0, FIX)

    def reserve(stage):
        """1 while the check stage is still to come: the total cap keeps its last round for the check's reply."""
        return 1 if stage != "check" and "check" in queue else 0

    def to_check(stage=None):
        """The cap leaves one round: the stages before the check are skipped, and the check gives the reply."""
        later = ([stage] if stage else []) + [s for s in queue if s != "check"]
        skipped.extend(SKIPPED_AT_CAP % s.capitalize() for s in later if s != COMPLETE)
        queue[:] = ["check"]

    while queue:
        stage = queue.pop(0)
        if cancel.is_set():
            return cancelled(stage)
        if stage == DETAIL:
            if detail is None:
                continue
            post({"type": "stage", "stage": stage, "state": "active"})
            try:
                found = execute("read_scene", {})
                outcome = detail(json.dumps(clean(found)), rounds, limits.total_rounds)
            except Exception as exc:  # the scene stays as the layout left it; the run goes on
                debug_log({"stage": stage, "error": str(exc)}, secrets)
                post({"type": "stage", "stage": stage, "state": "partial"})
                skipped.append(PARTLY_DONE % (stage.capitalize(), _detail(clean(str(exc) or type(exc).__name__))))
                continue
            rounds += outcome.rounds
            limits.total_rounds += outcome.rounds
            if limits.detail_rounds is not None:  # spent from the rounds the complete and fix stages may also use
                limits.extra_rounds = max(0, limits.extra_rounds - outcome.rounds)
            for step in outcome.steps:
                steps.append(dict(step, step=len(steps) + 1))
            if outcome.cancelled:
                post({"type": "stage", "stage": stage, "state": "cancelled"})
                return cancelled(stage)
            post({"type": "stage", "stage": stage, "state": "partial" if outcome.lines else "done"})
            skipped.extend(outcome.lines)
            settle_props(stage)
            fix_if_needed()  # what the detail stage left in the wrong place is fixed before the materials
            continue
        if rounds >= limits.total_rounds - reserve(stage):
            if rounds >= limits.total_rounds:
                return _stopped_total(limits, last_reply, skipped)
            to_check(stage)
            continue
        post({"type": "stage", "stage": stage, "state": "active"})
        def read(name):
            try:
                return json.dumps(clean(execute(name, {})))
            except Exception as exc:
                return "ERROR: %s" % clean(str(exc) or type(exc).__name__)
        scene = read("read_scene")
        if start_scene is None:
            start_scene = scene
        view = read("camera_view") if stage == "check" else None  # the check stage starts with what it checks
        problems = view_problems(view) if view else []
        if stage in ("camera", "check"):
            problems += camera_problems(start_scene, scene)
        if stage == "check":
            problems += loose_problems(scene) + overlap_problems(scene)
            bare = _unpainted(scene)
            if bare:
                problems.append(NO_MATERIAL % ", ".join(bare))
        failed_3d = list(generation.notes()) if generation is not None and generation.notes is not None else []
        problems = failed_3d + problems
        if stage == COMPLETE:
            problems = [MISSING_TEXT % "; ".join(missing)] + problems
        elif stage == FIX:
            problems = ([PROBLEMS_TEXT % json.dumps(fix_problems)] if fix_problems or not review_fix else []) + (
                [scene_review_text.fix_text(review_found)] if review_fix else []) + problems
        elif stage == "check" and generation is not None and generation.complete:
            try:
                absent = list(execute("missing_items", {}) or [])
            except Exception:  # a safety net; the stage goes on without it
                absent = []
            if absent:  # the reply must not say the scene has them
                problems = [MISSING_TEXT % "; ".join(absent) + " Never describe them as built until they are"] + problems
        offer = generation is not None and generation.offered(stage)
        route = routes(stage) if routes is not None else None
        llm, quick_llm, cap = (route.llm, route.quick, route.cap) if route is not None else (run_llm, run_quick,
                                                                                          run_cap)
        cut_off_reply, cut_off_step = step_size(CUT_OFF_REPLY, cap.lines), step_size(CUT_OFF, cap.lines)
        system = system_text(instructions[stage], blender, cap.lines)
        if stage == "layout" and detail is not None and DETAIL in queue:
            system += "\n" + DETAIL_LATER
        if generation is not None:
            system += "\n" + (GENERATE_RULE if offer else "") + GENERATED_RULE
        texturing = textures > 0 and stage in TEXTURE_STAGES
        if texturing:
            system += "\n" + TEXTURE_RULE % textures
        haven = ASSET_TOOLS.get(stage, ()) if assets else ()
        if haven:
            system += "\n" + FREE_ASSETS_RULE
        request = user_message(prompt, scene, earlier, steps, view, problems)
        if offer and generation.brief:
            request += "\n\n" + generation.brief
        messages = [{"role": "system", "content": system}, {"role": "user", "content": request}]
        if concept and stage in CONCEPT_STAGES and (visual is None or visual.accepted):
            messages.append({"role": "user", "content": [{"type": "text", "text": CONCEPT_NOTE},
                                                         {"type": "image_url", "image_url": {"url": concept}}]})
        quick = stage in QUICK_STAGES
        looking = LOOK_TOOLS.get(stage, ()) if visual is not None and visual.accepted else ()
        allowed = STAGE_TOOLS[stage] + (("generate_texture",) if texturing else ()) + haven + looking
        tools = [scene_tools.TOOLS[n] for n in allowed]
        stage_calls = 0
        stuck = ""  # set when one tool failed too often in a row in this stage
        stage_rounds = limits.rounds_for(stage)
        if stage == "check" and extra_light:
            stage_rounds = max(1, stage_rounds - 1)
        if stage == "check" and failed_3d:  # a round to build in code what could not be generated
            stage_rounds += 1
        if stage in REPLY_STAGES:  # its last round, without tools, always fits within the total cap
            stage_rounds = max(1, min(stage_rounds, limits.total_rounds - rounds))
        capped = False  # the cap cut this stage short, and the check stage gives the reply
        if stage == "check" and stage_rounds > 1:  # with one round there is no round to fix what it shows
            seen = look(stage)
            if seen is not None:
                messages.append(seen)

        def fail(message):
            post({"type": "stage", "stage": stage, "state": "failed"})
            return RunResult("stopped", message, rounds, stage)

        def stop_cancelled():
            post({"type": "stage", "stage": stage, "state": "cancelled"})
            return cancelled(stage)

        while True:
            while stage_calls < stage_rounds:
                if cancel.is_set():
                    return stop_cancelled()
                if rounds >= limits.total_rounds - reserve(stage):
                    if rounds >= limits.total_rounds:
                        post({"type": "stage", "stage": stage, "state": "done"})
                        return _stopped_total(limits, last_reply, skipped)
                    capped = True
                    break

                # The check stage's last round goes without tools, so the model has to write its reply. A note
                # after a cut-off reply asked for a step; it is replaced, so the model gets one instruction.
                last = stage in REPLY_STAGES and stage_calls == stage_rounds - 1
                if last:
                    closing = {"role": "user", "content": LAST_EDIT_ROUND if stage == EDIT else LAST_ROUND}
                    if messages[-1] == {"role": "user", "content": cut_off_reply}:
                        messages[-1] = closing
                    elif messages[-1] != closing:
                        messages.append(closing)
                offered = [] if last else tools
                base = quick_llm if quick_llm is not None and quick else llm
                ask = with_pictures_fallback(base, visual)
                post({"type": "thinking", "since": time.monotonic()})
                started = time.monotonic()
                try:
                    try:
                        reply = ask(messages, offered)
                    except Exception as exc:
                        if not _retryable(exc):
                            raise
                        # The lost call may still be billed; one more try with the same messages.
                        debug_log({"stage": stage, "round": rounds + 1, "error": str(exc), "retry": True,
                                   "seconds": round(time.monotonic() - started, 2)}, secrets)
                        if cancel.wait(model_calls.RETRY_AFTER):
                            post({"type": "thinking", "since": None})
                            return stop_cancelled()
                        reply = ask(messages, offered)
                except Exception as exc:  # any failure of the call ends the run with Retry offered
                    debug_log({"stage": stage, "round": rounds + 1, "messages": messages, "error": str(exc),
                               "seconds": round(time.monotonic() - started, 2)}, secrets)
                    rounds += 1
                    post({"type": "thinking", "since": None})
                    post({"type": "round", "n": rounds, "total": limits.total_rounds})
                    return fail(_llm_error(exc))
                debug_log({"stage": stage, "round": rounds + 1, "messages": messages, "reply": reply,
                           "reasoning": base is llm, "seconds": round(time.monotonic() - started, 2)}, secrets)
                post({"type": "thinking", "since": None})
                rounds += 1
                stage_calls += 1
                post({"type": "round", "n": rounds, "total": limits.total_rounds})

                try:
                    message = reply["choices"][0]["message"]
                    cut_off = _cut_off(reply, cap.tokens)
                except (KeyError, IndexError, TypeError, AttributeError):
                    return fail("The model sent a reply that could not be read.")
                calls = message.get("tool_calls") or []
                text = (message.get("content") or "").strip()
                # The cap is mostly hidden reasoning, and asked again the model fills it again: in one follow-up,
                # 9 of 15 replies held nothing else. The stage goes on without reasoning.
                if cut_off:
                    quick = True
                if not calls and cut_off:  # nothing came through; the model is told so and the stage goes on
                    messages.append({"role": "assistant", "content": text or "(cut off)"})
                    messages.append({"role": "user", "content": cut_off_reply})
                    continue
                if not calls and offered and _looks_like_code(text):  # without reasoning it sometimes writes code
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": CODE_AS_TEXT})
                    continue
                if not calls:
                    # The check's reply stays the run's reply after the review's fix stage.
                    if text and (stage != COMPLETE or not last_reply) and not (stage == FIX and review_fix):
                        last_reply = text
                        post({"type": "reply", "stage": stage, "text": text})
                    messages.append({"role": "assistant", "content": text or "Done."})
                    break

                calls = [c for c in calls if isinstance(c, dict) and c.get("id") is not None]
                sent = {"role": "assistant", "content": message.get("content") or ""}
                if calls:
                    sent["tool_calls"] = calls
                messages.append(sent)
                for index, call in enumerate(calls):
                    if cancel.is_set():
                        return stop_cancelled()
                    call_id = call["id"]
                    if index >= limits.max_calls_per_reply:
                        messages.append({"role": "tool", "tool_call_id": call_id, "content":
                                         "ERROR: only %d tool calls are run per reply; send the rest in your next reply"
                                         % limits.max_calls_per_reply})
                        continue
                    fn = call.get("function")
                    name = fn.get("name") if isinstance(fn, dict) else None
                    raw = fn.get("arguments") if isinstance(fn, dict) else None
                    if not isinstance(name, str) or not isinstance(raw, str):
                        name, error = "malformed", "malformed tool call"
                        args = None
                    else:
                        error, args = None, None
                        try:
                            args = json.loads(raw or "{}")
                        except ValueError:
                            error = cut_off_step if cut_off else "arguments were not valid JSON"
                        if error is None and name not in allowed:
                            error = scene_tools.not_a_tool(name)
                        if error is None:
                            try:
                                args = scene_tools.validate(name, args)
                            except scene_tools.ToolArgError as exc:
                                error = str(exc) or "ToolArgError"
                    label = scene_tools.summary(name, args) if error is None else name
                    post({"type": "tool", "id": call_id, "name": name, "summary": label,
                          "state": "running", "detail": ""})
                    content, pictures = None, []
                    if error is None and name == "run_python":
                        post({"type": "code", "id": call_id, "stage": stage, "code": args["code"]})
                    if error is None and name == "run_python" and review is not None and _passes_filter(args["code"]):
                        post({"type": "code_check", "state": "checking"})
                        try:
                            context = execute("chat_context", {})
                        except Exception:
                            context = None
                        if isinstance(context, dict):
                            objects = context.get("objects")
                            allowed_step, reason = review(args["code"], objects if isinstance(objects, list) else [],
                                                          str(context.get("collection") or ""))
                            told = "ERROR: Code check: %s. Rewrite the step without that."
                        else:  # without the chat's names the review cannot tell the chat's objects from the person's
                            allowed_step, reason = False, NO_CONTEXT
                            told = "ERROR: Code check: %s. Rewrite the step."
                        if cancel.is_set():
                            return stop_cancelled()
                        if not allowed_step:
                            refusals += 1
                            reason = clean(reason)
                            post({"type": "code_check", "state": "refused", "reason": reason})
                            post({"type": "tool", "id": call_id, "name": name, "summary": label,
                                  "state": "error", "detail": "Code check: " + reason})
                            messages.append({"role": "tool", "tool_call_id": call_id,
                                             "content": told % reason.rstrip(".")})
                            if refusals >= CHECK_REFUSALS:
                                return fail("Code check stopped the run: %s" % reason)
                            continue
                        refusals = 0
                        post({"type": "code_check", "state": "allowed"})
                    if error is None:
                        try:
                            result = clean(execute(name, args))
                        except StopRun as exc:
                            post({"type": "tool", "id": call_id, "name": name, "summary": label,
                                  "state": "error", "detail": str(exc)})
                            return fail(str(exc))
                        except Exception as exc:
                            error = clean(str(exc) or type(exc).__name__)
                        else:
                            if name == "look_at" and isinstance(result, dict):  # the pictures go as a picture
                                pictures = result.pop("images", None) or []
                            content = json.dumps(result)
                            if name == "run_python":
                                steps.append({"step": len(steps) + 1, "stage": stage,
                                              "summary": step_summary(args["code"], result)})
                            error = _result_error(result)
                            hint = enum_hint(error) if error else ""
                            if hint:
                                result = dict(result, hint=hint)
                                content = json.dumps(result)
                    if error is None:
                        failures[name] = 0
                        post({"type": "tool", "id": call_id, "name": name, "summary": label,
                              "state": "ok", "detail": ""})
                    else:
                        if content is None:
                            content = "ERROR: %s" % error
                        failures[name] = failures.get(name, 0) + 1
                        post({"type": "tool", "id": call_id, "name": name, "summary": label,
                              "state": "error", "detail": _detail(error)})
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": content})
                    if pictures:
                        visual.renders += len(pictures)
                        messages.append(around_message(pictures, result.get("views")))
                        pictures = []
                    if failures.get(name, 0) >= limits.max_failures:
                        stuck = "%s kept failing: %s" % (name, _detail(error))
                        break
                if stuck:
                    break
                if _looks_like_code(text) and not any((c.get("function") or {}).get("name") == "run_python"
                                                      for c in calls):
                    messages.append({"role": "user", "content": CODE_AS_TEXT})  # code beside a camera_view call
            if stuck or capped:
                break
            # A materials stage that left meshes of the run's own bare gets one more round for them, once per run.
            bare = _unpainted(read("read_scene")) if stage == "materials" and not extra_paint else []
            if bare and not cancel.is_set() and rounds < limits.total_rounds:
                extra_paint = True
                stage_rounds += 1
                messages.append({"role": "user", "content": NO_MATERIAL % ", ".join(bare)})
                continue
            # A light stage that left the scene without lights of its own gets one more round, once per run.
            if (stage == "light" and not extra_light and not cancel.is_set() and rounds < limits.total_rounds
                    and _has_no_lights(read("read_scene"))):
                extra_light = True
                stage_rounds += 1
                messages.append({"role": "user", "content": NO_LIGHTS})
                continue
            # The visual check: the stage's work is done; one more round fixes what the render shows.
            if ((stage in LOOK_AFTER or stage == EDIT) and stage not in looked and not cancel.is_set()
                    and rounds < limits.total_rounds - reserve(stage)):
                seen = look(stage)
                if seen is not None:
                    stage_rounds += EDIT_LOOK_ROUNDS if stage == EDIT else 1
                    messages.append(seen)
                    continue
            break

        debug_log({"stage": stage, "end": True, "messages": messages[2:]}, secrets)
        if stuck:
            # Nothing can follow a stuck layout, and two stuck stages in a row mean the run is going nowhere; else
            # the stage keeps what it built and the run goes on.
            if stage == "layout" or stuck_before:
                return fail("Stopped: %s" % stuck)
            post({"type": "stage", "stage": stage, "state": "partial"})
            skipped.append(PARTLY_DONE % (stage.capitalize(), stuck))
            stuck_before, failures = True, {}
            continue
        stuck_before = False
        post({"type": "stage", "stage": stage, "state": "done"})
        if stage in ("layout", FIX, COMPLETE):
            settle_props(stage)
        if stage == FIX:  # the reply names only the fixes the add-on measured as gone, never the model's word for it
            undone = False
            if review_fix:
                review_fix = False
                undone = review_after()
            fixed = "" if undone else verified_line(fix_problems, measured())
            if fixed:
                skipped.append(fixed)
        if capped:
            to_check()
            continue
        # Things measured in the wrong place get a fix stage: after the layout (when no detail stage follows) and
        # before the check.
        if stage != FIX and (stage == "layout" and DETAIL not in queue or queue and queue[0] == "check"):
            fix_if_needed()
        # After the layout and the check, every planned thing must be in the scene: what is missing gets a short
        # stage of its own, within the total cap or from the extra rounds. A complete stage that built some of the
        # list goes again for the rest, while it keeps building.
        if (generation is not None and generation.complete and stage in ("layout", "check", COMPLETE)
                and not cancel.is_set()):
            before = len(missing) if stage == COMPLETE else None
            try:
                missing = list(execute("missing_items", {}) or [])
            except Exception:  # the check is a safety net; the run goes on without it
                missing = []
            if stage == COMPLETE:
                completes += 1
                if before is not None and len(missing) >= before or completes >= COMPLETE_REPEATS:
                    missing = []  # no progress, or done enough times: the reply says what is not built
            if missing and room(COMPLETE_ROUNDS):
                queue.insert(0, COMPLETE)
        # Once the check and what it left to build are done, the scene review judges the scene; what it keeps gets
        # one more fix stage, only when all its rounds fit within the person's limit.
        checked = checked or stage == "check"
        if scene_review is not None and checked and not reviewed and not queue and not cancel.is_set():
            reviewed = True
            review_found = scene_review.find()
            if review_found and fits(limits.rounds_for(FIX)):
                fix_problems, review_fix = measured(), True
                scene_review.mark()
                queue.insert(0, FIX)
            elif review_found:
                skipped.append(scene_review_text.done_line(review_found, None, scene_review_text.NO_ROOM))

    if not last_reply and rounds >= limits.total_rounds:  # the check's last round came back without a reply
        return _stopped_total(limits, "", skipped)
    still = problems_line(measured())  # the reply never reads as if the scene were fine while they remain
    if still:
        skipped.append(still)
    return RunResult("done", "\n".join([last_reply] + skipped).strip(), rounds, None)
