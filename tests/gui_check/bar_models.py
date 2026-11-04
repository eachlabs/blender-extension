"""Scripted models and settings for the bar scenario."""

import bpy

from tests import blender_fakes
from tests.blender_fakes import FakeLLM, text_reply
from tests.gui_check.common import hold


REVIEWS = []  # Code check calls the fake model answered
REFUSE = []  # one entry per review to refuse, from the next one on


class SlowLLM(FakeLLM):
    """Slow model rounds; Code check's reviews are allowed at once and do not count as rounds."""

    def __call__(self, messages, tools):
        if len(messages) > 1 and "Code to review" in str(messages[1].get("content")):
            REVIEWS.append(1)
            if REFUSE:
                REFUSE.pop()
                self.pause = 5.0  # the rewrite takes a while, so Show code and Stop can be pressed
                return text_reply('{"allow": false, "reason": "it tried to read a file outside Blender"}')
            return text_reply('{"allow": true, "reason": ""}')
        hold(getattr(self, "pause", 0.4))  # not time.sleep: see parked()
        self.pause = 0.4
        return super().__call__(messages, tools)


class FailFirstLLM(SlowLLM):
    """The first round fails like a server error; the rest follow the script."""

    def __call__(self, messages, tools):
        if blender_fakes.is_intent_call(messages):  # the quick call that reads the prompt is not a round
            return super().__call__(messages, tools)
        if not getattr(self, "failed", False):
            self.failed = True
            from eachlabs.api_client import ApiError
            raise ApiError("The server answered HTTP 502.")
        return super().__call__(messages, tools)


def addon_prefs():
    from eachlabs import preferences

    return preferences.get_preferences(bpy.context)


def code_windows():
    """Windows with a Text Editor showing the Eachlabs code text."""
    return [w for w in bpy.context.window_manager.windows for a in w.screen.areas
            if a.type == "TEXT_EDITOR" and a.spaces.active.text and a.spaces.active.text.name == "Eachlabs code"]
