"""The shot video's Blender side: things in view, the clay clip, the key renders, the job and its Retry."""

import hashlib
import math
import os
import time
import types

import bpy

from eachlabs import compat, importers, jobs, pipeline
from eachlabs.shot import models, render, start, timing, view_cache, views
from eachlabs.things import ids, registry
from tests.blender_fakes import FakeClient, offline_api
from tests.smoke.common import WORK, check
from tests.smoke.export import drive, tone_clip

# Settings the renders change, set here to values no render uses, so putting them back is visible.
UNUSUAL = (
    ("render", "resolution_percentage", 50),
    ("render", "film_transparent", True),
    ("render", "use_motion_blur", True),
    ("display.shading", "light", "FLAT"),
    ("display.shading", "color_type", "OBJECT"),
    ("display.shading", "single_color", (0.1, 0.2, 0.3)),
    ("display.shading", "show_cavity", False),
    ("display.shading", "show_shadows", False),
    ("display.shading", "show_object_outline", True),
    ("eevee", "taa_render_samples", 7),
    ("render.image_settings", "quality", 55),
)


def _owner(scene, path):
    for part in filter(None, path.split(".")):
        scene = getattr(scene, part)
    return scene


def _settings(scene):
    values = [(path, attr, getattr(_owner(scene, path), attr)) for path, attr, _ in UNUSUAL]
    values = [(p, a, tuple(round(x, 4) for x in v) if a == "single_color" else v) for p, a, v in values]
    return values + [("", "engine", scene.render.engine), ("", "size", (scene.render.resolution_x,
                     scene.render.resolution_y)), ("", "camera", scene.camera), ("", "range", (scene.frame_start,
                     scene.frame_end)), ("", "filepath", scene.render.filepath)]


def _thing(scene, name, kind, location, size, parent=None):
    """A tagged empty with one cube part, like a thing the chat built."""
    root = bpy.data.objects.new(name, None)
    scene.collection.objects.link(root)
    root.location = location
    tid = registry.declare(root, kind, parent=parent, objects=list(scene.objects))
    mesh = bpy.data.meshes.new(name + " part")
    half = size / 2.0
    mesh.from_pydata([(x, y, z) for x in (-half, half) for y in (-half, half) for z in (-half, half)], [],
                     [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
    part = bpy.data.objects.new(name + " part", mesh)
    scene.collection.objects.link(part)
    part.parent = root
    part[ids.THING] = tid
    return root, part


def _uploads():
    return len([entry for entry in FakeClient.log if entry[0] == "upload"])


def _close_up(scene, teapot):
    """A camera close to the teapot, with the teapot overflowing the frame, counts it as shown; a camera inside the
    teapot's box leaves it out, since a box around the camera is what a room is."""
    cam = bpy.data.objects.new("Close camera", bpy.data.cameras.new("Close camera"))
    scene.collection.objects.link(cam)
    cam.rotation_euler = (math.radians(90), 0.0, 0.0)
    try:
        cam.location = (0.0, -1.3, 0.2)
        found = views.collect(scene, cam, scene.frame_start, scene.frame_start, size=(1280, 720))
        share = found.get(scene.frame_start, {}).get(teapot.name, 0.0)
        check("shot: a close-up that overflows the frame counts the thing as shown", share >= 0.9, "share %.3f" % share)
        cam.location = (0.0, -0.5, 0.2)
        found = views.collect(scene, cam, scene.frame_start, scene.frame_start, size=(1280, 720))
        check("shot: a camera inside a thing's box leaves the thing out",
              teapot.name not in found.get(scene.frame_start, {}), str(found))
    finally:
        bpy.data.objects.remove(cam)


def _stopped(scene, plan):
    """A job stopped mid-way: nothing more renders, nothing reports done, the clay frames are removed."""
    calls = []
    folder = os.path.join(WORK, "stopped_keys")
    render.key_frames(bpy.context, scene, scene.camera, [scene.frame_start, scene.frame_start + 6], (320, 180), folder,
                      calls.append, calls.append, still_wanted=lambda: not os.listdir(folder))
    clip = os.path.join(WORK, "stopped_clip.mp4")
    render.clay_clip(bpy.context, scene, scene.camera, plan, (320, 180), clip, calls.append, calls.append,
                     still_wanted=lambda: False)
    check("shot: a stopped job renders no more key frames and encodes no clip",
          calls == [] and len(os.listdir(folder)) == 1 and not os.path.exists(clip)
          and not os.path.isdir(os.path.join(WORK, "stopped_clip_frames")), "%s %s" % (calls, os.listdir(folder)))


def _bar_follows(job, clip):
    """The done card follows the finished job."""
    from eachlabs import chat_run
    from eachlabs.chat import make_video

    state = chat_run.STATE
    saved = (state.video, state.video_job)
    try:
        state.video, state.video_job = "rendering", job.job_id
        make_video.sync()
        check("shot: the bar shows the finished video, with Show file",
              state.video == "done" and bpy.types.EACHLABS_OT_chat_video_file.poll(bpy.context), state.video)
        state.video = "failed"
        asked = make_video._retry_price(bpy.context)
        check("shot: Retry without the bar asks with what it makes and its price for the scene as it is now",
              asked is not None and "Total $" in asked[0] and "It may still be billed after Stop." in asked[0]
              and len(asked[1]) == 2, str(asked))
    finally:
        state.video, state.video_job = saved


def _digest(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _retry_while_chat_runs(job, teapot):
    """The scene changes after the first video, so Retry renders again. While that video is made, a new chat run
    starts: the video stays, its line moves to the bar's status line, and it still lands in the Sequencer. An object
    changed after the upload leaves the uploaded clip alone."""
    from eachlabs import chat_run
    from eachlabs.ui import bar_state
    from eachlabs.ui.text_field import TextField
    from tests.blender_fakes import FakeLLM, text_reply
    from tests.smoke.chat_common import _chat_drive

    def bar():
        return bar_state.from_chat(state, TextField([], mac=False), False, time.monotonic())

    shot, state = job.context["shot"], chat_run.STATE
    first = _digest(shot["clip"])
    saved = (state.video, state.video_job)
    chat_scene = bpy.data.scenes.new("eachlabs_shot_chat")
    teapot.location.x += 1.5  # the scene changed after the first video
    uploads = _uploads()
    jobs_before = len(pipeline.REGISTRY.jobs)
    FakeClient.statuses["next"] = "processing"  # the photos wait on each::labs until the chat run is over
    try:
        try:
            start.rerun(types.SimpleNamespace(scene=chat_scene), job.job_id)
            refused = ""
        except pipeline.Problem as exc:
            refused = str(exc)
        check("shot: Retry from another scene is refused and names the video's scene",
              job.context["scene"] in refused and len(pipeline.REGISTRY.jobs) == jobs_before, refused)
        again = start.rerun(bpy.context, job.job_id)
        state.video, state.video_job = "rendering", again.job_id
        drive(again.job_id, lambda j: j.state == jobs.RUNNING and j.message.startswith("Making the look"), timeout=180)
        redone = again.context.get("shot", {})
        sent = _digest(redone["clip"]) if os.path.isfile(redone.get("clip", "")) else ""
        check("shot: Retry after a scene change renders again: a new clip and new key frames",
              redone.get("clip") != shot["clip"] and sent and sent != first and len(redone.get("renders", [])) == 2
              and set(redone["renders"]).isdisjoint(shot["renders"]), str(redone.get("renders")))
        check("shot: the main thread's tick copies the job to the bar, with nothing drawn",
              state.video == "photos" and state.video_message == "1 of 2", "%s %r" % (state.video, state.video_message))

        teapot.location.x += 1.5  # after the upload: the running job no longer reads the scene
        uploaded = _uploads()
        FakeClient.chat_llm = FakeLLM([text_reply("Nothing to change.")])
        chat_run.start(types.SimpleNamespace(scene=chat_scene, preferences=bpy.context.preferences), "a bench")
        shown = bar()
        check("shot: a new chat run keeps the video, and its line moves to the bar's status line",
              state.running and (state.video, state.video_job) == ("photos", again.job_id)
              and shown.objects[-1:] == ["Video: making the look (1 of 2)…"],
              "%s %s %s %s" % (state.running, state.video, shown.mode, shown.objects))
        _chat_drive()
        FakeClient.statuses["next"] = "success"
        drive(again.job_id, lambda j: not j.active, timeout=120)
        editor = bpy.data.scenes[again.context["scene"]].sequence_editor
        strip = next((s for s in compat.all_strips(editor) if s.name == "EL " + again.job_id), None) if editor else None
        check("shot: after the chat run the video still lands in the Sequencer, and the bar says so",
              again.state == jobs.DONE and strip is not None and state.video == "done"
              and redone.get("request") == shot.get("request") and _uploads() == uploads + 3,
              "%s %s, %d new uploads" % (again.error or again.message, state.video, _uploads() - uploads))
        check("shot: an object changed after the upload renders and uploads nothing again: the clip file is the same",
              _digest(redone["clip"]) == sent and _uploads() == uploaded, "%d uploads after" % (_uploads() - uploaded))
    finally:
        FakeClient.statuses["next"] = "success"
        chat_run.cancel(drop_build=True)
        chat_run.reset_view()
        bpy.data.scenes.remove(chat_scene)
        state.video, state.video_job = saved


def _no_chat_build():
    """A scene opened from a file: no chat run built it, so there is no chat build; a camera is enough."""
    from eachlabs import chat_run

    chat_run._build = None


def _measured_once(scene):
    """The camera's view is measured once per camera and aspect: changing the duration only picks again, and an
    edit to an object marks the measure stale."""
    calls = []
    collect = views.collect

    def counted(*args, **kw):
        calls.append(args[2:4])
        return collect(*args, **kw)

    views.collect = counted
    try:
        view_cache.forget()
        cam = scene.camera
        before = view_cache.photos(scene, cam, "16:9", 4)
        view_cache.measure(scene, cam, "16:9")
        took = []
        for seconds in (4, 5, 6, 4, 5, 6):
            t = time.perf_counter()
            view_cache.photos(scene, cam, "16:9", seconds)
            took.append(time.perf_counter() - t)
        check("shot: a duration change reads the one measure, never measures again, in well under 50 ms",
              before is None and len(calls) == 1 and max(took) < 0.05,
              "%d measures, slowest %.1f ms" % (len(calls), 1000 * max(took)))
        view_cache.measure(scene, cam, "1:1")
        check("shot: another aspect is a measure of its own", len(calls) == 2 and view_cache.measured(scene, cam, "16:9"))
        moved = scene.objects[0]
        for step in range(5):  # edits with the tab chosen: the last measure stays, nothing measures again
            moved.location.x += 0.1
            bpy.context.view_layer.update()
            from eachlabs import main_thread

            main_thread.tick()
        check("shot: edits measure nothing again; the last measure stays for the price",
              len(calls) == 2 and view_cache.photos(scene, cam, "16:9", 4) is not None, "%d measures" % len(calls))
        moved.location.x -= 0.5
        _load_forgets(scene, cam)
    finally:
        views.collect = collect


def _load_forgets(scene, cam):
    """Opening another file forgets every measure: its scene and camera may carry the same names."""
    from eachlabs import chat_run, render_export

    saved = chat_run.cancel, chat_run.reset_view, render_export.cancel_pending, pipeline.REGISTRY.cancel_all
    chat_run.cancel = chat_run.reset_view = render_export.cancel_pending = lambda *a, **kw: None
    pipeline.REGISTRY.cancel_all = lambda *a, **kw: None
    try:
        pipeline.on_load_pre(None)  # what Blender calls before it opens another file
    finally:
        chat_run.cancel, chat_run.reset_view, render_export.cancel_pending, pipeline.REGISTRY.cancel_all = saved
    check("shot: opening another file forgets the measures, so the same names measure again",
          not view_cache.measured(scene, cam, "16:9") and view_cache.photos(scene, cam, "16:9", 4) is None)


def _changed_scene_refuses(scene):
    """Make video carries the key frames the confirm card priced; a scene that shows others since starts nothing."""
    before = len(pipeline.REGISTRY.jobs)
    request = start.Request(prompt="", camera=scene.camera.name, aspect="16:9", resolution="480p", seconds=4,
                            frames=(scene.frame_start, 99999))
    try:
        start.start(bpy.context, request)
        refused = ""
    except start.SceneChanged as exc:
        refused = str(exc)
    check("shot: a start whose priced key frames the scene no longer shows refuses and makes no job",
          refused == start.CHANGED and len(pipeline.REGISTRY.jobs) == before, refused)


def test_shot_flow(scene):
    """Over the orbit scene, inside a room: one thing always in view, one that comes into view at frame 30, and a
    floor in view at every frame. No chat build: the camera move alone is enough."""
    _no_chat_build()
    made = []
    room = _thing(scene, "Room", "room", (0, 0, 0), 40.0)
    always = _thing(scene, "Teapot", "teapot", (0, 0, 0), 2.2, parent=room[0])
    later = _thing(scene, "Lamp", "lamp", (0, 0, 100), 0.5)
    floor = _thing(scene, "Floor", "floor", (0, 0, -4.0), 6.0)
    made += room + always + later + floor
    lamp = later[0]
    for frame, z in ((scene.frame_start, 100.0), (29, 100.0), (30, 1.6)):
        lamp.location.z = z
        lamp.keyframe_insert("location", index=2, frame=frame)
    for fcurve in compat.object_fcurves(lamp):
        for point in fcurve.keyframe_points:
            point.interpolation = "CONSTANT"
    scene.frame_set(scene.frame_start)
    found = views.collect(scene, scene.camera, scene.frame_start, scene.frame_end, size=(1280, 720))
    seen = set().union(*found.values())
    check("shot: a thing around the camera is left out; a thing inside it is still shown",
          room[0].name not in seen and {always[0].name, later[0].name, floor[0].name} <= seen
          and all(floor[0].name in shown for shown in found.values()), str(sorted(seen)))
    _close_up(scene, always[0])
    _measured_once(scene)

    camera = scene.camera
    original = [(path, attr, getattr(_owner(scene, path), attr)) for path, attr, _ in UNUSUAL]
    original = [(p, a, tuple(v) if a == "single_color" else v) for p, a, v in original]
    for path, attr, value in UNUSUAL:
        setattr(_owner(scene, path), attr, value)
    before = _settings(scene)
    fps = scene.render.fps / scene.render.fps_base
    plan = timing.plan(scene.frame_start, scene.frame_end, fps, None)
    _stopped(scene, plan)
    with offline_api():
        FakeClient.results["next"], FakeClient.statuses["next"] = tone_clip(96, "shot96"), "success"
        FakeClient.by_model[models.PHOTO["slug"]] = "photo.jpg"
        request = start.Request(prompt="", camera=camera.name, aspect="16:9", resolution="480p", seconds=None)
        view = bpy.context.preferences.view
        shown = view.render_display_type
        view.render_display_type = "WINDOW"
        try:
            _changed_scene_refuses(scene)
            job = start.start(bpy.context, request)
            hidden = view.render_display_type
            drive(job.job_id, lambda j: not j.active, timeout=180)
            check("shot: Blender's render window stays hidden during the shot's renders and comes back after",
                  hidden == "NONE" and view.render_display_type == "WINDOW",
                  "%s during, %s after" % (hidden, view.render_display_type))
            shot = job.context.get("shot", {})
            clip = shot.get("clip", "")
            count, _fps = importers.probe_movie(clip) if os.path.isfile(clip) else (0, 0)
            size = tuple(bpy.data.movieclips.load(clip).size) if count else ()
            frames = plan.frame_end - plan.frame_start + 1 + plan.hold
            check("shot: the clay clip is 1280x720 with the plan's frames, the hold included",
                  size == (1280, 720) and count == frames == 96, "%s %d of %d" % (size, count, frames))
            check("shot: the clay clip's frame folder is removed", not os.path.isdir(os.path.splitext(clip)[0] + "_frames"))
            renders = shot.get("renders", [])
            check("shot: two key renders, the first frame and the frame the lamp comes into view",
                  len(renders) == 2 and all(os.path.isfile(p) for p in renders), str(renders))
            after = _settings(scene)
            check("shot: engine, shading, size, samples, camera and frame range are put back", before == after,
                  str([(b, a) for b, a in zip(before, after) if b != a]))
            created = [e for e in FakeClient.log if e[0] == "create" and e[1] == models.VIDEO["slug"]]
            sent = created[-1][2] if created else {}
            check("shot: the video request sends the clip, two photos and 4 s",
                  len(sent.get("video_urls", [])) == 1 and len(sent.get("image_urls", [])) == 2
                  and sent.get("duration") == "4", str(sent))
            editor = scene.sequence_editor
            strip = next((s for s in compat.all_strips(editor) if s.name == "EL " + job.job_id), None) if editor else None
            check("shot: the video lands in the camera's own scene, at the move's first frame",
                  job.state == jobs.DONE and strip is not None and job.context.get("sequencer_scene") == scene.name
                  and compat.strip_start(strip) == scene.frame_start, job.error or job.message)
            _bar_follows(job, clip)

            _retry_while_chat_runs(job, always[0])
        finally:
            view.render_display_type = shown
            FakeClient.by_model.clear()
            for path, attr, value in original:
                setattr(_owner(scene, path), attr, value)
            for obj in made:
                bpy.data.objects.remove(obj)


def _moved_by_a_constraint(scene, cam):
    """A camera with no keys of its own that tracks a moving target, or follows an animated path, moves."""
    from eachlabs.chat import playback

    target = bpy.data.objects.new("Moving target", None)
    scene.collection.objects.link(target)
    path = bpy.data.curves.new("Camera path", "CURVE")
    path.splines.new("POLY").points.add(1)
    rail = bpy.data.objects.new("Camera rail", path)
    scene.collection.objects.link(rail)
    try:
        for frame, x in ((scene.frame_start, 0.0), (scene.frame_end, 4.0)):
            target.location.x = x
            target.keyframe_insert("location", index=0, frame=frame)
        track = cam.constraints.new("TRACK_TO")
        track.target = target
        tracking = playback.camera_moves(scene, cam.name)
        track.target = rail  # a still target: still again
        still_target = playback.camera_moves(scene, cam.name)
        cam.constraints.remove(track)
        follow = cam.constraints.new("FOLLOW_PATH")
        follow.target = rail
        for frame, value in ((scene.frame_start, 0.0), (scene.frame_end, 100.0)):
            path.eval_time = value
            path.keyframe_insert("eval_time", frame=frame)
        following = playback.camera_moves(scene, cam.name)
        cam.constraints.remove(follow)
        check("shot: a camera tracking a moving target or following an animated path moves; a still target does not",
              tracking and following and not still_target and not playback.camera_moves(scene, cam.name),
              "%s %s %s" % (tracking, following, still_target))
    finally:
        bpy.data.objects.remove(target)
        bpy.data.objects.remove(rail)
        bpy.data.curves.remove(path)


def test_still_shot(scene):
    """A camera that does not move, in a scene with no chat build and no tagged things: the video is a still shot of
    5 s, the 48-frame range filmed and its last frame held, with one photo, of the first frame."""
    from eachlabs import chat_run
    from eachlabs.chat import playback

    _no_chat_build()
    cam = bpy.data.objects.new("Still camera", bpy.data.cameras.new("Still camera"))
    scene.collection.objects.link(cam)
    cam.location, cam.rotation_euler = (0.0, -8.0, 1.0), (math.radians(85), 0.0, 0.0)
    saved = scene.camera, chat_run.STATE.play_camera
    scene.camera, chat_run.STATE.play_camera = cam, cam.name
    try:
        fps = scene.render.fps / scene.render.fps_base
        check("shot: a still camera is a camera to film through, and its video starts at 5 s, up to 15 s",
              playback.chosen(scene) == cam.name and not playback.camera_moves(scene)
              and timing.longest(scene.frame_start, scene.frame_end, fps, False) == 15
              and timing.default_seconds(scene.frame_start, scene.frame_end, fps, False) == 5,
              "%s %s" % (playback.chosen(scene), playback.camera_moves(scene)))
        _moved_by_a_constraint(scene, cam)
        plan = timing.plan(scene.frame_start, scene.frame_end, fps, 5)
        with offline_api():
            FakeClient.results["next"], FakeClient.statuses["next"] = tone_clip(120, "still120"), "success"
            FakeClient.by_model[models.PHOTO["slug"]] = "photo.jpg"
            try:
                job = start.start(bpy.context, start.Request(prompt="", camera=cam.name, aspect="16:9",
                                                             resolution="480p", seconds=5))
                drive(job.job_id, lambda j: not j.active, timeout=180)
                shot = job.context.get("shot", {})
                clip = shot.get("clip", "")
                count, clip_fps = importers.probe_movie(clip) if os.path.isfile(clip) else (0, 0)
                check("shot: a still shot's clay clip runs 5 s: the scene's 48 frames, then the last one held",
                      count == 120 and abs(count / (clip_fps or 1) - 5.0) < 0.05 and plan.hold == 72,
                      "%d frames at %s fps, hold %d" % (count, clip_fps, plan.hold))
                created = [e for e in FakeClient.log if e[0] == "create" and e[1] == models.VIDEO["slug"]]
                sent = created[-1][2] if created else {}
                check("shot: a still shot sends one photo, of the first frame, and 5 s",
                      job.state == jobs.DONE and len(shot.get("renders", [])) == 1 and shot.get("times") == [0.0]
                      and len(sent.get("image_urls", [])) == 1 and sent.get("duration") == "5",
                      "%s %s %s" % (job.error or job.state, shot.get("times"), sent))
                check("shot: a still shot's prompt says the camera stays still, not that it follows a path",
                      "camera stays still" in sent.get("prompt", "") and "camera path" not in sent.get("prompt", ""),
                      sent.get("prompt", ""))
            finally:
                FakeClient.by_model.clear()
    finally:
        scene.camera, chat_run.STATE.play_camera = saved
        bpy.data.objects.remove(cam)
