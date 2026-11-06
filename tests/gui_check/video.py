"""The shot video on the bar: its line and pills on the done card in each state with a fake job, on the status line
while a new chat run goes, and the window that plays the video next to the scene through its camera."""

import os
import shutil
import tempfile
import threading

import bpy

from eachlabs import chat_run, compat, jobs, pipeline, render_export
from tests.gui_check.args import OUT
from tests.gui_check.bar_input import answer_dialog, bar_point, click, key, move, placed, viewport_centre
from tests.gui_check.common import check, hold, parked, screenshot, wait_for

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


def video_flow():
    """Run on the open done card of a chat whose camera moves: the video's line and its pills in each state, with a
    fake job, then the window that plays the video next to the scene."""
    from eachlabs import overlay
    from eachlabs.chat import playback

    state = chat_run.STATE
    scene = bpy.context.scene
    camera = scene.objects.get(playback.chosen(scene))
    work = tempfile.mkdtemp(prefix="eachlabs-gui-video-")
    clip = os.path.join(work, "video.mp4")
    _record(scene, camera, clip)
    info = compat.strips(scene.sequence_editor or scene.sequence_editor_create()).new_movie(
        "EL gui-video-done", clip, 30, scene.frame_start)
    check("video: the check's clip is %d frames on the camera's scene" % CLIP_FRAMES,
          compat.strip_length(info) == CLIP_FRAMES, str(compat.strip_length(info)))
    look = _job("look", jobs.RUNNING, "Making the look (1 of 2)")
    _show(look)
    overlay.tag_redraw()
    yield 0.6
    check("video: while it is made the done card shows its line with Stop video",
          "Video: making the look (1 of 2)…" in placed()[4].reply and "video_stop" in placed()[1].hits,
          "%r %s" % (placed()[4].reply, sorted(placed()[1].hits)))
    screenshot("video-01-making.png")

    shot = {"request": {"prompt": "", "camera": camera.name, "aspect": "16:9", "resolution": "480p", "seconds": 4}}
    done = _job("done", jobs.DONE, outputs=[(clip, "video")],
                context={"shot": shot, "scene": scene.name, "sequencer_scene": scene.name})
    _show(done, "done")
    overlay.tag_redraw()
    yield 0.6
    check("video: a made video's line says it is in the Video Sequencer, with Open Sequencer and Show file",
          "Video: in the Video Sequencer" in placed()[4].reply
          and {"video_open", "video_file"} <= set(placed()[1].hits),
          "%r %s" % (placed()[4].reply, sorted(placed()[1].hits)))
    move(*viewport_centre())
    key("ESC")  # the bar gives the keys back before the window plays
    yield 0.4
    yield from _synced_window(scene, camera, info)

    failed = _job("failed", jobs.FAILED, error="Photo 1 failed: the photo was refused", context={"shot": {}})
    _show(failed)
    overlay.tag_redraw()
    yield 0.6
    check("video: a failed video's line says why, with Retry video",
          "Video failed: Photo 1 failed: the photo was refused" in placed()[4].reply
          and "video_retry" in placed()[1].hits, placed()[4].reply)
    screenshot("video-02-failed.png")

    state.video, state.video_job, state.video_info, state.video_stage = "", "", {}, ""
    for job in (look, done, failed):
        pipeline.REGISTRY.jobs.pop(job.job_id, None)
    compat.strips(scene.sequence_editor).remove(info)
    shutil.rmtree(work, ignore_errors=True)
    overlay.tag_redraw()  # the card loses its video pills: the next clicks need the new layout's hits
    yield 0.6
    check("video: without a video the card has no video pills, and nothing plays",
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
