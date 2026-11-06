"""The Video tab: its chips and menus, the confirm card, each video state with a fake job, the time a duration change
takes, and the window that plays the video next to the scene through its camera."""

import os
import shutil
import tempfile
import threading
import time

import bpy

from eachlabs import chat_run, compat, jobs, pipeline, render_export
from eachlabs.shot import start as shot_start
from tests.gui_check.args import OUT
from tests.gui_check.bar_input import answer_dialog, bar_point, click, key, move, placed, type_text, viewport_centre
from tests.gui_check.common import check, hold, override, parked, screenshot, wait_for

CLIP_FRAMES = 36  # 1.5 s at 24 fps: the window plays it to the end within the check


def _job(name, state, message="", error="", outputs=(), context=None):
    job = pipeline.REGISTRY.add(jobs.Job("gui-video-%s" % name, "SHOT", "Seedance 2.5", "model",
                                         state=state, message=message, error=error))
    job.outputs, job.context = list(outputs), dict(context or {})
    return job


def _show(job, video=""):
    state = chat_run.STATE
    state.video, state.video_job = video or "rendering", job.job_id
    from eachlabs.chat import make_video

    make_video.sync()


def _record(scene, camera, path):
    """The camera's move rendered grey and small into an MP4, so the preview shows what the 3D view shows."""
    saved = render_export.snapshot(scene, (("render", "engine"), ("", "camera"), ("render", "resolution_x"),
                                           ("render", "resolution_y")))
    folder = tempfile.mkdtemp(prefix="eachlabs-gui-clip-")
    try:
        scene.render.engine, scene.camera = "BLENDER_WORKBENCH", camera
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 320, 180, 100
        render_export._png(scene)
        scene.render.filepath = os.path.join(folder, "f_")
        start, end = scene.frame_start, scene.frame_end
        scene.frame_end = start + CLIP_FRAMES - 1
        with parked():
            bpy.ops.render.render(animation=True, scene=scene.name)
        scene.frame_end = end
        frames = sorted(os.path.join(folder, f) for f in os.listdir(folder))
        render_export.encode_mp4(frames, scene.render.fps, scene.render.fps_base, path)
    finally:
        render_export.restore(scene, saved)
        shutil.rmtree(folder, ignore_errors=True)


def _tab_click(name):
    click(*bar_point(name))


def _time_duration_changes(seconds_list):
    """Change the duration through the Video tab's menu, as a click does, and draw the bar after each: the time of
    each change, and how often the camera's view was measured meanwhile."""
    from eachlabs import overlay
    from eachlabs.chat import video_tab
    from eachlabs.shot import views
    from eachlabs.ui import bar
    from eachlabs.viewport import draw

    calls, collect = [], views.collect
    views.collect = lambda *a, **kw: calls.append(a) or collect(*a, **kw)
    took = []
    try:
        width, scale = placed()[2], placed()[3]
        with override():
            for seconds in seconds_list:
                t = time.perf_counter()
                overlay.UI["video_menu"] = "seconds"
                items = video_tab.view.menu_values(video_tab.shot(bpy.context, overlay.UI), "seconds")
                index = next((i for i, item in enumerate(items) if item[0] == seconds), 0)
                video_tab.act(bpy.context, "vmenu_%d" % index, overlay.UI, overlay.FIELD)
                bar.render(draw.current_state(), width, scale)
                took.append(time.perf_counter() - t)
    finally:
        views.collect = collect
    return took, len(calls)


def _edits_measure_nothing(scene):
    """With the Video tab chosen, edits to the scene measure nothing again, and while a modal tool (a grab) runs
    Send's measure waits for it."""
    from eachlabs import overlay
    from eachlabs.chat import video_tab
    from eachlabs.shot import view_cache, views

    calls, collect = [], views.collect
    views.collect = lambda *a, **kw: calls.append(a) or collect(*a, **kw)
    moved = next(o for o in scene.objects if o.type == "MESH")
    start = tuple(moved.location)
    selected = [o for o in scene.objects if o.select_get()]
    active = bpy.context.view_layer.objects.active
    try:
        for step in range(6):
            moved.location.x += 0.2
            bpy.context.view_layer.update()
            overlay.tag_redraw()
            yield 0.3
        moved.location = start
        bpy.context.view_layer.update()
        yield 0.6
        check("video: edits with the Video tab chosen measure nothing again; the price stays marked ≈",
              not calls and placed()[4].video_price.startswith("≈ $"), "%d measures" % len(calls))
        move(*viewport_centre())
        key("ESC")  # the bar gives the keys back, so G reaches the 3D view
        yield 0.3
        for obj in scene.objects:
            obj.select_set(obj == moved)
        bpy.context.view_layer.objects.active = moved
        key("G", "g")
        yield 0.3
        grabbing_now = not view_cache.can_measure()
        with override():
            asked = video_tab.ask(bpy.context, overlay.UI, overlay.FIELD)
        yield 0.3
        waited = not calls and not asked and not overlay.UI["video_confirm"]
        key("ESC")  # cancel the grab: nothing moved, no undo step
        opened = yield from wait_for(lambda: overlay.UI["video_confirm"], 5)
        check("video: while a grab runs nothing is measured; Send's measure and card wait for it, then open",
              grabbing_now and waited and opened and len(calls) == 1 and tuple(moved.location) == start,
              "%s %s %s %d" % (grabbing_now, waited, opened, len(calls)))
        overlay.UI["video_confirm"] = False
    finally:
        views.collect = collect
        for obj in scene.objects:
            obj.select_set(obj in selected)
        bpy.context.view_layer.objects.active = active
        overlay.tag_redraw()
    yield 0.4


def video_flow():
    """Run on the open done card of a chat whose camera moves: the Video tab's settings, menus, confirm card and
    every card state with a fake job, then the window that plays the video next to the scene."""
    from eachlabs import overlay
    from eachlabs.chat import make_video, playback
    from eachlabs.ui import video_texts as V

    scene = bpy.context.scene
    camera = scene.objects.get(playback.chosen(scene))
    hits = set(placed()[1].hits)
    check("video: the done card has no Make video pill; the Video tab is the fourth tab",
          "video" not in hits and "tab_video" in hits, str(sorted(hits)))

    _tab_click("field")
    yield 0.2
    type_text("a cosy room")
    yield 0.3
    _tab_click("tab_video")
    measured = yield from wait_for(lambda: placed()[4].mode == "video" and placed()[4].video_price.startswith("≈ $"),
                                   15)
    s = placed()[4]
    labels = [label for _h, label in s.video_chips]
    check("video: the Video tab shows its chips and the price once the camera's view is measured",
          measured and set(V.CHIP_HITS) <= set(placed()[1].hits) and overlay.FIELD.text == ""
          and labels[0] == camera.name and labels[1:3] == ["16:9", "480p"] and labels[4] == "Seedance 2.5",
          "%s %s %r" % (s.video_price, labels, overlay.FIELD.text))
    screenshot("video-tab-v1.png")
    yield from _edits_measure_nothing(scene)

    _tab_click("field")
    yield 0.2
    type_text("golden hour light mist")
    yield 0.3
    _tab_click("tab_scene")
    yield 0.4
    scene_text = overlay.FIELD.text
    _tab_click("tab_video")
    yield 0.4
    check("video: each tab keeps its own text", scene_text == "a cosy room"
          and overlay.FIELD.text == "golden hour light mist", "%r %r" % (scene_text, overlay.FIELD.text))

    _tab_click("vchip_resolution")
    yield 0.4
    s = placed()[4]
    check("video: the resolution chip opens its menu with each size's price",
          s.video_menu_title.startswith("Resolution") and [n for n, _h, _c in s.video_menu] == ["480p", "720p", "1080p"]
          and s.video_menu[0][1].startswith("draft · $") and "vmenu_2" in placed()[1].hits, str(s.video_menu))
    screenshot("video-tab-v2.png")
    key("ESC")
    yield 0.3
    check("video: Esc closes the chip's menu", not placed()[4].video_menu)

    took, measures = _time_duration_changes([4, 5, 6, 8, 4, 6, 5, 8, 4, 5])
    check("video: each duration change, drawn, takes under 50 ms and never measures the view again",
          max(took) < 0.05 and measures == 0,
          "slowest %.1f ms, mean %.1f ms, %d measures" % (1000 * max(took), 1000 * sum(took) / len(took), measures))
    print("GUI duration changes (ms): %s" % ", ".join("%.1f" % (1000 * t) for t in took), flush=True)
    yield 0.3
    _tab_click("vchip_seconds")
    yield 0.3
    _tab_click("vmenu_0")  # 4 s, by a real click
    yield 0.4
    check("video: a duration picked in its menu shows on its chip", placed()[4].video_chips[3][1] == "4 s",
          str(placed()[4].video_chips))
    started = []
    real_start = make_video.video_start
    make_video.video_start = lambda context, request, again="": started.append(request)
    try:
        _tab_click("send")
        yield 0.5
        s = placed()[4]
        check("video: Send opens the confirm card in the bar and starts nothing",
              s.video_card == "confirm" and s.video_meta.startswith("Total $") and "It may still be billed after Stop."
              in s.video_text and {"video_make", "video_cancel"} <= set(placed()[1].hits) and not started
              and chat_run.STATE.video == "", "%s %r" % (s.video_card, s.video_text))
        screenshot("video-tab-v3.png")
        _tab_click("video_cancel")
        yield 0.4
        check("video: Cancel closes it; nothing starts", placed()[4].video_card == "" and not started)
        _tab_click("field")
        yield 0.2
        key("RET")
        yield 0.5
        check("video: Enter opens the same confirm card", placed()[4].video_card == "confirm" and not started)
        _tab_click("video_make")
        yield 0.4
        check("video: only Make video starts it, with the tab's settings and text",
              len(started) == 1 and started[0].camera == camera.name and started[0].seconds == 4
              and started[0].resolution == "480p" and started[0].prompt == "golden hour light mist"
              and started[0].frames, str(started))

        def changed(context, request, again=""):
            raise shot_start.SceneChanged(shot_start.CHANGED)

        make_video.video_start = changed
        _tab_click("send")
        yield 0.5
        _tab_click("video_make")
        yield 0.5
        s = placed()[4]
        check("video: when the scene changed since Send, Make video starts nothing and the card asks again with the "
              "new price", s.video_card == "confirm" and s.video_error == V.CHANGED and chat_run.STATE.video == "",
              "%s %r" % (s.video_card, s.video_error))
        _tab_click("video_cancel")
        yield 0.3
    finally:
        make_video.video_start = real_start
    overlay.FIELD.clear()

    work = tempfile.mkdtemp(prefix="eachlabs-gui-video-")
    shot = {"clip": os.path.join(work, "clip.mp4"), "frames": 95, "times": [0], "keys": "",
            "request": {"prompt": "rainy evening", "camera": camera.name, "aspect": "1:1", "resolution": "720p",
                        "seconds": 4}, "seconds": 9}
    clip = os.path.join(work, "video.mp4")
    _record(scene, camera, clip)
    info = compat.strips(scene.sequence_editor or scene.sequence_editor_create()).new_movie(
        "EL gui-video-done", clip, 30, scene.frame_start)
    check("video: the check's clip is %d frames on the camera's scene" % CLIP_FRAMES,
          compat.strip_length(info) == CLIP_FRAMES, str(compat.strip_length(info)))
    state = chat_run.STATE
    begun = time.monotonic()
    look = _job("look", jobs.RUNNING, "Making the look (1 of 1)", context={"shot": shot})
    _show(look)
    state.video_info = {"seconds": 9, "photos": 1, "price": 1.44, "started": begun - 41}
    overlay.tag_redraw()
    yield 0.6
    priced = yield from wait_for(lambda: placed()[4].video_price.startswith("≈ $"), 5)
    check("video: the chips' price comes back while the card's spinner redraws", priced, placed()[4].video_price)
    s = placed()[4]
    check("video: while it is made the card names every stage, the time and price, the stage and the next",
          s.video_card == "progress" and list(s.stages) == ["Camera move", "Key frames", "Look 1/1", "Video", "Sequencer"]
          and list(s.stages.values()) == ["done", "done", "active", "todo", "todo"] and s.video_meta.endswith("$1.44")
          and "Next, Seedance films the camera move" in s.video_text and s.video_line == "Making the look: photo 1 of 1…"
          and "video_stop" in placed()[1].hits, "%s %s %r" % (s.stages, s.video_meta, s.video_line))
    screenshot("video-tab-v4.png")
    _tab_click("video_stop")
    yield 0.4
    asked = placed()[4].video_ask
    _tab_click("video_stop_no")
    yield 0.4
    check("video: Stop video asks in the bar, and Keep going keeps it",
          asked == V.STOP_ASK and look.state == jobs.RUNNING and not look.cancel_event.is_set()
          and placed()[4].actions == ["video_stop"], asked)

    done = _job("done", jobs.DONE, outputs=[(clip, "video")],
                context={"shot": shot, "scene": scene.name, "sequencer_scene": scene.name})
    _show(done, "done")
    state.video_info = dict(state.video_info, started=begun - 230, ended=begun)
    overlay.tag_redraw()
    yield 0.6
    s = placed()[4]
    check("video: a made video's card: all stages done, its minutes and price, Open Sequencer, Show file and "
          "Make another", s.video_card == "ready" and set(s.stages.values()) == {"done"}
          and s.video_meta == "4 min · $1.44" and s.video_text.startswith("Your 9 s video is in the Video Sequencer")
          and {"video_open", "video_file", "video_another"} <= set(placed()[1].hits),
          "%s %r" % (s.video_meta, s.video_text))
    screenshot("video-tab-v5.png")
    move(*viewport_centre())
    key("ESC")  # the bar gives the keys back before the window plays, as on the done card
    yield 0.4
    yield from _synced_window(scene, camera, info)

    failed = _job("failed", jobs.FAILED, error="Photo 1 failed: the photo was refused", context={"shot": shot})
    _show(failed)
    state.video_stage = "look"
    overlay.tag_redraw()
    yield 0.6
    s = placed()[4]
    check("video: a failed video marks its stage, says why in one line, with Retry video and Edit the settings",
          s.video_card == "failed" and s.stages.get("Look") == "failed"
          and s.video_error == "The look failed: photo 1 failed: the photo was refused."
          and {"video_retry", "video_edit"} <= set(placed()[1].hits), "%s %r" % (s.stages, s.video_error))
    screenshot("video-tab-v6.png")
    _tab_click("video_retry")
    yield 0.6
    s = placed()[4]
    check("video: Retry video puts its settings and text back and asks with the price, starting nothing",
          s.video_card == "confirm" and overlay.FIELD.text == "rainy evening" and s.video_chips[1][1] == "1:1"
          and s.video_chips[2][1] == "720p" and s.video_chips[3][1] == "4 s" and state.video == "failed",
          "%s %r %s" % (s.video_card, overlay.FIELD.text, s.video_chips))
    _tab_click("video_cancel")
    yield 0.3
    _tab_click("video_edit")
    yield 0.4
    check("video: Edit the settings closes the card and keeps the settings on the chips",
          placed()[4].video_card == "" and placed()[4].video_chips[2][1] == "720p", placed()[4].video_card)

    overlay.FIELD.clear()
    _tab_click("tab_scene")
    yield 0.5
    check("video: on the other tabs the video keeps its line, and Retry on the card",
          "Video failed: Photo 1 failed: the photo was refused" in placed()[4].reply
          and "video_retry" in placed()[1].hits, placed()[4].reply)
    state.video_resolution, state.video_aspect, state.video_length = "480p", "16:9", 0
    state.video, state.video_job, state.video_info, state.video_stage = "", "", {}, ""
    for job in (look, done, failed):
        pipeline.REGISTRY.jobs.pop(job.job_id, None)
    compat.strips(scene.sequence_editor).remove(info)
    shutil.rmtree(work, ignore_errors=True)
    overlay.FIELD.clear()
    overlay.UI["tab_text"].clear()
    overlay.tag_redraw()  # the card loses its video pills: the next clicks need the new layout's hits
    yield 0.6
    check("video: back on Scene the card has no video pills, and nothing plays",
          not [a for a in placed()[4].actions if a.startswith("video")] and not _anyone_playing(),
          str(placed()[4].actions))
    move(*viewport_centre())
    key("ESC")  # the bar gives the keys back, as the person's next edit expects
    yield 0.4


_DURING = {}  # the fake video job made before the chat run that ``during_run`` checks, and the run's gate


def before_run(client):
    """A video being made when a new chat run is sent from the done card. The run's model waits at its first call
    until ``during_run`` has checked the running bar."""
    _DURING["job"] = job = _job("during-run", jobs.RUNNING, "Seedance 2.5 is making it")
    _show(job)
    gate = _DURING["gate"] = threading.Event()
    llm = client.chat_llm
    model = type(llm)

    class Gated(model):
        def __call__(self, messages, tools):
            if not gate.is_set():
                hold(60, gate)
            return model.__call__(self, messages, tools)

    llm.__class__ = Gated
    _DURING["llm"] = (llm, model)
    yield 0.2


def during_run():
    """While the chat runs, the video's line sits on the bar's status line with Stop, and follows the job on the
    main thread's tick; when the run is done, the done card shows it again with its buttons."""
    from eachlabs import overlay

    job = _DURING.pop("job", None)
    if job is None:
        return
    gate, (llm, model) = _DURING.pop("gate"), _DURING.pop("llm")
    try:
        seen = yield from wait_for(lambda: chat_run.STATE.running and placed()[4].objects[-1:] != []
                                   and placed()[4].objects[-1].startswith("Video: Seedance 2.5 is making it…")
                                   and "video_stop" in placed()[1].hits, 10)
        check("video: a new chat run keeps the video; its line and Stop show on the bar's status line",
              seen and chat_run.STATE.video_job == job.job_id,
              "%s %s %s" % (placed()[4].mode, placed()[4].objects, sorted(placed()[1].hits)))
        screenshot("video-09-status-line.png")
        opened = yield from answer_dialog(bar_point("video_stop"), "Stop the video?", True)
        check("video: Stop on the status line asks first and cancels the video while the chat runs",
              opened and job.cancel_event.is_set() and chat_run.STATE.running, "%s %s" % (opened, job.message))
        job.apply({"state": jobs.CANCELLED, "message": "Cancelled"})  # what the worker answers to the cancel
        stopped = yield from wait_for(lambda: placed()[4].objects[-1:] == [
            "Video stopped; it may still be billed · Retry when the chat finishes."], 10)
        check("video: the status line says the video stopped and when Retry comes back", stopped and chat_run.STATE.running,
              str(placed()[4].objects))
        pipeline.REGISTRY.jobs.pop(job.job_id, None)
        job = _job("during-run-2", jobs.RUNNING, "Seedance 2.5 is making it")
        _show(job)
        job.apply({"state": jobs.DONE, "message": "Strip on channel 2"})  # the video lands while the chat runs
        moved = yield from wait_for(lambda: chat_run.STATE.running
                                    and placed()[4].objects[-1:] == ["Video: in the Video Sequencer"]
                                    and {"video_open", "video_file"} <= set(placed()[1].hits), 10)
        check("video: the status line follows the job on the tick, with Open Sequencer and Show file", moved,
              "%s %s %s" % (chat_run.STATE.running, placed()[4].objects, sorted(placed()[1].hits)))
        screenshot("video-10-status-line-done.png")
    finally:
        gate.set()
        llm.__class__ = model
    yield from wait_for(lambda: not chat_run.STATE.running, 40)
    overlay.tag_redraw()
    yield 0.6
    check("video: once the run is done, its card shows the video again with Open Sequencer",
          "Video: in the Video Sequencer" in placed()[4].reply and "video_open" in placed()[1].hits,
          "%r %s" % (placed()[4].reply, sorted(placed()[1].hits)))
    chat_run.STATE.video, chat_run.STATE.video_job = "", ""
    pipeline.REGISTRY.jobs.pop(job.job_id, None)
    overlay.tag_redraw()  # the card loses its video pills: the next clicks need the new layout's hits
    yield 0.6


def _anyone_playing():
    return any(w.screen.is_animation_playing for w in bpy.context.window_manager.windows)


def _new_window():
    from eachlabs.chat import video_window

    return video_window._window(video_window._OPEN.get("window"))


def _synced_window(scene, camera, strip):
    from eachlabs.chat import video_window

    scene_camera = scene.camera
    start, end = compat.strip_start(strip), compat.strip_end(strip) - 1
    click(*bar_point("video_open"))
    built = yield from wait_for(lambda: _new_window() is not None and video_window._areas(_new_window()) is not None
                                and _new_window().screen.is_animation_playing, 15)
    win = _new_window()
    check("video: Open Sequencer opens a window with the preview, the 3D view and the timeline, and plays",
          built, str([(a.type, a.y) for a in win.screen.areas]) if win else "no window")
    if not built:
        return
    preview, view, timeline = video_window._areas(win)
    space = view.spaces.active
    seq_scene = getattr(win.workspace, "sequencer_scene", scene)
    check("video: the 3D view looks through the video's camera without changing the scene camera, and the "
          "window's Sequencer shows the camera's scene",
          space.use_local_camera and space.camera == camera and space.region_3d.view_perspective == "CAMERA"
          and scene.camera == scene_camera and seq_scene == scene and win.scene == scene,
          "%s %s %s" % (space.camera, seq_scene, scene.camera))
    with parked(), bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=os.path.join(OUT, "video-06-window-playing.png"))
    print("SHOT", os.path.join(OUT, "video-06-window-playing.png"), flush=True)
    # Simulated events hold back the playback timer here, so the frames are stepped as playback would step them.
    for frame in range(start + 1, end + 1):
        scene.frame_set(frame)
    stopped = yield from wait_for(lambda: not _anyone_playing(), 5)
    check("video: playback stops at the video's last frame", stopped and scene.frame_current == end,
          "frame %d, end %d" % (scene.frame_current, end))
    with parked(), bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=os.path.join(OUT, "video-07-window-end.png"))
    print("SHOT", os.path.join(OUT, "video-07-window-end.png"), flush=True)
    scene.frame_set(start + 12)
    yield 0.6
    with parked(), bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=os.path.join(OUT, "video-08-window-same-frame.png"))
    print("SHOT", os.path.join(OUT, "video-08-window-same-frame.png"), flush=True)

    frame_end = scene.frame_end  # a strip that runs past the scene's last frame, as a held clip does
    scene.frame_end = start + 20
    try:
        click(*bar_point("video_open"))
        yield 0.5
        for frame in range(start + 1, scene.frame_end + 1):
            scene.frame_set(frame)
        stopped = yield from wait_for(lambda: not _anyone_playing(), 5)
        check("video: a strip past the scene's last frame stops playback there, the range unchanged",
              stopped and scene.frame_current == start + 20 and scene.frame_end == start + 20,
              "frame %d" % scene.frame_current)
    finally:
        scene.frame_end = frame_end
    click(*bar_point("video_open"))
    yield 0.5
    for frame in range(start + 1, start + 8):
        scene.frame_set(frame)
    scene.frame_set(scene.frame_start)  # playback wrapped to the start
    stopped = yield from wait_for(lambda: not _anyone_playing(), 5)
    check("video: playback that wraps back to the start stops", stopped and not video_window._WATCH,
          str(video_window._WATCH))

    for round_ in range(3):  # pressed again: the same window plays again from the start
        click(*bar_point("video_open"))
        yield 0.5
        check("video: Open Sequencer again (%d) plays the same window from the video's first frame" % (round_ + 1),
              _new_window() == win and win.screen.is_animation_playing
              and len(bpy.context.window_manager.windows) == 2, str(scene.frame_current))
    with parked(), bpy.context.temp_override(window=win):
        bpy.ops.wm.window_close()
    yield 0.3
    scene.frame_set(scene.frame_current + 1)  # the next playback step finds its window gone
    stopped = yield from wait_for(lambda: not _anyone_playing(), 5)
    check("video: closing the window while it plays stops playback and the watch, and Blender keeps running",
          stopped and len(bpy.context.window_manager.windows) == 1 and not video_window._WATCH
          and video_window._on_frame in bpy.app.handlers.frame_change_post, str(video_window._WATCH))
    for round_ in range(3):  # opened from scratch each time, the timer steps building it
        click(*bar_point("video_open"))
        built = yield from wait_for(lambda: _new_window() is not None and _new_window().screen.is_animation_playing, 15)
        video_window.close()
        yield 0.8
        check("video: open and close the window (%d)" % (round_ + 1),
              built and len(bpy.context.window_manager.windows) == 1, str(built))
    check("video: nothing plays once the window is closed", not _anyone_playing())
    yield 0.3
    check("video: closing the window removes its workspace, and no other",
          not [w for w in bpy.data.workspaces if w.get(video_window.TAG)] and "Layout" in bpy.data.workspaces,
          str([w.name for w in bpy.data.workspaces]))
