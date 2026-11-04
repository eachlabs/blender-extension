"""The prompt bar scenario, driven with simulated clicks and keys."""

import os
import threading
import time

import bpy
from mathutils import Vector

import eachlabs
from eachlabs import compat, mcp_client, scene_build, undo_steps
from eachlabs.ui import tokens
from tests.blender_fakes import CAMERA, CHECK, KIOSK_CODE, STREET, code_reply, offline_api, text_reply
from tests.gui_check.args import OUT, SKIA_ERROR
from tests.gui_check.bar_input import (answer_dialog, bar_point, click, close, framed_on, grabbing, key, kinds,
                                       modal_names, move, orange_pixels, placed, reveal_cube, screen_point, shot_pixel,
                                       type_text, view3d_region, viewport_centre)
from tests.gui_check.bar_models import FailFirstLLM, REFUSE, REVIEWS, SlowLLM, addon_prefs, code_windows
from tests.gui_check.common import area_of, check, optional, override, parked, screenshot, wait_for, window

looks_flow = optional("looks", "looks_flow")
plan_flow = optional("plan", "plan_flow")
play_through = optional("play", "play_through")
quality_picker = optional("quality", "quality_picker")
review_flow = optional("review", "review_flow")
visual_flow = optional("review", "visual_flow")
tool_presses = optional("tools", "tool_presses")
tooltip_checks = optional("tooltips", "tooltip_checks")


def scenario_bar():
    from eachlabs import overlay, viewport_marks
    from eachlabs.ui import bar_state

    check("bar: Skia imports in this Blender", SKIA_ERROR is None, SKIA_ERROR or "")
    addon_prefs().objects_3d = "OFF"  # the plan of 3D objects has its own flow (plan_flow)
    addon_prefs().visual_check = False  # the visual check has its own flow (visual_flow)
    addon_prefs().scene_review = False  # the scene review has its own flow (review_flow)
    addon_prefs().concept_picture = False  # the looks ask for Build on their own plan (looks_flow)
    addon_prefs().detail_rounds = 0  # the detail stage has its own checks (tests/smoke.py)
    addon_prefs().reference_pictures = False
    addon_prefs().textures_limit = 0
    region, prefs = view3d_region(), bpy.context.preferences
    header = next(r for r in area_of("VIEW_3D").regions if r.type == "HEADER")
    print("SCALE ui_scale=%.2f pixel_size=%.2f header=%d region=%dx%d" % (
        prefs.system.ui_scale, prefs.system.pixel_size, header.height, region.width, region.height), flush=True)
    move(*viewport_centre())
    yield 1.0
    check("bar: no modal operator runs while the bar is idle (autosave stays on)",
          not overlay._running_in(window()) and not modal_names(), str(modal_names()))
    check("bar: drawn in the 3D view", placed() is not None)
    origin, frame, width, scale = placed()[:4]
    bx, by, bw, bh = frame.bar_rect
    left, right = overlay.insets(area_of("VIEW_3D"), region)  # the toolbar overlaps the view's left side
    visible = region.width - left - right
    check("bar: centred in the free width, 36 px above the bottom, min(640, free width - 32) wide",
          abs(origin[0] + bx + bw / 2 - (left + visible / 2)) <= 1
          and origin[1] + frame.height - by - bh == round(36 * scale)
          and width == min(640, int(visible / scale) - 32), "%s %s %s %s %d %d" % (origin, frame.bar_rect, width,
                                                                                 scale, left, right))
    shot = os.path.join(OUT, "bar-01-idle.png")
    screenshot("bar-01-idle.png")
    sx, sy = bar_point("send", 0.85, 0.5)
    fx, fy = bar_point("bar", 0.004, 0.5)
    send_rgb, fill_rgb = shot_pixel(shot, sx, sy), shot_pixel(shot, fx + 6, fy)
    check("bar: send button is the brand orange", close(send_rgb, (0xFF, 0x3C, 0x15)), str(send_rgb))
    check("bar: bar fill is near black", max(fill_rgb) < 32, str(fill_rgb))
    yield from quality_picker()
    addon_prefs().chat_quality = "ADVANCED"  # the scripted flows below count Final's rounds and prices
    from eachlabs import chat_run

    check("settings: the bar shows the settings button next to send", "settings" in placed()[1].hits,
          str(sorted(placed()[1].hits)))
    check("tabs: Scene, Assets and Characters show above the input, Scene chosen",
          all(h in placed()[1].hits for h in tokens.TAB_HITS) and chat_run.STATE.target == "scene",
          str(sorted(placed()[1].hits)))
    click(*bar_point("tab_asset"))
    yield 0.4
    check("tabs: a click on Assets chooses it and the placeholder follows",
          chat_run.STATE.target == "asset" and placed()[4].tab == "asset", chat_run.STATE.target)
    screenshot("bar-06-tab-assets.png")
    barrel = bpy.data.objects.new("Barrel", bpy.data.meshes.new("Barrel"))
    bpy.context.scene.collection.objects.link(barrel)
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    barrel.select_set(True)
    overlay.tag_redraw()
    yield 0.4
    check("tabs: a selected object on Assets shows the changing line and its chip",
          placed()[4].thing == "Barrel" and tokens.TAB_CLEAR in placed()[1].hits,
          "%r %s" % (placed()[4].thing, sorted(placed()[1].hits)))
    screenshot("bar-06c-tab-changing.png")
    click(*bar_point(tokens.TAB_CLEAR))
    yield 0.4
    check("tabs: the chip's cross clears the selection and the line goes back to adding",
          not barrel.select_get() and placed()[4].thing == "" and tokens.TAB_CLEAR not in placed()[1].hits,
          "%s %r" % (barrel.select_get(), placed()[4].thing))
    bpy.data.objects.remove(barrel)
    yield from tooltip_checks()
    click(*bar_point("tab_scene"))
    yield 0.4
    check("tabs: a click on Scene chooses it again", chat_run.STATE.target == "scene", chat_run.STATE.target)
    key("ESC")
    yield 0.3

    cube = bpy.data.objects["Cube"]
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    yield 0.3
    click(*screen_point(cube.location))
    yield 0.4
    check("bar: off the bar, Blender's click-select still selects the cube",
          cube.select_get() and not overlay._running_in(window()), str(modal_names()))
    click(*bar_point("field"))
    yield 0.4
    check("bar: a click on the field focuses it and starts the input operator",
          overlay.UI["focused"] and overlay._running_in(window()), str(modal_names()))
    screenshot("bar-02-focused.png")
    type_text("a street")
    key("RET", shift=True)
    type_text("at dusk")
    yield 0.5
    check("bar: typing and Shift+Enter", overlay.FIELD.text == "a street\nat dusk", repr(overlay.FIELD.text))
    screenshot("bar-03-multiline.png")
    click(*bar_point("field", 0.0, 0.25))
    yield 0.3
    check("bar: a click in the text moves the caret", overlay.FIELD.caret == 0, str(overlay.FIELD.caret))
    x0, y0 = bar_point("field", 0.0, 0.25)
    x1, _ = bar_point("field", 1.0, 0.25)
    move(x0, y0)
    yield 0.6  # longer than the double-click time, so this press is not a double click on the last one
    window().event_simulate("LEFTMOUSE", "PRESS", x=x0, y=y0)
    yield 0.2
    for step in range(1, 5):
        move(x0 + (x1 - x0) * step // 4, y0)
        yield 0.05
    window().event_simulate("LEFTMOUSE", "RELEASE", x=x1, y=y0)
    yield 0.3
    check("bar: a mouse drag over the first line selects it", overlay.FIELD.copy() == "a street",
          repr(overlay.FIELD.copy()))
    screenshot("bar-03b-drag-selection.png")
    x2, y2 = bar_point("field", 0.0, 0.75)
    move(x2, y2)
    for _ in range(2):  # two quick presses: Blender makes the second one a double click
        window().event_simulate("LEFTMOUSE", "PRESS", x=x2, y=y2)
        window().event_simulate("LEFTMOUSE", "RELEASE", x=x2, y=y2)
    yield 0.3
    check("bar: a double click selects the word", overlay.FIELD.copy() == "at", repr(overlay.FIELD.copy()))
    key("END")
    yield 0.1

    cube = bpy.data.objects["Cube"]
    start = tuple(cube.location)
    move(*viewport_centre())
    key("G", "g")
    yield 0.4
    check("bar: while focused G types and does not grab", not grabbing() and "g" in overlay.FIELD.text,
          "%s %r" % (modal_names(), overlay.FIELD.text[-3:]))
    key("ESC")
    yield 0.3
    check("bar: Esc gives the keys back and ends the input operator",
          not overlay.UI["focused"] and not overlay._running_in(window()), str(modal_names()))
    key("G", "g")
    yield 0.4
    check("bar: after Esc G grabs", grabbing(), str(modal_names()))
    key("ESC")
    yield 0.4
    check("bar: the grab was cancelled, the cube did not move", not grabbing() and tuple(cube.location) == start)
    key("SPACE", " ", ctrl=True, shift=True)
    yield 0.4
    check("bar: Ctrl+Shift+Space stays Blender's reverse playback", window().screen.is_animation_playing
          and not overlay.UI["focused"])
    with override():
        bpy.ops.screen.animation_cancel(restore_frame=True)
    yield 0.3
    key("SPACE", " ", shift=True, alt=True)
    yield 0.4
    check("bar: Shift+Alt+Space focuses the bar", overlay.UI["focused"])
    click(*viewport_centre())
    yield 0.3
    move(*viewport_centre())  # the input operator ends on the event after the click
    yield 0.3
    check("bar: a click outside the bar unfocuses it", not overlay.UI["focused"]
          and not overlay._running_in(window()), str(modal_names()))
    yield from tool_presses()

    real_check, mcp_calls = mcp_client.check, []
    mcp_client.check = lambda base_url, api_key: mcp_calls.append(1) or (True, "MCP connected")
    try:
        with offline_api() as client:
            client.chat_llm = SlowLLM(STREET + CAMERA + CHECK + [text_reply("A street at sunset with a slow camera move.")])
            client.balances = [10.0, 9.996]
            overlay.FIELD.clear()
            screenshot("live-00-before.png")
            base_orange = orange_pixels(os.path.join(OUT, "live-00-before.png"))
            click(*bar_point("field"))
            type_text("a street at sunset")
            prefs = addon_prefs()
            key("RET")
            yield 0.4
            check("consent: the first Enter opens the consent card and runs nothing",
                  placed()[4].mode == "consent" and not chat_run.STATE.running and client.chat_llm.calls == 0
                  and overlay.FIELD.text == "a street at sunset" and prefs.chat_code_consent == "UNSET",
                  "%s %s" % (placed()[4].mode, prefs.chat_code_consent))
            screenshot("bar-10-consent.png")
            click(*bar_point("consent_cancel"))
            yield 0.4
            check("consent: Cancel stores nothing, runs nothing and keeps the prompt",
                  placed()[4].mode != "consent" and not chat_run.STATE.running and client.chat_llm.calls == 0
                  and overlay.FIELD.text == "a street at sunset" and prefs.chat_code_consent == "UNSET"
                  and not prefs.chat_code_check, "%s %r" % (placed()[4].mode, overlay.FIELD.text))
            key("RET")
            yield 0.4
            check("consent: the card shows again on the next Enter", placed()[4].mode == "consent",
                  placed()[4].mode)
            key("ESC")
            yield 0.4
            check("consent: Esc closes the card like Cancel and the bar keeps the keys",
                  placed()[4].mode != "consent" and overlay.UI["focused"] and not chat_run.STATE.running
                  and overlay.FIELD.text == "a street at sunset", placed()[4].mode)
            key("RET")
            yield 0.4
            click(*bar_point("consent_check"))
            yield 0.3
            check("consent: Build with code check stores the consent, turns Code check on and starts the run",
                  prefs.chat_code_consent == "ALLOWED" and prefs.chat_code_check and chat_run.STATE.running
                  and chat_run.STATE.code_check_on and not overlay.FIELD.text,
                  "%s %s %s" % (prefs.chat_code_consent, prefs.chat_code_check, chat_run.STATE.error))
            run, calls = chat_run._run, client.chat_llm.calls
            seen = yield from wait_for(lambda: viewport_marks.has_flashes(), 20)
            check("picker: the quality pill is dimmed and takes no click while a run is going",
                  chat_run.STATE.running and placed()[4].quality_enabled is False and "quality" not in placed()[1].hits,
                  str(sorted(placed()[1].hits)))
            screenshot("live-01-flash.png")
            flash_orange = orange_pixels(os.path.join(OUT, "live-01-flash.png"))
            check("live: objects the chat just created are flashed", seen and viewport_marks.has_flashes())
            check("live: orange outlines are visible right after the objects appear",
                  flash_orange > base_orange + 150, "%d -> %d orange pixels" % (base_orange, flash_orange))
            type_text("night")
            key("RET")
            yield 0.3
            check("bar: Enter during a run sends nothing and keeps the text", overlay.FIELD.text == "night"
                  and chat_run._run is run and chat_run.STATE.prompt == "a street at sunset"
                  and client.chat_llm.calls <= calls + 1, "%r %d -> %d" % (overlay.FIELD.text, calls,
                                                                         client.chat_llm.calls))
            overlay.FIELD.clear()
            yield 0.9
            screenshot("bar-04-running.png")
            check("bar: running shows the stop button", "stop" in placed()[1].hits, str(sorted(placed()[1].hits)))
            check("code check: the bar shows the CODE CHECK badge and the steps are reviewed",
                  placed()[4].code_check and REVIEWS, "%s %d" % (placed()[4].code_check, len(REVIEWS)))
            shading = area_of("VIEW_3D").spaces.active.shading
            scene = bpy.context.scene
            check("live: the view starts in Solid shading", shading.type == "SOLID", shading.type)
            check("live: with Workbench, which has no Material Preview, Solid stays",
                  scene.render.engine == "BLENDER_WORKBENCH" and chat_run.material_preview(window().as_pointer()) == 0
                  and shading.type == "SOLID", scene.render.engine)
            for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):  # 5.x, 4.2
                try:
                    scene.render.engine = engine
                    break
                except TypeError:
                    pass
            done = yield from wait_for(lambda: chat_run.STATE.stages.get("layout") == "done", 20)
            yield 0.3
            screenshot("live-01b-after-layout.png")
            # The light stage may have added lamps by now; the view was framed on the layout's buildings.
            ok, detail = framed_on([o for o in chat_run._build.frame_targets() if o.name.startswith("Building")])
            check("live: the view frames the street once the layout stage ends", done and ok, detail)
            lit = yield from wait_for(lambda: chat_run.STATE.stages.get("light") == "done", 20)
            yield 0.2
            check("live: Solid switches to Material Preview when the light stage ends",
                  lit and shading.type == "MATERIAL", shading.type)
            yield from wait_for(lambda: not chat_run.STATE.running, 40)
            yield 1.0
            shading.type = "RENDERED"
            switched = chat_run.material_preview(window().as_pointer())
            check("live: Rendered shading is never switched", switched == 0 and shading.type == "RENDERED",
                  shading.type)
            shading.type = "MATERIAL"
            scene.render.engine = "BLENDER_WORKBENCH"
            shading.type = "SOLID"
            check("bar: the run builds the street", chat_run.STATE.status == "done"
                  and {"box", "lamp", "camera"} <= kinds(), "%s %s" % (chat_run.STATE.status, kinds()))
            check("bar: one MCP check before the first send", len(mcp_calls) == 1, str(len(mcp_calls)))
            check("bar: without Show advanced tools, done hides New scene, Final render and Show code",
                  {"play", "frame", "undo"} <= set(placed()[1].hits)
                  and not {"new", "final", "code"} & set(placed()[1].hits), str(sorted(placed()[1].hits)))
            addon_prefs().show_advanced_tools = True  # the rest of the scenario uses them
            yield 0.4
            check("bar: done shows Play, Frame result, Undo stage: Camera (check changed nothing) and New scene",
                  {"play", "frame", "undo", "new"} <= set(placed()[1].hits) and placed()[4].undo_stage == "camera",
                  "%s %r" % (sorted(placed()[1].hits), placed()[4].undo_stage))
            check("bar: the active undo step reads as the camera stage", undo_steps.active_name() == "Eachlabs: camera",
                  str(undo_steps.active_name()))
            startup = bpy.data.objects.get("Cube")
            check("bar: the person's camera aims at the startup Cube, so the new scene keeps it, and says nothing",
                  startup is not None and not startup.hide_get() and not placed()[4].note
                  and "cube" not in placed()[1].hits, repr(placed()[4].note))
            screenshot("bar-05-done.png")
            reveal_cube()  # the script's, outside the undo stack: the checks below use the Cube as the person's
            windows = len(bpy.context.window_manager.windows)
            click(*bar_point("code"))
            yield 1.0
            text = bpy.data.texts.get("Eachlabs code")
            shown = code_windows()
            check("bar: Show code writes the steps to the Eachlabs code text and opens it in a new window",
                  text is not None and "# ---- Step 1 \u00b7 Layout \u00b7 ran ----" in text.as_string()
                  and "fake-key" not in text.as_string() and shown
                  and len(bpy.context.window_manager.windows) == windows + 1,
                  "%s %d windows" % (text and text.as_string()[:120], len(bpy.context.window_manager.windows)))
            if shown:  # a screenshot of the second window comes out blank, so the check reads the editor
                with parked(), bpy.context.temp_override(window=shown[0]):
                    bpy.ops.wm.window_close()
                yield 0.6
            move(*viewport_centre())
            yield 0.3
            yield 1.5  # the last flashes are over
            check("live: flashes are gone after 1.2 s", not viewport_marks.active_flashes(time.monotonic()))
            screenshot("live-02-path.png")
            path_orange = orange_pixels(os.path.join(OUT, "live-02-path.png"))
            check("live: the camera path is kept and drawn once the camera stage is done",
                  len(viewport_marks.camera_path()) == 2 and path_orange > base_orange + 40,
                  "%d -> %d orange pixels" % (base_orange, path_orange))
            check("live: draw handler is registered", viewport_marks.active())
            odd = [o.name for o in bpy.context.scene.objects
                   if o.get("eachlabs_id") and o.type in ("CAMERA", "LIGHT", "EMPTY")]
            errors = viewport_marks._state["errors"]
            viewport_marks.flash(odd + ["no-such-object"] + [o.name for o in bpy.context.scene.objects
                                                             if o.name.startswith("Building")][:1], time.monotonic())
            yield 0.2
            screenshot("live-02b-odd.png")
            check("live: flashing cameras, lamps, empties and a missing name draws without errors, boxes still draw",
                  viewport_marks._state["errors"] == errors
                  and orange_pixels(os.path.join(OUT, "live-02b-odd.png")) > path_orange + 40,
                  "%d errors" % (viewport_marks._state["errors"] - errors))
            yield 1.4

            key("UP_ARROW")
            yield 0.4
            check("bar: up recalls the last prompt", overlay.FIELD.text == "a street at sunset", repr(overlay.FIELD.text))
            key("ESC")
            overlay.FIELD.clear()

            area = area_of("VIEW_3D")
            area.spaces.active.region_3d.view_location = (40, 40, 0)  # look away first
            selected = sorted(o.name for o in bpy.context.scene.objects if o.select_get())
            active = bpy.context.view_layer.objects.active
            click(*bar_point("frame"))
            yield 0.5
            ok, detail = framed_on(chat_run._build.frame_targets())
            check("bar: Frame result frames what was built and keeps the selection and active object",
                  ok and sorted(o.name for o in bpy.context.scene.objects if o.select_get()) == selected
                  and bpy.context.view_layer.objects.active == active, detail)
            overlay.tag_redraw()
            yield 0.5
            screenshot("live-03-still.png")
            still_orange = orange_pixels(os.path.join(OUT, "live-03-still.png"))
            yield from play_through(still_orange)

            scene = chat_run._build.scene
            engine, percentage = scene.render.engine, scene.render.resolution_percentage
            scene.render.resolution_percentage = 10  # a small picture: the check is the flow, not the look
            click(*bar_point("final"))
            rendering = False  # watched often: a small render can finish within half a second
            for _ in range(40):
                yield 0.05
                if chat_run.STATE.final_render == "rendering" and "final" not in placed()[1].hits:
                    rendering = True
                    break
                if chat_run.STATE.final_render in ("saved", "failed", "cancelled"):
                    break
            yield from wait_for(lambda: chat_run.STATE.final_render in ("saved", "failed", "cancelled"), 120)
            overlay.tag_redraw()
            yield 0.5
            screenshot("live-04b-final-render.png")
            check("bar: Final render renders with Cycles in its own window, saves the picture, puts the settings "
                  "back and offers it again", rendering and chat_run.STATE.final_render == "saved"
                  and os.path.isfile(chat_run.STATE.final_path) and scene.render.engine == engine
                  and "final" in placed()[1].hits and "Final render saved" in placed()[4].reply,
                  "%s %r %s %s" % (chat_run.STATE.final_render, chat_run.STATE.final_path, scene.render.engine,
                                   chat_run.STATE.final_error))
            scene.render.resolution_percentage = percentage
            for win in list(bpy.context.window_manager.windows)[1:]:  # the render window
                with bpy.context.temp_override(window=win):
                    bpy.ops.wm.window_close()
            yield 0.5

            check("bar: the Undo pill is still offered after Frame result and Play",
                  "undo" in placed()[1].hits and placed()[4].undo_stage == "camera", str(sorted(placed()[1].hits)))
            opened = yield from answer_dialog(bar_point("undo"), "Undo the camera stage?", False,
                                              "bar-05a-undo-confirm.png")
            check("bar: Undo stage asks first, and Cancel undoes nothing",
                  opened and "camera" in kinds() and placed()[4].undo_stage == "camera",
                  "%s %s %r" % (opened, kinds(), placed()[4].undo_stage))
            opened = yield from answer_dialog(bar_point("undo"), "Undo the camera stage?", True)
            check("bar: Undo stage removes the camera stage's objects and offers the light stage next",
                  "camera" not in kinds() and {"box", "lamp"} <= kinds() and placed()[4].undo_stage == "light",
                  "%s %r %s" % (kinds(), placed()[4].undo_stage, undo_steps._printed()))
            screenshot("bar-05b-undo-pill.png")

            reveal_cube()  # undoing the camera stage brought back the layout stage's hidden Cube
            cube = bpy.data.objects["Cube"]  # undo replaced the datablocks
            start = tuple(cube.location)
            x, y = viewport_centre()
            move(x, y)
            key("G", "g")
            yield 0.3
            move(x + 60, y)
            yield 0.2
            click(x + 60, y)
            yield 0.8
            check("bar: an edit by the person after the run hides the Undo pill",
                  tuple(cube.location) != start and "undo" not in placed()[1].hits,
                  "%s %s" % (tuple(cube.location), sorted(placed()[1].hits)))

            move(*viewport_centre())
            gone = {}
            for press in range(1, 7):
                key("Z", ctrl=True)
                yield 0.6
                for kind in ("lamp", "box"):
                    if kind not in kinds() and kind not in gone:
                        gone[kind] = press
            check("bar: Ctrl+Z then undoes the person's move, the lamps, then the buildings",
                  1 < gone.get("lamp", 99) < gone.get("box", 99) < 99, str(gone))
            startup = bpy.data.objects.get("Cube")  # undo replaced the datablocks
            check("bar: the person's Cube is still there after the undos", startup is not None and not startup.hide_get(),
                  str(startup))
            screenshot("bar-06-undone.png")

            client.chat_llm = SlowLLM(STREET + CAMERA + CHECK + [text_reply("Done.")])
            client.balances = []
            click(*bar_point("field"))
            type_text("a street")
            key("RET")
            yield 0.5
            yield from wait_for(lambda: not chat_run.STATE.running, 40)
            yield 0.8
            check("bar: a second full run offers Undo stage", "undo" in placed()[1].hits, str(sorted(placed()[1].hits)))
            reveal_cube()  # a new scene again, so the Cube was hidden again
            cube = bpy.data.objects["Cube"]
            for obj in bpy.context.scene.objects:
                obj.select_set(False)
            yield 0.6  # the deselect above is the script's, outside the undo stack
            overlay.tag_redraw()
            yield 0.3
            check("bar: ... while its camera stage is the active undo step", "undo" in placed()[1].hits
                  and undo_steps.active_name() == "Eachlabs: camera", str(undo_steps.active_name()))
            # A point on the cube's top face that the bar does not cover: the done card, with the prompt line,
            # reaches over the cube in this view, so the view looks a little lower until one is clear.
            area, region = area_of("VIEW_3D"), view3d_region()
            rv3d = area.spaces.active.region_3d
            moved = 0.0
            point = screen_point(cube.matrix_world @ Vector((0, 0, 1)))
            while overlay._target_at(area, region, *point) is not None and moved < 6.0:
                rv3d.view_location.z -= 0.5
                moved += 0.5
                overlay.tag_redraw()
                yield 0.2
                point = screen_point(cube.matrix_world @ Vector((0, 0, 1)))
            check("bar: the bar still has focus after Enter", overlay.UI["focused"])
            click(*point)  # also gives the keys back
            yield 0.8
            overlay.tag_redraw()
            yield 0.3
            selected = [o.name for o in bpy.context.scene.objects if o.select_get()]
            check("bar: a selection click after the run hides the Undo pill",
                  selected and undo_steps.active_name() == "Select" and "undo" not in placed()[1].hits,
                  "%s %s %s %s" % (point, selected, undo_steps.active_name(), sorted(placed()[1].hits)))
            rv3d.view_location.z += moved
            chat_run.STATE.changed = ["layout", "materials", "light", "camera"]  # as if tracking had missed the click
            chat_run._undo.update(top="Eachlabs: camera", read_at=time.monotonic(), dirty=False)
            reports, before = [], kinds()
            fake = type("Op", (), {"report": lambda self, kind, text: reports.append(text)})()
            result = chat_run.EACHLABS_OT_chat_undo_stage.execute(fake, bpy.context)
            check("bar: Undo stage reads the undo stack again and refuses when the top step is not the chat's",
                  result == {"CANCELLED"} and kinds() == before and reports and undo_steps.active_name() == "Select",
                  str(reports))
            overlay.tag_redraw()
            yield 0.4

            client.chat_llm = SlowLLM(STREET + CAMERA + CHECK + [text_reply("Done.")])
            old_scene = window().scene
            built = [c.name for c in old_scene.collection.children if c.get(scene_build.RUN)]
            status = chat_run.STATE.status
            opened = yield from answer_dialog(bar_point("new"), "Start a new scene?", False,
                                              "bar-06a-new-scene-confirm.png")
            check("bar: New scene asks first, and Cancel keeps the scene and the bar",
                  opened and window().scene == old_scene and chat_run.STATE.status == status
                  and placed()[4].has_scene, "%s %s %s" % (opened, window().scene.name, chat_run.STATE.status))
            opened = yield from answer_dialog(bar_point("new"), "Start a new scene?", True)
            check("bar: New scene clears the bar and the placeholder asks for a new scene",
                  chat_run.STATE.status == "idle" and not placed()[4].has_scene, chat_run.STATE.status)
            check("bar: New scene opens a new, empty Blender scene and keeps the old one as it was",
                  built and window().scene != old_scene and not window().scene.objects
                  and [c.name for c in old_scene.collection.children if c.get(scene_build.RUN)] == built,
                  "%s %s" % (window().scene.name, built))
            click(*bar_point("field"))
            type_text("a street")
            key("RET")
            yield 0.8
            click(*viewport_centre())
            yield 0.3
            key("ESC")
            yield 0.4
            check("bar: Esc with the bar unfocused is not taken and the run goes on",
                  chat_run.STATE.running and not overlay._running_in(window()), chat_run.STATE.status)
            click(*bar_point("field"))
            yield 0.3
            key("ESC")
            yield 0.4
            check("bar: Esc in the focused bar stops the run and gives the keys back",
                  chat_run.STATE.status == "cancelled" and not chat_run.STATE.running
                  and not overlay.UI["focused"], chat_run.STATE.status)
            screenshot("bar-06b-esc-stopped.png")
            yield from wait_for(lambda: not (chat_run.worker() and chat_run.worker().is_alive()), 10)
            overlay.tag_redraw()
            yield 0.3
            check("bar: stopped by you offers New scene and Keep the scene",
                  {"new", "keep"} <= set(placed()[1].hits), str(sorted(placed()[1].hits)))
            click(*bar_point("keep"))
            yield 0.4
            check("bar: Keep the scene dismisses the stop and keeps what was built",
                  chat_run.STATE.status == "idle" and placed()[4].mode in ("idle", "typing")
                  and kinds(), "%s %s" % (chat_run.STATE.status, placed()[4].mode))

            def field_send(text):
                click(*bar_point("field"))
                overlay.FIELD.clear()
                type_text(text)
                key("RET")

            prefs.chat_code_check, prefs.chat_code_consent = False, "UNSET"
            real_online = compat.online_problem
            client.chat_llm = SlowLLM([code_reply(KIOSK_CODE), text_reply("A kiosk.")])
            compat.online_problem = lambda: tokens.ONLINE_OFF
            field_send("a kiosk")
            yield 0.5
            hits = sorted(placed()[1].hits)
            check("bar: a refused start (online access off) offers Open preferences, not Retry",
                  placed()[4].mode == "error" and "network" in hits and "retry" not in hits
                  and overlay._ACTION_ARGS["network"] == {"section": "SYSTEM"}, "%s %s" % (placed()[4].mode, hits))
            compat.online_problem = real_online
            click(*bar_point("field"))
            key("RET")
            yield 0.5
            check("consent: Enter once online access is on, consent unset, opens the card and keeps the prompt",
                  placed()[4].mode == "consent" and not chat_run.STATE.running
                  and prefs.chat_code_consent == "UNSET" and overlay.FIELD.text == "a kiosk",
                  "%s %r" % (placed()[4].mode, overlay.FIELD.text))
            click(*bar_point("consent_plain"))
            yield 0.4
            check("consent: Build without check stores the consent, leaves Code check off and starts the run",
                  prefs.chat_code_consent == "ALLOWED" and not prefs.chat_code_check and chat_run.STATE.running
                  and not chat_run.STATE.code_check_on and chat_run.STATE.prompt == "a kiosk",
                  "%s %s %s" % (prefs.chat_code_consent, chat_run.STATE.status, chat_run.STATE.error))
            yield from wait_for(lambda: not chat_run.STATE.running, 20)
            yield 0.3

            client.chat_llm = SlowLLM([text_reply("Nothing to change.")])
            real_start = threading.Thread.start

            def no_chat_thread(thread):
                if thread.name == "eachlabs-chat":
                    raise RuntimeError("can't start new thread")
                return real_start(thread)

            threading.Thread.start = no_chat_thread
            try:
                field_send("a bench")
                yield 0.5
            finally:
                threading.Thread.start = real_start
            check("bar: a chat that could not start shows the error with Retry, and nothing runs",
                  placed()[4].mode == "error" and placed()[4].error == tokens.START_FAILED
                  and "retry" in placed()[1].hits and not chat_run.STATE.running,
                  "%s %r" % (placed()[4].mode, placed()[4].error))
            click(*bar_point("retry"))
            yield 0.4
            check("bar: Retry after a refused start sends the same prompt again",
                  chat_run.STATE.running and chat_run.STATE.prompt == "a bench", chat_run.STATE.error)
            yield from wait_for(lambda: not chat_run.STATE.running, 20)
            yield 0.3

            prefs.chat_code_check = True
            REFUSE[:] = [1]
            client.chat_llm = SlowLLM(STREET + [text_reply("Done.")])
            field_send("a street")
            refused = yield from wait_for(lambda: placed()[4].actions == ["code", "halt"], 20)
            screenshot("bar-13-refused.png")
            check("bar: a refused step shows the Code check line with Show code and Stop",
                  refused and {"code", "halt"} <= set(placed()[1].hits), str(placed()[4].actions))
            windows = len(bpy.context.window_manager.windows)
            click(*bar_point("code"))
            yield 0.6
            shown = code_windows()
            check("bar: Show code while the run goes opens the code in a new window from the bar's own window",
                  chat_run.STATE.running and shown and len(bpy.context.window_manager.windows) == windows + 1,
                  "%s %d windows" % (chat_run.STATE.status, len(bpy.context.window_manager.windows)))
            if shown:
                with parked(), bpy.context.temp_override(window=shown[0]):
                    bpy.ops.wm.window_close()
                yield 0.6
            move(*viewport_centre())
            yield 0.2
            click(*bar_point("halt"))
            yield 0.4
            check("bar: the Stop pill stops the run", chat_run.STATE.status == "cancelled"
                  and not chat_run.STATE.running, chat_run.STATE.status)
            yield from wait_for(lambda: not (chat_run.worker() and chat_run.worker().is_alive()), 10)
            overlay.tag_redraw()
            yield 0.3
            click(*bar_point("keep"))
            yield 0.3

            prefs.chat_code_check = False  # what the sidebar's Code check switch writes
            client.chat_llm = FailFirstLLM(STREET + CAMERA + CHECK + [text_reply("Done.")])
            click(*bar_point("field"))
            type_text("a lamp")
            key("RET")
            yield 0.4
            check("code check: switched off in the preferences, the next run is not checked",
                  chat_run.STATE.prompt == "a lamp" and not chat_run.STATE.code_check_on, chat_run.STATE.status)
            yield from wait_for(lambda: not chat_run.STATE.running, 10)
            overlay.tag_redraw()
            yield 0.4
            screenshot("bar-12-failed.png")
            check("bar: a failed stage offers Retry and New scene",
                  chat_run.STATE.status == "stopped" and {"retry", "new"} <= set(placed()[1].hits),
                  "%s %s" % (chat_run.STATE.status, sorted(placed()[1].hits)))
            click(*bar_point("retry"))
            yield 0.4
            check("bar: Retry starts a run from the failed stage", chat_run.STATE.running
                  and chat_run.STATE.prompt == "a lamp", chat_run.STATE.error)
            yield from wait_for(lambda: not chat_run.STATE.running, 40)
            yield 0.4
            check("bar: ... and it finishes", chat_run.STATE.status == "done", chat_run.STATE.status)
            key("ESC")
            yield 0.3
            yield from plan_flow(client)
            yield from visual_flow(client)
            yield from review_flow(client)
            yield from looks_flow(client)
    finally:
        mcp_client.check = real_check

    cube = bpy.data.objects["Cube"]  # undo replaced the datablocks; select it again for the grab
    window().scene = cube.users_scene[0]  # New scene above moved the window to a new, empty scene
    yield 0.3
    cube.select_set(True)
    key("ESC")  # the Esc test above may leave a click-select box or menu
    bpy.context.view_layer.objects.active = cube
    overlay.UI["fail_draw"] = True
    overlay.tag_redraw()
    yield 0.6
    screenshot("bar-07-draw-error.png")
    check("bar: a failing draw is caught", overlay.UI["draw_errors"] > 0)
    key("G", "g")
    yield 0.4
    check("bar: the viewport still takes keys after a draw error", grabbing(), str(modal_names()))
    key("ESC")
    overlay.UI["fail_draw"] = False
    yield 0.4

    overlay.blur()
    area = area_of("VIEW_3D")
    area.spaces.active.show_region_ui = True
    yield 0.6
    ui = next(r for r in area.regions if r.type == "UI")
    win = view3d_region()
    left, right = overlay.insets(area, win)
    origin, frame, _, scale = placed()[:4]
    bx, _, bw, _ = frame.bar_rect
    check("bar: centred in the width the sidebar and toolbar leave", right >= ui.width - 2
          and abs(origin[0] + bx + bw / 2 - (left + (win.width - left - right) / 2)) <= 1,
          "left %d right %d sidebar %d" % (left, right, ui.width))
    screenshot("bar-08-sidebar.png")
    real_min = bar_state.MIN_WIDTH
    bar_state.MIN_WIDTH = int(win.width / scale) + 200  # wider than the view: the bar runs under the sidebar
    overlay.tag_redraw()
    yield 0.6
    y = bar_point("bar")[1]
    # Blender's own handling of a simulated press is not observable here, so the check reads what the
    # bar decided: a press it takes sets UI["pressed"] until the release.
    move(ui.x + ui.width // 2, y)
    window().event_simulate("LEFTMOUSE", "PRESS", x=ui.x + ui.width // 2, y=y)
    yield 0.3
    on_sidebar = overlay.UI["pressed"] or overlay.UI["focused"]
    window().event_simulate("LEFTMOUSE", "RELEASE", x=ui.x + ui.width // 2, y=y)
    yield 0.3
    x = win.x + left + 40  # on the bar, left of the sidebar
    move(x, y)
    window().event_simulate("LEFTMOUSE", "PRESS", x=x, y=y)
    yield 0.3
    on_bar = overlay.UI["pressed"]
    window().event_simulate("LEFTMOUSE", "RELEASE", x=x, y=y)
    yield 0.3
    check("bar: a press on the sidebar over the bar goes to the sidebar; beside it, to the bar",
          not on_sidebar and on_bar, "sidebar taken %s, bar taken %s" % (on_sidebar, on_bar))
    screenshot("bar-09-under-sidebar.png")
    bar_state.MIN_WIDTH = real_min
    area.spaces.active.show_region_ui = False
    yield 0.4

    eachlabs.unregister()
    move(*viewport_centre())
    yield 0.4
    check("bar: unregister ends the input operator", not overlay._running_in(window()), str(modal_names()))
    eachlabs.register()
    yield 0.4
