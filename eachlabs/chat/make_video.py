"""The shot video's start and its buttons on the bar and the sidebar: Stop, Retry and Show file, and copying the
video's job into the bar's state. Main thread only. Stop and Retry ask in a Blender dialog."""

import os
import time

import bpy

from .. import confirm, main_thread, pipeline
from ..shot import price, start
from ..ui import tokens, tooltips
from . import video_track
from .live import chat_run

RUNNING = ("rendering", "photos", "generating")
RETRY_ASK = "Make a %d s, %s video through %s again. Total %s. It may still be billed after Stop."


def video_start(context, request, again="", frames=()):
    """Start the video and show it on the bar; a start that cannot run shows why on the bar.
    ``again``: the job id of a video to make again from its own request instead, with the confirmed ``frames``.
    ``start.SceneChanged`` passes through: nothing started, and the caller asks again with the new price."""
    state = chat_run.STATE
    now = time.monotonic()
    try:
        job = start.rerun(context, again, frames) if again else start.start(context, request)
        request = start.Request(**job.context["shot"]["request"])
    except start.SceneChanged:
        raise
    except pipeline.Problem as exc:
        state.video, state.video_job, state.video_message = "failed", "", str(exc).rstrip(".")
        state.video_stage, state.video_info = "camera", {"started": now, "ended": now}
        main_thread.tag_redraw()
        return None
    shot = job.context.get("shot") or {}
    photos, seconds = len(shot.get("times", [])), shot.get("seconds", request.seconds or 0)
    state.video, state.video_job, state.video_message, state.video_progress = "rendering", job.job_id, "", 0
    state.video_stage = "camera"
    state.video_info = {"seconds": seconds, "photos": photos, "started": now,
                        "price": price.total(request.resolution, seconds, photos)}
    sync()
    main_thread.tag_redraw()
    return job


def sync():
    """Copy the video's job into ``chat_run.STATE`` now; ``pipeline.tick_hook`` does it on every tick."""
    video_track.follow(chat_run.STATE, pipeline.REGISTRY, time.monotonic())


def job_of(states):
    """The video's job while ``chat_run.STATE.video`` is one of ``states``, else ``None``."""
    state = chat_run.STATE
    if state.video not in states or not state.video_job:
        return None
    return pipeline.REGISTRY.get(state.video_job)


def stop():
    job = job_of(RUNNING)
    if job is not None:
        pipeline.cancel(job.job_id)
    sync()
    main_thread.tag_redraw()


class EACHLABS_OT_chat_video_stop(bpy.types.Operator):
    bl_idname = "eachlabs.chat_video_stop"
    bl_label = "Stop video"
    bl_description = tooltips.TEXTS["video_stop"]

    @classmethod
    def poll(cls, context):
        return job_of(RUNNING) is not None

    def invoke(self, context, event):
        if chat_run.STATE.video == "rendering":  # nothing sent yet: nothing to warn about
            return self.execute(context)
        return confirm.ask(self, context, event, *tokens.CONFIRM_STOP_VIDEO)

    def execute(self, context):
        stop()
        return {"FINISHED"}


class EACHLABS_OT_chat_video_retry(bpy.types.Operator):
    bl_idname = "eachlabs.chat_video_retry"
    bl_label = "Retry video"
    bl_description = tooltips.TEXTS["video_retry"]

    frames: bpy.props.StringProperty(options={"SKIP_SAVE", "HIDDEN"})  # the key frames the dialog priced

    @classmethod
    def poll(cls, context):
        job = job_of(("failed", "stopped"))
        return job is not None and bool(job.context.get("shot")) and not chat_run.STATE.running

    def invoke(self, context, event):
        asked = _retry_price(context)
        if asked is None:
            return self.execute(context)  # the rerun refuses and says why
        self.frames = ",".join(str(f) for f in asked[1])
        return confirm.ask(self, context, event, "Make the video again?", asked[0], "Retry video")

    def execute(self, context):
        frames = tuple(int(f) for f in self.frames.split(",") if f)
        try:
            started = video_start(context, None, again=chat_run.STATE.video_job, frames=frames)
        except start.SceneChanged as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if started is None:
            self.report({"ERROR"}, chat_run.STATE.video_message)
            return {"CANCELLED"}
        return {"FINISHED"}


def _retry_price(context):
    """``(message, key frames)`` for Retry's dialog: what it makes and its price, measured on the scene as it is
    now; ``None`` when the rerun cannot run here."""
    from ..shot import view_cache

    job = job_of(("failed", "stopped"))
    request = (job.context.get("shot") or {}).get("request") if job is not None else None
    scene = context.scene
    camera = scene.objects.get(request["camera"]) if request else None
    if camera is None or camera.type != "CAMERA" or scene.name != job.context.get("scene"):
        return None
    plan = view_cache.plan_for(scene, request["seconds"])
    frames = view_cache.frames(scene, camera, request["aspect"], plan, fresh=True)
    total = price.text(price.total(request["resolution"], plan.seconds, len(frames)))
    return RETRY_ASK % (plan.seconds, request["resolution"], camera.name, total), frames


def _video_path(job):
    return next((path for path, kind in job.outputs if kind == "video"), "") if job is not None else ""


class EACHLABS_OT_chat_video_file(bpy.types.Operator):
    bl_idname = "eachlabs.chat_video_file"
    bl_label = "Show file"
    bl_description = tooltips.TEXTS["video_file"]

    @classmethod
    def poll(cls, context):
        return bool(_video_path(job_of(("done",))))

    def execute(self, context):
        path = _video_path(job_of(("done",)))
        if not os.path.isfile(path):
            self.report({"ERROR"}, "The video file is gone: %s" % path)
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=os.path.dirname(path))
        return {"FINISHED"}


CLASSES = (EACHLABS_OT_chat_video_stop, EACHLABS_OT_chat_video_retry, EACHLABS_OT_chat_video_file)
