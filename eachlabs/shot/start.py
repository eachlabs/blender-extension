"""Starting a shot video: check the request, find the key frames, render the clay clip and the key frames, then run
the worker on the job registry, so the result reaches the Video Sequencer like every video job. Main thread only."""

import os
from dataclasses import asdict, dataclass

import bpy

from .. import jobs, main_thread, naming, pipeline, preferences
from .. import timing as scene_timing
from . import models, render, render_window, timing, view_cache, worker

SHOT = "SHOT"  # the job's action
CHANGED = "The scene changed; check the new price"


class SceneChanged(pipeline.Problem):
    """The scene shows other key frames than the person confirmed: nothing starts and nothing is billed."""


@dataclass(frozen=True)
class Request:
    prompt: str  # the person's direction; may be empty
    camera: str  # the camera object's name
    aspect: str
    resolution: str
    seconds: int = None  # None: the move's length
    frames: tuple = ()  # the key frames whose photos the person confirmed the price of; () when none was shown


def start(context, request):
    """Check ``request``, add its job and start the renders. Raises ``pipeline.Problem`` when it cannot start, and
    ``SceneChanged`` when the scene no longer shows the key frames the person confirmed (nothing is made or billed);
    a render that fails later fails the job."""
    scene = context.scene
    api = pipeline._common_checks(context)
    camera = _check(scene, request)
    fps = scene_timing.scene_fps(scene.render.fps, scene.render.fps_base)
    plan = timing.plan(scene.frame_start, scene.frame_end, fps, request.seconds)
    size = timing.clip_size(request.aspect)
    still = not _moves(scene, camera)
    try:
        frames = key_frames(scene, camera, plan, request.aspect, fresh=True)
    except (RuntimeError, ReferenceError) as exc:
        raise pipeline.Problem("Reading the camera move failed: %s" % exc)
    if request.frames and tuple(frames) != tuple(request.frames):
        raise SceneChanged(CHANGED)
    folder = naming.output_dir(bpy.data.filepath)
    job_id = naming.new_id()
    job = pipeline.REGISTRY.add(jobs.Job(job_id, SHOT, models.VIDEO["label"], "model"))
    _place(job, context, scene, plan)
    shot = {"request": asdict(request), "seconds": plan.seconds, "folder": folder,
            "clip": naming.input_path(folder, job_id, "clip", "mp4"), "renders": [], "times": [],
            "frames": plan.frame_end - plan.frame_start + 1, "keys": os.path.join(folder, job_id + "_keys")}
    job.context["shot"] = shot
    shot["times"] = [round((f - plan.frame_start) / fps, 2) for f in frames]
    job.message = "Recording the camera move"

    def failed(message):
        pipeline._render_failed(job, message)

    def keys_done(paths):
        if not job.active:
            return
        shot["renders"] = paths
        _launch(job, shot, request, api, still)

    def clip_done(_path):
        if not job.active:
            return
        job.message = "Rendering the key frames"
        render.key_frames(context, scene, camera, frames, size, shot["keys"], keys_done, failed, wanted)

    def waiting():
        job.message = "Waiting for the scene chat to finish"

    def wanted():
        return job.active

    render_window.hide_while(job)
    render.clay_clip(context, scene, camera, plan, size, shot["clip"], clip_done, failed, waiting, wanted)
    main_thread.start()
    return job


def key_frames(scene, camera, plan, aspect, fresh=False):
    """The frames of ``plan`` that become photos, as ``start`` picks them; the price counts them from the same
    measure. ``fresh``: measure the scene as it is now, as a start does, since an edit may have gone unseen."""
    return view_cache.frames(scene, camera, aspect, plan, fresh)


def _moves(scene, camera):
    from ..chat import playback  # the shot is filmed through any camera; Play's rule says whether it moves

    return playback.camera_moves(scene, camera.name)


def rerun(context, job_id, frames=()):
    """Make a finished shot job's video again from its request: new renders, new uploads, new photos and video.
    Renders are never reused, since the scene may have changed in ways no check sees. ``frames``: the key frames
    whose price the person confirmed for this run, as for ``Request.frames``."""
    old = pipeline.REGISTRY.get(job_id)
    shot = old.context.get("shot") if old is not None else None
    if not shot:
        raise pipeline.Problem("This video can no longer be retried; make it again.")
    if old.active:
        raise pipeline.Problem("This video is still being made.")
    if context.scene.name != old.context.get("scene"):
        raise pipeline.Problem("This video belongs to the scene %r; switch to it to retry." % old.context.get("scene"))
    return start(context, Request(**dict(shot["request"], frames=tuple(frames))))


def _check(scene, request):
    camera = scene.objects.get(request.camera)
    if camera is None or camera.type != "CAMERA":
        raise pipeline.Problem("The camera %r is not in this scene." % request.camera)
    if request.aspect not in models.ASPECTS:
        raise pipeline.Problem("Videos come in %s, not %s." % (", ".join(models.ASPECTS), request.aspect))
    if request.resolution not in models.RESOLUTIONS:
        raise pipeline.Problem("Videos come in %s, not %s." % (", ".join(models.RESOLUTIONS), request.resolution))
    if scene.frame_end < scene.frame_start:
        raise pipeline.Problem("The frame range ends before it starts.")
    return camera


def _place(job, context, scene, plan):
    """What ``pipeline.import_result`` needs to put the video on the scene's timeline. The strip goes into the
    camera's own scene, not a separate sequencer scene, so one playhead drives the video and the camera move."""
    settings = scene.eachlabs
    job.context = {"scene": scene.name, "sequencer_scene": scene.name,
                   "workspace": pipeline._workspace_name(context), "frame_start": plan.frame_start,
                   "frames": plan.frame_end - plan.frame_start + 1 + plan.hold, "timing": settings.timing_mode,
                   "import_audio": settings.import_audio}


def _launch(job, shot, request, api, still=False):
    spec = worker.ShotSpec(
        job_id=job.job_id, output_dir=shot["folder"], clip_path=shot["clip"], render_paths=list(shot["renders"]),
        times=list(shot["times"]), person=request.prompt, aspect=request.aspect, resolution=request.resolution,
        seconds=shot["seconds"], still=still, api_key=api["api_key"], base_url=api["base_url"],
        user_agent=preferences.user_agent(), poll_interval=api["poll_interval"],
        timeout_seconds=api["timeout_seconds"])
    job.apply({"state": jobs.UPLOADING, "message": ""})
    pipeline.REGISTRY.start(job, spec, worker=worker.run)

