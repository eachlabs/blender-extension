"""Show code: every step's Blender Python in one Text datablock, opened in a Text Editor."""

import bpy

from .live import chat_run
from .. import code_check, thread_safety


CODE_TEXT = "Eachlabs code"  # the Text datablock Show code writes
SHOW_CODE_LATER = "The code is in the text \"%s\". Open it in a Text Editor." % CODE_TEXT



def _code_runs():
    """Every run of the current scene with its steps, oldest first; without a scene, the last run only."""
    runs = list(chat_run._build.code_runs) if chat_run._build is not None else []
    if not any(r["steps"] is chat_run.STATE.code_steps for r in runs) and chat_run.STATE.code_steps:
        runs.append({"prompt": chat_run.STATE.prompt, "retry": False, "steps": chat_run.STATE.code_steps})
    return runs



def code_text():
    """Every prompt of the current scene and its steps as one text, one section per prompt and per step, newest
    last; the API key is already redacted."""
    secrets = chat_run._run.secrets if chat_run._run is not None else ()
    lines = ["# The Blender Python the chat wrote for this scene.",
             "# One section per prompt and per step, newest last. A refused or failed step says so in its heading.",
             ""]
    for number, run in enumerate(_code_runs(), 1):
        prompt = code_check.redact(" ".join(run["prompt"].split()), secrets)
        lines += ["# ==== Prompt %d%s: %s ====" % (number, " (retry)" if run.get("retry") else "", prompt), ""]
        if run.get("concept"):
            lines += ["# Concept picture: %s" % run["concept"], ""]
        for n, step in enumerate(run["steps"], 1):
            state, detail = step.get("state"), step.get("detail") or ""
            if state == "ok":
                outcome = "ran"
            elif detail.startswith("Code check:"):
                outcome = "not run, " + detail
            elif state == "error":
                outcome = "failed: " + detail
            else:
                outcome = "not finished"
            lines += ["# ---- Step %d · %s · %s ----" % (n, (step.get("stage") or "").capitalize(), outcome),
                      step.get("code", "").rstrip("\n"), ""]
    return "\n".join(lines)



def _text_editor(context):
    """A Text Editor in any open window, else ``None``."""
    wm = context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            if area.type == "TEXT_EDITOR":
                return area
    return None



def show_code(context):
    """Write the run's steps into the ``Eachlabs code`` text and show it in a Text Editor: an open one, else
    a new window. Returns the text and a message for the person when no editor could be opened, else ``""``."""
    text = bpy.data.texts.get(CODE_TEXT) or bpy.data.texts.new(CODE_TEXT)
    text.clear()
    text.write(code_text())
    if bpy.app.background:
        return text, ""
    area = _text_editor(context)
    if area is None:
        wm = context.window_manager
        before = set(w.as_pointer() for w in wm.windows)
        if getattr(context, "window", None) is not None:  # a button's context: no temp_override needed
            bpy.ops.wm.window_new()
        elif not wm.windows:
            return text, ""
        elif thread_safety.ops_override_unsafe():  # the window and layout stay as they are
            return text, SHOW_CODE_LATER
        else:
            with context.temp_override(window=wm.windows[0]):
                bpy.ops.wm.window_new()
        new = next((w for w in wm.windows if w.as_pointer() not in before), None)
        if new is None:
            return text, ""
        area = max(new.screen.areas, key=lambda a: a.width * a.height)
        area.type = "TEXT_EDITOR"
    area.spaces.active.text = text
    area.spaces.active.top = 0
    area.tag_redraw()
    return text, ""
