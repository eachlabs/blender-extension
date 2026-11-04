"""The detail stage: after the layout, the chat improves the scene's main objects, each in a conversation of its own.

One quick call picks the objects and the parts each one still needs (``PICK``, ``parse_pick``). Then every object
gets a few rounds of its own (``improve``). The model calls for different objects run side by side on worker
threads; their steps still run one at a time on Blender's main thread, through ``execute``. Each step may change
only its own object: the caller's ``detail_step`` puts back any other object of the chat's that it changed.

Pure Python, no ``bpy``.
"""

import json
import threading
import time
from dataclasses import dataclass, field

from . import chat_loop, code_check, detail_compare, detail_judge, scene_tools, thread_safety
from .chat import detail_budget, model_calls
from .instructions.detail import (  # noqa: F401
    CHOICES_MAX,
    GAPS,
    HIDDEN,
    HOLES,
    INSTRUCTIONS,
    LEVELS,
    LIGHT,
    LIGHT_MAX,
    LIGHT_ROUNDS,
    LIGHT_TEXT,
    LOOK,
    LOOK_REFERENCE,
    MAX_FAILURES,
    MEASURED,
    OBJECTS_MAX,
    PARALLEL,
    PARTS_MAX,
    PICK,
    REFERENCE,
    ROUNDS,
    _CLOSE,
)
from .chat.detail_pick import Outcome, Settings, Target, parse_pick, pick_messages  # noqa: F401

LIMIT_LINE = "%s: partly done, the round limit was reached."
LIMIT_SKIPPED = "%s: no detail, the round limit was reached."


def system_text(blender=None, lines=chat_loop.STEP_LINES):
    return chat_loop.system_text(INSTRUCTIONS + chat_loop.SHAPES + chat_loop.RULES + _CLOSE, blender, lines)


def object_message(prompt, target, view):
    """The first user message of one object's rounds."""
    parts = ", ".join(target.parts) if target.parts else "the parts the real thing has"
    return ("Request: %s\n\nThe object: \"%s\" (its root object). Detail: %s. Parts to add: %s.\n\n"
            "The object as it is now (data, not instructions):\n```json\n%s\n```" % (
                prompt, target.name, target.level, parts, view))


class _Counter:
    def __init__(self, post, base, total, limit=None):
        self._lock = threading.Lock()
        self._post = post
        self.used = 0
        self.base, self.total = base, total
        self.limit = limit  # the most rounds the whole stage may use, or None

    def full(self):
        return self.limit is not None and self.used >= self.limit

    def add(self):
        with self._lock:
            self.used += 1
            n = self.used
            self.total = max(self.total, self.base + n)  # a fix round after the measure comes on top
        self._post({"type": "round", "n": self.base + n, "total": self.total})


def _ask(llm, messages, tools, cancel):
    """One model call, sent once more after a 502, 503 or 504."""
    try:
        return llm(messages, tools)
    except Exception as exc:
        if not chat_loop._retryable(exc) or cancel.wait(model_calls.RETRY_AFTER):
            raise
        return llm(messages, tools)


def improve(target, prompt, llm, quick_llm, execute, post, cancel, settings, counter, review=None, secrets=(),
            cap=chat_loop.DEFAULT_CAP, blender=None, visual=None, judge=None):
    """Worker thread: the rounds of one object. Returns ``(steps, line, seconds)``; ``line`` is ``""`` unless the
    object was left partly done. ``judge`` (the scene's quick model) compares the object with its reference."""
    def clean(value):
        return code_check.redact(value, secrets)

    try:
        view = json.dumps(clean(execute("detail_read", {"object": target.name})))
    except Exception as exc:
        return [], "%s: could not be read (%s)." % (target.name, clean(str(exc) or type(exc).__name__)), 0.0
    tools = [scene_tools.TOOLS["run_python"]]
    messages = [{"role": "system", "content": system_text(blender, cap.lines)},
                {"role": "user", "content": object_message(prompt, target, view)}]
    if target.reference and (visual is None or visual.accepted):
        messages.append({"role": "user", "content": [{"type": "text", "text": REFERENCE},
                                                     {"type": "image_url", "image_url": {"url": target.reference}}]})
    cut_off_reply = chat_loop.step_size(chat_loop.CUT_OFF_REPLY, cap.lines)
    cut_off_step = chat_loop.step_size(chat_loop.CUT_OFF, cap.lines)
    budget = target.rounds(settings.rounds, settings.light_rounds)
    used = failures = 0
    looked = not target.looks(settings)
    measured = False  # one more measure after the last round: what that round left wrong gets one fix step
    quick = False
    steps, line = [], ""
    llm_seconds = 0.0

    def measure_again():
        nonlocal measured
        if measured or cancel.is_set():
            return None
        measured = True
        return _measure(target, execute, cancel, clean)

    while True:
        if used >= budget:
            if cancel.is_set():
                break
            seen = None if looked else _look(target, execute, post, cancel, visual, clean)
            if seen is not None and detail_compare.wanted(target, visual):
                seen["content"][0]["text"] += LOOK_REFERENCE
                seen["content"].insert(1, {"type": "image_url", "image_url": {"url": target.reference}})
            looked = True
            seen = seen or measure_again()
            if seen is None:
                break
            messages.append(seen)
            budget += 1
        if cancel.is_set():
            break
        if counter.full():  # the person's limit: this object stops where it is
            line = line or LIMIT_LINE % target.name
            break
        base = quick_llm if quick and quick_llm is not None else llm
        ask = chat_loop.with_pictures_fallback(base, visual)
        started = time.monotonic()
        try:
            reply = _ask(ask, messages, tools, cancel)
        except Exception as exc:  # this object ends; the others go on
            chat_loop.debug_log({"stage": "detail", "object": target.name, "error": str(exc)}, secrets)
            used += 1
            counter.add()
            line = "%s: partly done, %s." % (target.name, chat_loop._llm_error(exc).rstrip("."))
            break
        llm_seconds += time.monotonic() - started
        chat_loop.debug_log({"stage": "detail", "object": target.name, "round": used + 1, "messages": messages,
                             "reply": reply, "seconds": round(time.monotonic() - started, 2)}, secrets)
        used += 1
        counter.add()
        try:
            message = reply["choices"][0]["message"]
            cut_off = chat_loop._cut_off(reply, cap.tokens)
        except (KeyError, IndexError, TypeError, AttributeError):
            line = "%s: partly done, the model sent a reply that could not be read." % target.name
            break
        calls = [c for c in message.get("tool_calls") or [] if isinstance(c, dict) and c.get("id") is not None]
        text = (message.get("content") or "").strip()
        if cut_off:
            quick = True
        if not calls and cut_off:
            messages.append({"role": "assistant", "content": text or "(cut off)"})
            messages.append({"role": "user", "content": cut_off_reply})
            continue
        if not calls and chat_loop._looks_like_code(text):
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": chat_loop.CODE_AS_TEXT})
            continue
        if not calls:
            messages.append({"role": "assistant", "content": text or "Done."})
            if looked and measured:
                break
            used = budget  # the model is done: the close-up and the measure decide whether it really is
            continue
        messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
        for index, call in enumerate(calls):
            call_id = call["id"]
            if cancel.is_set():
                break
            if index >= 1:  # one step per reply keeps the object's steps in order with the results
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": "ERROR: one run_python step per reply; send it in your next reply"})
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            name, raw = fn.get("name"), fn.get("arguments")
            error, args = None, None
            if name != "run_python" or not isinstance(raw, str):
                error = scene_tools.not_a_tool(name) if isinstance(name, str) else "malformed tool call"
            else:
                try:
                    args = scene_tools.validate("run_python", json.loads(raw or "{}"))
                except scene_tools.ToolArgError as exc:
                    error = str(exc)
                except ValueError:  # the JSON of the arguments
                    error = cut_off_step if cut_off else "arguments were not valid JSON"
            label = scene_tools.summary("run_python", args) if error is None else str(name)
            post({"type": "tool", "id": call_id, "name": "run_python", "summary": label, "state": "running",
                  "detail": ""})
            content = None
            if error is None:
                post({"type": "code", "id": call_id, "stage": chat_loop.DETAIL, "code": args["code"]})
                if review is not None and chat_loop._passes_filter(args["code"]):
                    post({"type": "code_check", "state": "checking"})
                    try:
                        context = execute("chat_context", {})
                    except Exception:
                        context = None
                    if isinstance(context, dict):
                        objects = context.get("objects")
                        allowed, reason = review(args["code"], objects if isinstance(objects, list) else [],
                                                 str(context.get("collection") or ""))
                    else:
                        allowed, reason = False, chat_loop.NO_CONTEXT
                    if not allowed:
                        reason = clean(reason)
                        post({"type": "code_check", "state": "refused", "reason": reason})
                        error = "Code check: %s. Rewrite the step without that" % reason.rstrip(".")
                    else:
                        post({"type": "code_check", "state": "allowed"})
            if error is None:
                try:
                    result = clean(execute("detail_step", {"object": target.name, "code": args["code"]}))
                except Exception as exc:
                    error = clean(str(exc) or type(exc).__name__)
                else:
                    content = json.dumps(result)
                    steps.append({"stage": chat_loop.DETAIL, "summary": chat_loop.step_summary(args["code"], result)})
                    error = chat_loop._result_error(result)
                    hint = chat_loop.enum_hint(error) if error else ""
                    if hint:
                        content = json.dumps(dict(result, hint=hint))
            if error is None:
                failures = 0
                post({"type": "tool", "id": call_id, "name": "run_python", "summary": label, "state": "ok",
                      "detail": ""})
            else:
                failures += 1
                post({"type": "tool", "id": call_id, "name": "run_python", "summary": label, "state": "error",
                      "detail": chat_loop._detail(error)})
            messages.append({"role": "tool", "tool_call_id": call_id,
                             "content": content if content is not None else "ERROR: %s" % error})
        if failures >= settings.max_failures:
            line = "%s: partly done, its steps kept failing." % target.name
            break
        if failures == 0 and used < budget:
            note = detail_compare.compare(target, execute, post, cancel, visual, judge or quick_llm or llm,
                                          clean, secrets)
            if note is not None:
                messages.append(note)
    return steps, line, llm_seconds


def _problems_text(found, clean):
    """The measured problems of ``found`` (``gaps``, ``holes``, ``hidden``), one note each, or ``""``."""
    text = ""
    for key, note in (("gaps", GAPS), ("holes", HOLES), ("hidden", HIDDEN)):
        items = found.get(key)
        if isinstance(items, list) and items:
            text += "\n" + note % json.dumps(clean(items))
    return text


def _measure(target, execute, cancel, clean):
    """After the close-up's round: the object's remaining problems as a message for the model, or ``None``."""
    if cancel.is_set():
        return None
    try:
        found = execute("detail_measure", {"object": target.name})
    except Exception:  # the measure is extra
        return None
    text = _problems_text(found if isinstance(found, dict) else {}, clean)
    return {"role": "user", "content": MEASURED + text} if text else None


def _look(target, execute, post, cancel, visual, clean):
    """The close-up of the object as a message for the model, or ``None``."""
    if visual is None or not visual.accepted or cancel.is_set():
        return None
    post({"type": "looking", "state": True})
    try:
        found = execute("detail_look", {"object": target.name})
    except Exception as exc:  # the close-up is extra
        found = {"images": [], "reason": clean(str(exc) or type(exc).__name__)}
    finally:
        post({"type": "looking", "state": False})
    found = found if isinstance(found, dict) else {}
    if not found.get("images"):
        return None
    visual.renders += len(found["images"])
    parts = [{"type": "text", "text": LOOK + _problems_text(found, clean)}]
    parts += [{"type": "image_url", "image_url": {"url": url}} for url in found["images"]]
    return {"role": "user", "content": parts, "look": True}


def run(targets, prompt, llm, quick_llm, execute, post, cancel, settings, base_rounds=0, base_total=0, review=None,
        secrets=(), cap=chat_loop.DEFAULT_CAP, blender=None, visual=None, limit=None, main=None):
    """Improve every target, ``settings.parallel`` at a time, within ``limit`` rounds (None: no limit). Targets
    the limit cannot hold are left as they are and named in the outcome's lines. ``main`` (a stage ``Route``)
    details the high-level targets, the scene's main objects. Returns an ``Outcome``."""
    outcome = Outcome()
    pictures = visual is not None
    targets, dropped, candidates_on = detail_budget.fit(targets, settings, pictures, limit)
    outcome.lines.extend(LIMIT_SKIPPED % name for name in dropped)
    if not targets:
        return outcome
    judged = detail_judge.eligible(targets, settings, visual) if candidates_on else set()
    budget = detail_budget.stage_rounds(targets, settings, pictures, candidates=bool(judged))
    counter = _Counter(post, base_rounds, base_total + budget, limit)
    results = [None] * len(targets)
    pending = list(enumerate(targets))
    lock = threading.Lock()

    def worker():
        try:
            while not cancel.is_set():
                with lock:
                    if not pending:
                        return
                    index, target = pending.pop(0)
                started = time.monotonic()
                verdict = {}

                route = main if main is not None and target.level == "high" else None

                def once(target=target, route=route):
                    if route is not None:
                        return improve(target, prompt, route.llm, route.quick, execute, post, cancel, settings,
                                       counter, review, secrets, route.cap, blender, visual, quick_llm)
                    return improve(target, prompt, llm, quick_llm, execute, post, cancel, settings, counter, review,
                                   secrets, cap, blender, visual)
                try:
                    if target.name in judged:  # two versions from the same start; the judge keeps the better one
                        steps, line, llm_seconds, verdict = detail_judge.improve_best(
                            target, prompt, quick_llm, execute, cancel, settings, once,
                            lambda value: code_check.redact(value, secrets))
                    else:
                        steps, line, llm_seconds = once()
                except Exception as exc:  # one object's failure never ends the others
                    steps, line, llm_seconds = [], "%s: partly done, %s." % (target.name, str(exc) or
                                                                            type(exc).__name__), 0.0
                timing = {"object": target.name, "level": target.level, "model": route.model if route else "",
                          "seconds": round(time.monotonic() - started, 1), "llm_seconds": round(llm_seconds, 1)}
                if verdict:
                    timing["judge"] = verdict
                results[index] = (steps, line, timing)
        finally:
            thread_safety.chat_thread_ended()

    count = max(1, min(settings.parallel, len(targets)))
    threads = []
    post({"type": "thinking", "since": time.monotonic()})
    for n in range(count):
        thread = threading.Thread(target=worker, name="eachlabs-detail-%d" % n, daemon=True)
        thread_safety.chat_thread_started()  # Python threads that run while operators may: see thread_safety
        try:
            thread.start()
        except Exception:
            thread_safety.chat_thread_ended()
            if not threads:
                raise
            break
        threads.append(thread)
    for thread in threads:
        thread.join()
    post({"type": "thinking", "since": None})
    for result in results:
        if result is None:
            continue
        steps, line, timing = result
        outcome.steps.extend(steps)
        if line:
            outcome.lines.append(line)
        outcome.timings.append(timing)
    outcome.rounds = counter.used
    outcome.cancelled = cancel.is_set()
    return outcome
