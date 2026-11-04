"""What the bar's field and buttons do: focus, submit, the consent card, and each action button."""

import bpy
import time

from .. import chat_run, compat, preferences
from . import draw, live
from ..chat import selection
from ..ui import bar_state, tokens as T


def focus(context=None):
    """Give the bar the keys: starts the input operator in the window of ``context``."""
    live.overlay.UI["focused"], live.overlay.UI["blink_from"] = True, time.monotonic()
    live.overlay.start_input(context or bpy.context)
    live.overlay._schedule()
    draw.tag_redraw()



def blur():
    live.overlay.UI["focused"] = live.overlay.UI["quality_menu"] = live.overlay.UI["camera_menu"] = False
    draw.tag_redraw()



def _ask_first(context):
    """True when the consent card must open before this send: there is a prompt to run, and the person has
    not agreed yet. Without a key or online access the start's own message shows instead."""
    if preferences.code_allowed(context) or not live.overlay.FIELD.text.strip():
        return False
    return bool(draw._api_key()) and compat.online_problem() is None



def submit(context):
    """Enter or the send button: start a run with the field's text; keep the text when it is refused. Before
    the first run the consent card opens instead, and the prompt waits in the field. An empty field does
    nothing: the placeholder says what to type."""
    if chat_run.STATE.running or not draw.current_state().send_enabled or not live.overlay.FIELD.text.strip():
        return False
    live.overlay.UI["quality_menu"] = False
    if _ask_first(context):
        live.overlay.UI["consent"] = True
        draw.tag_redraw()
        return False
    live.overlay.UI["consent"] = False
    if not live.overlay.UI["mcp_checked"] and draw._api_key() and compat.online_problem() is None:
        live.overlay.UI["mcp_checked"] = True
        try:
            bpy.ops.eachlabs.check_mcp()
        except RuntimeError:
            pass  # The sidebar shows the MCP result; the run does not depend on it.
    started = chat_run.start(context, live.overlay.FIELD.text)
    live.overlay.UI["consent"] = bar_state.consent_after_send(live.overlay.UI["consent"], started)
    if started:
        live.overlay.FIELD.clear()
        live.overlay.FIELD.set_history(chat_run.STATE.history)
    live.overlay._schedule()
    draw.tag_redraw()
    return started



def open_consent(prompt):
    """``chat_run.start`` without the person's consent: open the card with ``prompt`` in the field. False when
    no bar is drawn, so the start reports that a choice is needed instead."""
    if not live.overlay.active() or not live.overlay._placed:
        return False
    if prompt and not live.overlay.FIELD.text.strip():
        live.overlay.FIELD.clear()
        live.overlay.FIELD.paste(prompt)
    live.overlay.UI["consent"] = True
    draw.tag_redraw()
    return True



def restore_prompt(prompt):
    """Cancel on the plan: the prompt goes back into the field, so the person can change it and send again."""
    if prompt and not live.overlay.FIELD.text.strip():
        live.overlay.FIELD.clear()
        live.overlay.FIELD.paste(prompt)
    draw.tag_redraw()



def consent(context, answer):
    """The consent card's buttons: ``check`` and ``plain`` store the consent and start; ``cancel`` stores
    nothing, runs nothing and keeps the prompt."""
    live.overlay.UI["consent"] = False
    if answer in ("check", "plain"):
        preferences.allow_code(context, code_check_on=answer == "check")
        submit(context)
    draw.tag_redraw()



def _stop():
    """Stop the run; while something paid is being made on each::labs, ask first, since that spend stays."""
    if chat_run.paid_running():
        try:
            bpy.ops.eachlabs.chat_cancel("INVOKE_DEFAULT")
        except RuntimeError as exc:
            print("Eachlabs: stop: %s" % exc)
        return
    chat_run.cancel()



def _act(context, name):
    mode = bar_state.picked(name)
    camera = bar_state.camera_picked(name, draw.current_state().camera_menu) if name in T.CAMERA_HITS else None
    if name == "quality":  # the menu opens with the keys, so Esc closes it
        live.overlay.UI["quality_menu"] = not live.overlay.UI["quality_menu"] and not chat_run.STATE.running
        live.overlay.UI["camera_menu"] = False
        if live.overlay.UI["quality_menu"] and not live.overlay.UI["focused"]:
            focus(context)
    elif name == "play_menu":  # the same: the camera menu opens with the keys
        live.overlay.UI["camera_menu"] = not live.overlay.UI["camera_menu"] and not chat_run.STATE.running
        live.overlay.UI["quality_menu"] = False
        if live.overlay.UI["camera_menu"] and not live.overlay.UI["focused"]:
            focus(context)
    elif name in T.CAMERA_HITS:
        live.overlay.UI["camera_menu"] = False
        if camera is not None:
            chat_run.STATE.play_camera = camera
    elif mode is not None:
        live.overlay.UI["quality_menu"] = False
        if not chat_run.STATE.running:
            preferences.set_quality(context, mode)
    elif name == "settings":
        bpy.ops.eachlabs.open_preferences(section="ADDON")
    elif name == T.TAB_CLEAR:  # the chip's cross: nothing selected, so the next prompt adds
        selection.clear(context)
    elif name in T.TAB_HITS:
        if not chat_run.STATE.running:
            chat_run.STATE.target = T.TABS[T.TAB_HITS.index(name)][0]
    elif name == "send":
        submit(context)
    elif name == "missing":
        chat_run.build_missing(context)
    elif name == "widen":
        chat_run.widen(context)
    elif name == "asked":  # a click shows the whole prompt, a second one folds it again
        live.overlay.UI["asked_open"] = not live.overlay.UI["asked_open"]
    elif name.startswith("plan_item_"):
        chat_run.plan_toggle(int(name[len("plan_item_"):]))
    elif name in ("plan_build", "plan_cancel", "plan_limit", "plan_raise"):
        chat_run.plan_answer(name[len("plan_"):])
    elif name.startswith("consent_"):
        consent(context, name[len("consent_"):])
    elif name in ("stop", "halt"):
        _stop()
    elif name == "keep":
        chat_run.dismiss()
    elif name in live.overlay._ACTIONS:
        try:  # invoked, as a button is: an action that removes or undoes something asks first
            getattr(bpy.ops.eachlabs, live.overlay._ACTIONS[name])("INVOKE_DEFAULT", **live.overlay._ACTION_ARGS.get(name, {}))
        except RuntimeError as exc:  # A failed poll or an operator error report.
            print("Eachlabs: %s: %s" % (name, exc))
    live.overlay._schedule()
    draw.tag_redraw()
