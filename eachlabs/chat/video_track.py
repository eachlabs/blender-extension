"""What the bar shows about the shot video: its job's state copied into ``ChatState`` on every main-thread tick;
and when the video's window stops playing. No ``bpy``."""

import os
import re

from .. import jobs

GONE = "the add-on no longer follows this video; make it again"
_LOOK = re.compile(r"Making the look \((\d+ of \d+)\)")
_RUNNING = ("rendering", "photos", "generating")


def follow(chat, registry, now):
    """Copy the video's job from ``registry`` into ``chat``; True when the bar's video line changed, so it redraws.
    A new chat run leaves these fields alone, so the line follows the video while the chat moves on."""
    if not chat.video_job:
        return False
    before = _shown(chat)
    job = registry.get(chat.video_job)
    rendering = job is not None and job.state == jobs.RENDERING
    copy(chat, job, now, render_progress(job.context.get("shot") or {}) if rendering else 0)
    return _shown(chat) != before


def forget(chat):
    """Clear the video from ``chat``: another file was opened, so its scene and camera are gone."""
    chat.video, chat.video_job, chat.video_message = "", "", ""
    chat.video_seconds, chat.video_progress, chat.video_since = 0, 0, 0.0
    chat.video_stage, chat.video_info, chat.video_camera = "", {}, ""


def _shown(chat):
    return chat.video, chat.video_job, chat.video_message, chat.video_progress, chat.video_seconds, chat.video_stage


def stage_of(state, message):
    """The Video tab's stage for a job's state and message, or ``""`` for a finished job: the stage it reached
    stays. Renders: the camera move, then the key frames; uploads and photos: the look; then the video model, then
    the import into the Sequencer."""
    if state == jobs.RENDERING:
        return "keys" if (message or "").startswith("Rendering the key frames") else "camera"
    if state == jobs.UPLOADING or (state == jobs.RUNNING and _LOOK.match(message or "")):
        return "look"
    if state == jobs.IMPORTING:
        return "sequencer"
    if state in (jobs.SUBMITTING, jobs.QUEUED, jobs.RUNNING, jobs.DOWNLOADING):
        return "video"
    return ""


def render_progress(shot):
    """Percent of the shot's renders on disk: the clay clip's frames, then the key frames."""
    def count(folder):
        try:
            return len(os.listdir(folder)) if folder and os.path.isdir(folder) else 0
        except OSError:
            return 0

    clip = shot.get("clip", "")
    return progress(shot.get("frames", 0), count(os.path.splitext(clip)[0] + "_frames"),
                    bool(clip) and os.path.isfile(clip), len(shot.get("times", [])), count(shot.get("keys", "")))


def copy(chat, job, now, progress=0):
    """Set ``chat.video`` and its line's numbers from ``job`` (``None``: the job is no longer in the registry).
    ``progress``: percent of the renders written, while it renders."""
    if job is None:
        if chat.video in _RUNNING:
            chat.video, chat.video_message, chat.video_job = "failed", GONE, ""
        elif chat.video == "done":
            chat.video, chat.video_job = "", ""
        return
    before = chat.video
    chat.video_stage = stage_of(job.state, job.message) or chat.video_stage
    chat.video_message = ""
    if job.state == jobs.RENDERING:
        chat.video, chat.video_progress = "rendering", int(progress)
    elif job.state == jobs.UPLOADING:
        chat.video = "photos"
    elif job.state == jobs.RUNNING and _LOOK.match(job.message or ""):
        chat.video, chat.video_message = "photos", _LOOK.match(job.message).group(1)
    elif job.state == jobs.DONE:
        chat.video = "done"
    elif job.state == jobs.FAILED:
        chat.video, chat.video_message = "failed", (job.error or "unknown error").strip().rstrip(".")
    elif job.state == jobs.CANCELLED:
        chat.video = "stopped"
    else:  # submitted, running, downloading, importing: the video model has it
        chat.video = "generating"
    if chat.video == "generating" and before != "generating":
        chat.video_since = now
    if chat.video == "generating":
        chat.video_seconds = int(max(0.0, now - chat.video_since))
    if chat.video in ("done", "failed", "stopped") and before != chat.video and chat.video_info:
        chat.video_info = dict(chat.video_info, ended=now)


def progress(clip_frames, clip_written, clip_done, keys, keys_written):
    """Percent of the renders done: the clay clip's frames, then the key frames."""
    total = clip_frames + keys
    if total <= 0:
        return 0
    done = (clip_frames if clip_done else min(clip_written, clip_frames)) + min(keys_written, keys)
    return 100 * done // total


def stop_frame(strip_end, frame_end):
    """The frame the video's window stops at: the strip's last (``strip_end`` is exclusive), or the scene's last
    when the strip runs past it, since playback wraps there."""
    return min(strip_end - 1, frame_end)


def ends(frame, last, end):
    """True when playback at ``frame`` is over: it reached ``end``, or it went back from ``last`` (a wrap)."""
    return frame >= end or frame < last
