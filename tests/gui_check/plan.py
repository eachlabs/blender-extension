"""The plan of 3D objects in the bar."""

from eachlabs import chat_run
from tests.blender_fakes import text_reply
from tests.gui_check.bar_input import bar_point, click, key, placed, type_text
from tests.gui_check.bar_models import SlowLLM, addon_prefs
from tests.gui_check.common import check, screenshot, wait_for


PLAN = ('{"objects_3d": [{"name": "statue", "description": "bronze statue", "tier": "large"}, '
        '{"name": "boulder", "description": "mossy boulder", "tier": "medium"}], '
        '"code": ["road", {"name": "rock", "solid": true}]}')


def plan_flow(client):
    """The plan of 3D objects in the bar: it waits, a chip click moves an item, Cancel gives the prompt back, Build
    starts the stages. The 3D jobs fail at once here (no network), so the chat builds them in code."""
    from eachlabs import generation, overlay

    prefs = addon_prefs()
    real_worker = chat_run.GEN_WORKER
    chat_run.GEN_WORKER = lambda spec, cancel, emit, c: emit({"state": generation.FAILED, "error": "offline check"})
    prefs.objects_3d = "AUTO"
    try:
        client.chat_llm = SlowLLM([text_reply(PLAN)])
        client.balances = [5.0, 5.0]
        click(*bar_point("field"))
        type_text("a park with a statue")
        key("RET")
        shown = yield from wait_for(lambda: chat_run.STATE.plan_waiting and placed()[4].mode == "plan", 10)
        overlay.tag_redraw()
        yield 0.4
        hits = set(placed()[1].hits)
        check("plan: the bar shows a chip per solid piece (none for the road), Build and Cancel, and nothing runs",
              shown and {"plan_item_0", "plan_item_1", "plan_item_3", "plan_build", "plan_cancel"} <= hits
              and "plan_item_2" not in hits and not chat_run._run.jobs
              and placed()[4].plan_3d.startswith("3D: statue, boulder · 2 × $0.45"),
              "%s %s" % (sorted(hits), placed()[4].plan_3d))
        screenshot("bar-13-plan.png")
        click(*bar_point("plan_item_1"))
        yield 0.4
        check("plan: a click on a chip moves the boulder to code", chat_run.STATE.plan.items[1].mode == "code"
              and placed()[4].plan_3d == "3D: statue · 1 × $0.45 = $0.45 · about 3 min one by one",
              placed()[4].plan_3d)
        screenshot("bar-14-plan-moved.png")
        click(*bar_point("plan_cancel"))
        yield from wait_for(lambda: not chat_run.STATE.running, 10)
        yield 0.3
        check("plan: Cancel builds nothing and puts the prompt back in the field",
              chat_run.STATE.status == "idle" and overlay.FIELD.text == "a park with a statue"
              and placed()[4].mode in ("idle", "typing"), "%s %r" % (chat_run.STATE.status, overlay.FIELD.text))
        client.chat_llm = SlowLLM([text_reply(PLAN), text_reply("Nothing to change.")])
        client.balances = [5.0, 5.0]
        click(*bar_point("field"))
        key("RET")
        yield from wait_for(lambda: chat_run.STATE.plan_waiting, 10)
        yield 0.3
        click(*bar_point("plan_build"))
        yield 0.4
        check("plan: Build starts the stages", chat_run.STATE.running and not chat_run.STATE.plan_waiting
              and placed()[4].mode != "plan", placed()[4].mode)
        yield from wait_for(lambda: not chat_run.STATE.running, 40)
        yield 0.3
        check("plan: ... and the run finishes", chat_run.STATE.status == "done", chat_run.STATE.status)
        key("ESC")
        yield 0.3
    finally:
        chat_run.GEN_WORKER = real_worker
        prefs.objects_3d = "OFF"
