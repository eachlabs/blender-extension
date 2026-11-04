"""The visual check and the scene review in the bar."""

import json
import threading

import bpy

from eachlabs import chat_run, undo_steps
from eachlabs.ui import tokens
from tests import blender_fakes
from tests.blender_fakes import CAMERA, CHECK, STREET, code_reply, text_reply
from tests.gui_check.bar_input import bar_point, click, key, placed, type_text
from tests.gui_check.bar_models import SlowLLM, addon_prefs
from tests.gui_check.common import check, screenshot, wait_for


def _render_settings(scene):
    render = scene.render
    return (render.engine, render.resolution_x, render.resolution_y, render.resolution_percentage, render.filepath,
            render.use_motion_blur, render.film_transparent, getattr(scene.eevee, "taa_render_samples", None),
            scene.camera, scene.frame_current)


def visual_flow(client):
    """The visual check in a window: the bar says Looking at the frame… before the main thread renders, the scene's
    render settings come back after each frame, and the model sees each frame as a picture."""
    from eachlabs import chat_loop, thread_safety, visual_check

    prefs = addon_prefs()
    calls, seen = [], []
    real = chat_run.visual_check.render

    def watched(build, moves=False):
        calls.append({"main": threading.current_thread() is threading.main_thread(),
                      "chat": any(t.name == "eachlabs-chat" and t.is_alive() for t in threading.enumerate()),
                      "unsafe": thread_safety.ops_override_unsafe(), "before": _render_settings(build.scene)})
        found = real(build, moves)
        calls[-1].update(after=_render_settings(build.scene), frames=found.get("frames"),
                         seconds=found.get("seconds"))
        return found

    script = [code_reply(blender_fakes.LAYOUT_CODE), text_reply("Ground and two buildings."), text_reply("Fine."),
              code_reply(blender_fakes.MATERIALS_CODE), text_reply("Painted."),
              code_reply(blender_fakes.LIGHT_CODE), text_reply("Lit."), text_reply("Fine."),
              code_reply(blender_fakes.CAMERA_CODE), text_reply("A dolly."), text_reply("Fine."),
              text_reply("A street at dusk.")]
    from eachlabs import overlay

    visual_check.render = chat_run.visual_check.render = watched
    prefs.visual_check = True
    concept, prefs.concept_picture = prefs.concept_picture, False  # no picture can be drawn offline
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    before = _render_settings(scene)
    try:
        chat_run.new_scene()
        client.chat_llm = SlowLLM(script)
        client.balances = [5.0, 5.0]
        overlay.FIELD.clear()
        click(*bar_point("field"))
        type_text("a street at dusk")
        key("RET")

        started = yield from wait_for(lambda: chat_run.STATE.running, 10)

        def watch():
            state = placed()[4]
            if tokens.LOOKING in (state.objects or []):
                if not seen:
                    screenshot("bar-15-looking.png")
                seen.append(1)
            return not chat_run.STATE.running
        yield from wait_for(watch, 90)
        yield 0.3
        pictures = [m for ms in client.chat_llm.messages for m in ms if isinstance(m["content"], list)
                    and m["content"][0].get("text", "").startswith(chat_loop.LOOK)]
        check("visual: the bar shows Looking at the frame… before a render", started and bool(seen), str(len(seen)))
        check("visual: four renders, each on the main thread while the chat worker waits",
              len(calls) == 4 and all(c["main"] and c["chat"] for c in calls)
              and all(c["unsafe"] == thread_safety.override_races() for c in calls),
              str([{k: c.get(k) for k in ("main", "chat", "unsafe", "frames", "seconds")} for c in calls]))
        check("visual: every render puts the scene's settings back, and the run leaves them as they were",
              all(c["before"] == c["after"] for c in calls) and _render_settings(scene)[:8] == before[:8],
              "%s %s" % (_render_settings(scene), before))
        check("visual: the model sees each render as a picture with the line, and the run is done",
              len(pictures) == 4 and [sum(p["type"] == "image_url" for p in m["content"]) for m in pictures] == [1, 1, 3, 3]
              and chat_run.STATE.status == "done" and not chat_run.STATE.looking,
              "%d %s %s %s %s calls=%d plan=%s" % (len(pictures), chat_run.STATE.status, chat_run.STATE.error,
                                                  chat_run.STATE.stages, placed()[4].mode, client.chat_llm.calls,
                                                  chat_run.STATE.plan_waiting))
        print("VISUAL seconds %s" % [c.get("seconds") for c in calls], flush=True)
        key("ESC")
        yield 0.3
    finally:
        visual_check.render = chat_run.visual_check.render = real
        prefs.visual_check = False
        prefs.concept_picture = concept


REVIEW_FIX_CODE = '''# Bring Building A up to the street
for obj in scene.objects:
    if obj.name.startswith("Building A"):
        obj.location.x = -7.0
'''


def review_flow(client):
    """The scene review in a window: a finding gets one more fix stage, the second look says it made the scene
    worse, and Blender's undo takes that stage back while the chat worker waits (on 5.x; on 4.2 the person does).
    """
    import re
    from eachlabs import overlay, thread_safety

    prefs = addon_prefs()
    named, undone = [], []

    def review(messages):
        listed = re.search(r"^(Building A(?:\.\d+)?) \|", messages[1]["content"][0]["text"], re.MULTILINE)
        named.append(listed.group(1) if listed else "?")
        return json.dumps({"matches": False, "missing": [], "problems": [
            {"thing": named[-1], "what": "%s stands apart from the street." % named[-1],
             "fix": "Move it one metre toward the street."}]})

    from eachlabs.chat import review_run
    real_undo = review_run.undo_fix

    def watched(run):
        found = real_undo(run)
        undone.append(dict(found, top=undo_steps.active_name()))
        return found

    script = STREET + CAMERA + CHECK + [text_reply("A street at dusk."), code_reply(REVIEW_FIX_CODE),
                                         text_reply("Moved it.")]
    prefs.scene_review = True
    review_run.undo_fix = watched
    try:
        chat_run.new_scene()
        llm = SlowLLM(script)
        llm.review, llm.again = review, '{"solved": [false], "worse": true}'
        client.chat_llm, client.balances = llm, [5.0, 5.0]
        overlay.FIELD.clear()
        click(*bar_point("field"))
        type_text("a street at dusk")
        key("RET")
        started = yield from wait_for(lambda: chat_run.STATE.running, 10)
        yield from wait_for(lambda: not chat_run.STATE.running, 120)
        yield 0.3
        scene = bpy.context.scene
        building = next((o for o in scene.objects if o.name.startswith("Building A")), None)
        check("review: one review call and one second look, and a fix stage between them",
              started and len(llm.reviews) == 2 and chat_run.STATE.stages.get("fix") == "done",
              "%d %s" % (len(llm.reviews), chat_run.STATE.stages))
        if thread_safety.override_races():  # Blender 4.2: never undone during a run; the person uses Undo stage
            check("review: on Blender 4.2 a worse fix stays and Undo stage is offered for it",
                  undone[:1] and undone[0].get("ask") is True and "fix" in chat_run.STATE.changed
                  and "Undo stage takes it back." in chat_run.STATE.reply, "%s %s" % (undone, chat_run.STATE.reply))
        else:
            check("review: worse after the fix undoes the fix stage with Blender's undo",
                  undone[:1] and undone[0].get("undone") is True and building is not None
                  and abs(building.location.x + 8.0) < 1e-6 and "fix" not in chat_run.STATE.changed,
                  "%s %s %s" % (undone, building.location.x if building else None, chat_run.STATE.changed))
            check("review: the done card says the fix was undone",
                  chat_run.STATE.status == "done" and "The fix made the scene worse, so it was undone." in
                  chat_run.STATE.reply and chat_run.STATE.reply.startswith("A street at dusk."), chat_run.STATE.reply)
        key("ESC")
        yield 0.3
    finally:
        prefs.scene_review = False
        review_run.undo_fix = real_undo
