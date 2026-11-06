"""The shot video's start and its buttons outside the bar's Video tab: Make video (opens the tab), Stop, Retry, Open
Sequencer and Show file, and copying the video's job into the bar's state. Main thread only.

The Video tab (``video_tab.py``) holds the settings and asks before anything is paid; these operators keep the ids
the sidebar and the status row's pills call. Without the bar (no Skia), Stop and Retry ask in a Blender dialog."""

import os
import time

import bpy

from .. import confirm, main_thread, pipeline
from ..shot import price, start
from ..ui import tokens, tooltips
from . import video_track, video_window
from .live import chat_run

RUNNING = ("rendering", "photos", "generating")


def video_start(context, request, again="", frames=()):
    """Start the video and show it on the bar; a start that cannot run shows why on the Video tab's card.
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


def _bar():
    from .. import overlay

    return overlay if overlay.active() else None


class EACHLABS_OT_chat_make_video(bpy.types.Operator):
    bl_idname = "eachlabs.chat_make_video"
    bl_label = "Make video"
    bl_description = tooltips.TEXTS["tab_video"]

    @classmethod
    def poll(cls, context):
        return not chat_run.STATE.running and _bar() is not None

    def execute(self, context):
        _bar().show_tab(context, "video")
        return {"FINISHED"}


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
        bar = _bar()
        if bar is not None:  # the Video tab asks, with the settings and the price
            bar.show_tab(context, "video")
            from . import video_tab

            video_tab.retry(context, bar.UI, bar.FIELD)
            return {"FINISHED"}
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
    """``(message, key frames)`` for Retry's dialog without the bar: what it makes and its price, measured on the
    scene as it is now; ``None`` when the rerun cannot run here."""
    from ..shot import view_cache
    from ..ui import video_tab as view

    job = job_of(("failed", "stopped"))
    request = (job.context.get("shot") or {}).get("request") if job is not None else None
    scene = context.scene
    camera = scene.objects.get(request["camera"]) if request else None
    if camera is None or camera.type != "CAMERA" or scene.name != job.context.get("scene"):
        return None
    plan = view_cache.plan_for(scene, request["seconds"])
    frames = view_cache.frames(scene, camera, request["aspect"], plan, fresh=True)
    shot = view.Shot(camera=camera.name, aspect=request["aspect"], resolution=request["resolution"],
                     seconds=plan.seconds, photos={plan.seconds: len(frames)})
    meta, text, _label = view.confirm(shot)
    return "%s %s." % (text, meta), frames


def _video_path(job):
    return next((path for path, kind in job.outputs if kind == "video"), "") if job is not None else ""


class EACHLABS_OT_chat_video_open(bpy.types.Operator):
    bl_idname = "eachlabs.chat_video_open"
    bl_label = "Open Sequencer"
    bl_description = tooltips.TEXTS["video_open"]

    @classmethod
    def poll(cls, context):
        return job_of(("done",)) is not None and context.window is not None

    def execute(self, context):
        job = job_of(("done",))
        scene = bpy.data.scenes.get(job.context.get("sequencer_scene", ""))
        if scene is None:
            self.report({"ERROR"}, "The scene of this video is gone.")
            return {"CANCELLED"}
        camera = scene.objects.get(((job.context.get("shot") or {}).get("request") or {}).get("camera", ""))
        try:
            video_window.open_window(context, scene, "EL %s" % job.job_id, camera)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


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


CLASSES = (EACHLABS_OT_chat_make_video, EACHLABS_OT_chat_video_stop, EACHLABS_OT_chat_video_retry,
           EACHLABS_OT_chat_video_open, EACHLABS_OT_chat_video_file)
