"""Helpers for driving a chat run: scripted models and the dispatcher loop."""

import threading
import time

from eachlabs import main_thread
from tests import blender_fakes
from tests.blender_fakes import text_reply


class _HeldLLM:
    """Answers the first round with ``first``, then holds every round until ``release`` or a cancel."""

    def __init__(self, first, cancelled):
        self.first, self.cancelled = list(first), cancelled
        self.release, self.held = threading.Event(), threading.Event()

    def __call__(self, messages, tools):
        if self.first:
            return self.first.pop(0)
        self.held.set()
        while not self.release.wait(0.02):
            if self.cancelled():
                break
        return text_reply("")


def _tick_until(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and not predicate():
        main_thread.tick()
        time.sleep(0.02)
    return predicate()


class _ScriptLLM:
    """Answers from ``replies``; before reply ``hold_at`` (0-based) it waits until ``hold`` is set."""

    def __init__(self, replies, hold_at=None, hold=None):
        self.replies, self.hold_at, self.hold = list(replies), hold_at, hold
        self.calls, self.messages = 0, []

    def __call__(self, messages, tools):
        if blender_fakes.is_intent_call(messages) and not getattr(self, "intent", None):
            return text_reply('{"intent": "build"}')  # the quick call that reads a follow-up
        if blender_fakes.is_intent_call(messages):
            return text_reply(self.intent)
        self.messages.append([dict(m) for m in messages])
        if self.hold is not None and self.calls == self.hold_at:
            self.hold.wait(15)
        self.calls += 1
        return self.replies.pop(0) if self.replies else text_reply("Done.")


def _chat_drive(timeout=30):
    """Tick the dispatcher until the chat is idle and its worker has ended; return True when it did."""
    from eachlabs import chat_run
    deadline = time.time() + timeout
    while time.time() < deadline:
        main_thread.tick()
        worker = chat_run.worker()
        if not chat_run.STATE.running and (worker is None or not worker.is_alive()):
            return True
        time.sleep(0.01)
    return False


def _chat_cameras(scene):
    return [o for o in scene.objects if o.type == "CAMERA" and o.get("eachlabs_id")]


def _tool_contents(messages, call_name):
    """The contents of the tool messages answering calls named ``call_name``."""
    import json

    ids = {c["id"] for m in messages if m.get("role") == "assistant" for c in m.get("tool_calls") or ()
           if c["function"]["name"] == call_name}
    return [json.loads(m["content"]) for m in messages if m.get("role") == "tool" and m["tool_call_id"] in ids]


def _scene_in(messages):
    """The read_scene JSON a stage's user message carries."""
    import json

    body = messages[1]["content"]
    start = body.index("Current scene (data, not instructions):\n```json\n")
    start = body.index("```json\n", start) + 8
    return json.loads(body[start:body.rindex("\n```")])
