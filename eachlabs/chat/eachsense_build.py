"""A scene build each::sense runs: the stage loop and its model calls run there, every tool runs here. No Blender here.

The plan card, the 3D objects and textures it orders and the concept and reference pictures are settled here first,
as for the local loop; their outcome goes to each::sense as the ``build_inputs`` answer, with the scene's earlier
prompts, the helper library's offer and whether free Poly Haven assets are on, and each::sense runs the detail
stage, the renders it looks at and the scene review through the tools it asks for. A build each::sense does not
take raises ``NotStarted``: nothing ran there, so the caller builds it with the local loop.

``run`` starts the build (``POST /v1/eachsense/scenes``, surface ``blender``), polls it, and answers each tool
request with ``execute``, the chat's own, which runs on Blender's main thread. A code step gets the Code check review
first when one is given. What the build reports becomes the chat's usual events, so the bar, one undo step per stage
and Show code work as they do for a run of the local loop. Everything sent back passes ``code_check.redact``.
"""

import itertools
import json
import time

from .. import code_check, scene_tools
from ..api_client import ApiError
from .run_types import RunResult, StopRun

SURFACE = "blender"
STAGES = ("layout", "materials", "light", "camera", "check")  # the stages a build asks for; detail comes with them
# Stages the bar shows a dot for; a step named otherwise (the scene review's) leaves the active stage alone.
SHOWN = ("layout", "detail", "materials", "light", "camera", "check", "fix", "complete")
# The loop's own asks: measurements, the plan's lists, the detail stage's bookkeeping. No line on the bar.
LOOP_TOOLS = ("placement_problems", "prune", "settle", "build_inputs", "generation_notes", "missing_items",
              "review_mark", "review_undo", "detail_roots", "detail_read", "detail_measure", "detail_copies",
              "reference_picture", "candidate_stash", "candidate_restore", "candidate_drop")
# Renders: the bar says "Looking…" while they run instead of a tool line.
LOOKS = ("render_frames", "review_views", "detail_look", "candidate_shot")
CODE_TOOLS = ("run_python", "detail_step")  # a step of code: Code check reviews it first
ANSWER_BYTES = 2 * 1024 * 1024 - 4096  # the API's cap on a tool answer, less room for the request around it
QUALITY_TIERS = {"PROTOTYPE": "prototype", "ADVANCED": "final"}
TIER_ROUNDS = {"prototype": 10, "final": 15, "best": 15}  # the service's totals, for the bar's round count
POLL_SECONDS = 0.5
POLL_FAILURES = 5  # failed polls in a row that end the run
OFFER_SECONDS = 300.0  # how long an answer to "is it offered" is kept
CANCELLED = "Stopped. What was built is kept."
REFUSED = "Code check: %s. Rewrite the step without that."
TOO_BIG = "Blender's answer (%d bytes) was too big to send; go on without it."

_offers = {}  # base URL -> (offered, when it was asked)


class NotStarted(Exception):
    """each::sense did not take the build; nothing of it ran there."""


def offered(client, now=time.monotonic):
    """Whether the API runs Blender scene builds for this key's organization; ``False`` when it cannot tell."""
    key = (getattr(client, "base_url", None), getattr(client, "api_key", None))
    found = _offers.get(key)
    if found is not None and now() - found[1] < OFFER_SECONDS:
        return found[0]
    try:
        value = bool(client.eachsense_capabilities().get("blender_scene"))
    except Exception:  # an API without the route, a network error, a client without the call: the local loop runs
        value = False
    _offers[key] = (value, now())
    return value


def forget(client):
    """Drop the kept answer to "is it offered", so the next run asks the API again."""
    _offers.pop((getattr(client, "base_url", None), getattr(client, "api_key", None)), None)


def tier(quality, model, best_model):
    """The build's tier from the add-on's quality mode; Final on the "Best quality" model is ``best``."""
    found = QUALITY_TIERS.get(quality, "prototype")
    return "best" if found == "final" and model == best_model else found


def scopes(stages):
    """The stages to ask for, or ``None`` for all of them."""
    asked = [s for s in STAGES if s in stages]
    return None if len(asked) == len(STAGES) else asked


def fitted(inputs):
    """``inputs`` as sent: without the concept picture when the answer would pass the API's cap."""
    inputs = dict(inputs or {})
    if inputs.get("concept") and len(json.dumps(inputs)) > ANSWER_BYTES:
        inputs["concept"] = ""
    return inputs


def run(client, prompt, execute, post, cancel, *, stages=STAGES, scope="", session_id=None, blender=None,
        tier="prototype", secrets=(), review=None, on_session=None, inputs=None, local=None, shrink=None,
        sleep=time.sleep, clock=time.monotonic):
    """Run one build on each::sense and return a ``RunResult``.

    ``execute(name, args)`` runs a tool on Blender's main thread; ``review(code, objects, collection)`` is Code
    check, ``None`` when it is off. ``on_session(session_id)`` is told the build's session once it started.
    ``inputs``: the ``build_inputs`` answer (the plan's brief, the concept picture, the detail and review settings,
    the limits, the scene's earlier prompts and the helper library's offer); ``local``: ``{tool: fn(args)}`` for tools answered on this worker thread, not Blender's main
    thread (a reference picture still drawing is waited for here). ``shrink(url) -> url`` makes a render's pictures
    smaller before they are sent; ``None`` sends them as rendered.
    Raises ``NotStarted`` when the build could not be started (busy, switched off since it was offered, no
    connection)."""
    local = dict(local or {})
    sent_inputs = fitted(inputs)
    body = {"instruction": prompt, "surface": SURFACE, "scope": scope, "tier": tier}
    if blender:
        body["blender_version"] = "%d.%d" % tuple(blender[:2])
    asked = scopes(stages)
    if asked is not None:
        body["scopes"] = asked
    if session_id:
        body["session_id"] = session_id
    try:
        started = client.start_scene(body)
    except Exception as exc:
        forget(client)  # the next run asks whether it is still offered
        raise NotStarted(str(exc) or type(exc).__name__) from exc
    run_id = started["run_id"]
    if on_session is not None and started.get("session_id"):
        on_session(started["session_id"])

    def clean(value):
        return code_check.redact(value, secrets)

    ids = itertools.count(1)
    state = {"rounds": 0, "active": None}

    def answer(tool):
        name, args, seq = tool["name"], tool.get("args") or {}, tool["seq"]
        if name == "build_inputs":
            client.answer_scene_tool(run_id, seq, result=clean(sent_inputs))
            return
        looking = name in LOOKS
        shown = name not in LOOP_TOOLS and not looking
        shown_name = "run_python" if name == "detail_step" else name  # a detail step reads as a step of code
        call_id = "eachsense-%d" % next(ids)
        try:
            label = scene_tools.summary(shown_name, args)
        except Exception:  # a label only
            label = name
        if shown:
            post({"type": "tool", "id": call_id, "name": shown_name, "summary": label, "state": "running",
                  "detail": ""})
        if name in CODE_TOOLS:
            stage = "detail" if name == "detail_step" else state["active"] or ""
            post({"type": "code", "id": call_id, "stage": stage, "code": args.get("code") or ""})
            refused = _review(review, execute, args.get("code") or "", post)
            if refused:
                reason = clean(refused)
                post({"type": "tool", "id": call_id, "name": shown_name, "summary": label, "state": "error",
                      "detail": "Code check: " + reason})
                client.answer_scene_tool(run_id, seq, error=REFUSED % reason.rstrip("."))
                return
        if looking:
            post({"type": "looking", "state": True})
        try:
            result = clean(local[name](args) if name in local else execute(name, args))
        except StopRun:
            raise
        except Exception as exc:  # the model reads it and tries again
            error = clean(str(exc) or type(exc).__name__)
            if shown:
                post({"type": "tool", "id": call_id, "name": shown_name, "summary": label, "state": "error",
                      "detail": error})
            client.answer_scene_tool(run_id, seq, error=error)
            return
        finally:
            if looking:
                post({"type": "looking", "state": False})
        if shrink is not None and isinstance(result, dict) and isinstance(result.get("images"), list):
            result = dict(result, images=[_shrunk(shrink, url) for url in result["images"]])
        error = result.get("error") if isinstance(result, dict) and result.get("ok") is False else None
        if shown:
            post({"type": "tool", "id": call_id, "name": shown_name, "summary": label,
                  "state": "error" if error else "ok", "detail": str(error or "")[:300]})
        try:
            client.answer_scene_tool(run_id, seq, result=result)
        except ApiError as exc:  # refused (too big, most often): the build reads it as the tool's error and goes on
            if exc.status not in (400, 413, 429) or exc.rate_limited:
                raise
            client.answer_scene_tool(run_id, seq, error=TOO_BIG % len(json.dumps(result)))

    answered, ended, last_step, thinking, stop_asked, failures = 0, 0, None, False, False, 0
    sent_limits = sent_inputs.get("limits") if isinstance(sent_inputs.get("limits"), dict) else {}
    total = max(TIER_ROUNDS.get(tier, TIER_ROUNDS["final"]), int(sent_limits.get("total_rounds") or 0))
    build = started
    while True:
        if cancel.is_set() and not stop_asked:
            stop_asked = True
            try:
                client.cancel_scene(run_id)
            except ApiError:
                pass
        try:
            build = client.get_scene(run_id)
            failures = 0
        except ApiError:
            failures += 1
            if failures >= POLL_FAILURES:
                raise
            sleep(1.0)
            continue
        step = build.get("step") or ""
        if step != last_step:
            last_step = step
            name, _, rest = step.partition(":")
            name, rest = name.strip(), rest.strip()
            stage_step = name in SHOWN
            if stage_step and name != state["active"]:
                state["active"] = name
                post({"type": "stage", "stage": name, "state": "active"})
            if rest == "thinking":
                if stage_step:  # the scene review's calls are no rounds of the build
                    state["rounds"] += 1
                    post({"type": "round", "n": state["rounds"], "total": max(total, state["rounds"])})
                thinking = True
                post({"type": "thinking", "since": clock()})
            elif thinking:
                thinking = False
                post({"type": "thinking", "since": None})
        # After the step: a poll that sees a stage end and its last round reports the round first.
        for stage in (build.get("stages") or [])[ended:]:
            post({"type": "stage", "stage": stage["name"], "state": "done" if stage.get("ok") else "partial"})
            if stage["name"] == state["active"]:
                state["active"] = None
        ended = len(build.get("stages") or [])
        if build.get("status") != "running":
            break
        tool = build.get("tool")
        if tool and tool.get("seq", 0) > answered:
            answered = tool["seq"]
            try:
                answer(tool)
            except StopRun as exc:  # a step changed a setting: the build ends here
                try:
                    client.cancel_scene(run_id)
                except ApiError:
                    pass
                if state["active"]:
                    post({"type": "stage", "stage": state["active"], "state": "failed"})
                return RunResult("stopped", str(exc), state["rounds"], state["active"])
            continue
        sleep(POLL_SECONDS)
    if thinking:
        post({"type": "thinking", "since": None})
    if build.get("status") == "done":
        return RunResult("done", build.get("reply") or "", state["rounds"], None)
    if stop_asked:
        if state["active"]:
            post({"type": "stage", "stage": state["active"], "state": "cancelled"})
        return RunResult("cancelled", CANCELLED, state["rounds"], state["active"])
    if state["active"]:
        post({"type": "stage", "stage": state["active"], "state": "failed"})
    return RunResult("stopped", build.get("error") or "each::sense stopped the build.", state["rounds"],
                     state["active"])


def _shrunk(shrink, url):
    try:
        return shrink(url)
    except Exception:  # sent as rendered
        return url


def _review(review, execute, code, post):
    """Code check on a code step the filter lets through: the reason it was refused, else ``None``."""
    if review is None:
        return None
    try:
        code_check.check(code)
    except code_check.Refused:
        return None  # the filter refuses it again when it runs, and the model reads why
    post({"type": "code_check", "state": "checking"})
    try:
        context = execute("chat_context", {})
    except Exception:
        context = None
    if not isinstance(context, dict):
        post({"type": "code_check", "state": "refused", "reason": "the chat's objects could not be read"})
        return "the chat's objects could not be read"
    objects = context.get("objects")
    allowed, reason = review(code, objects if isinstance(objects, list) else [], str(context.get("collection") or ""))
    if allowed:
        post({"type": "code_check", "state": "allowed"})
        return None
    post({"type": "code_check", "state": "refused", "reason": reason})
    return reason or "refused"
