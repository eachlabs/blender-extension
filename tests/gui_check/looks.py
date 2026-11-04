"""Looks that wait for Build."""

from eachlabs import chat_run
from tests.blender_fakes import text_reply
from tests.gui_check.bar_input import bar_point, click, key, placed, type_text
from tests.gui_check.bar_models import SlowLLM, addon_prefs
from tests.gui_check.common import check, screenshot, wait_for


def looks_flow(client):
    """With 3D objects Off, a new scene's concept picture and textures still wait for Build: the bar shows a plan
    with only the looks line, and Cancel draws nothing and gives the prompt back."""
    from eachlabs import overlay

    prefs = addon_prefs()
    prefs.concept_picture, prefs.textures_limit = True, 2
    try:
        chat_run.new_scene()
        client.chat_llm = SlowLLM([text_reply("Nothing to change.")])
        client.balances = [5.0, 5.0]
        created = len([e for e in client.log if e[0] == "create"])
        overlay.FIELD.clear()
        click(*bar_point("field"))
        type_text("a kiosk at dusk")
        key("RET")
        shown = yield from wait_for(lambda: chat_run.STATE.plan_waiting and placed()[4].mode == "plan", 10)
        overlay.tag_redraw()
        yield 0.4
        state, hits = placed()[4], set(placed()[1].hits)
        check("looks: with 3D objects Off the bar shows only the looks line with its price, Build and Cancel",
              shown and state.plan_looks.startswith("Looks: a concept picture and up to 2 textures · up to $0.45. This run: about ")
              and not state.plan_3d and {"plan_build", "plan_cancel"} <= hits
              and not any(h.startswith("plan_item_") for h in hits) and client.chat_llm.calls == 0,
              "%s %s" % (state.plan_looks, sorted(hits)))
        screenshot("bar-16-looks.png")
        click(*bar_point("plan_cancel"))
        yield from wait_for(lambda: not chat_run.STATE.running, 10)
        yield 0.3
        check("looks: Cancel draws nothing and puts the prompt back",
              chat_run.STATE.status == "idle" and overlay.FIELD.text == "a kiosk at dusk"
              and len([e for e in client.log if e[0] == "create"]) == created, "%s %r" % (chat_run.STATE.status, overlay.FIELD.text))
        key("ESC")
        yield 0.3
    finally:
        prefs.concept_picture, prefs.textures_limit = False, 0
