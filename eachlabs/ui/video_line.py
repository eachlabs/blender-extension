"""The shot video on the bar: its line, its part of the folded line and its pills, on the done card and, through
``attach``, in every other state. No Blender code."""

from . import tokens as T


def clock(seconds):
    seconds = int(max(0, seconds))
    return "%d:%02d" % divmod(seconds, 60)


def video_line(chat):
    """The bar's line about the shot video, or ``""`` when there is none."""
    video = getattr(chat, "video", "")
    message = getattr(chat, "video_message", "")
    if video == "rendering":
        return T.VIDEO_RENDERING % getattr(chat, "video_progress", 0)
    if video == "photos":
        return T.VIDEO_PHOTOS % message if message else T.VIDEO_UPLOADING
    if video == "generating":
        from ..shot import models

        return T.VIDEO_GENERATING % (models.VIDEO["label"], clock(getattr(chat, "video_seconds", 0)))
    if video == "done":
        return T.VIDEO_DONE
    if video == "failed":
        return T.VIDEO_FAILED % (message or "unknown error")
    if video == "stopped":
        return T.VIDEO_STOPPED
    return ""


RUNNING_ACTIONS = ("video_stop", "video_open", "video_file")  # what a chat run leaves usable: no new renders


def attach(s, chat):
    """Show the video on a bar state the done card did not already fill: while a chat run goes, its line on the
    status line (or under the plan) with Stop, or Open Sequencer and Show file, first; otherwise its line in the
    note with its pills after the state's own. Every state with a video keeps a next step for it."""
    line = video_line(chat)
    if s.video or not line:
        return
    s.video, s.video_tag = getattr(chat, "video", ""), video_tag(chat)
    if chat.running:
        if s.video in ("failed", "stopped"):  # no Retry under a chat run: say when it comes back
            line += T.VIDEO_RETRY_LATER
        if s.mode == "plan":
            s.plan_note = "\n".join(t for t in (s.plan_note or T.PLAN_HINT, line) if t)
        else:
            s.objects = list(s.objects) + [line]
        s.actions = [a for a in video_actions(chat) if a in RUNNING_ACTIONS] + list(s.actions)
        return
    s.note = "\n".join(t for t in (s.note, line) if t)
    s.actions = list(s.actions) + [a for a in video_actions(chat) if a not in s.actions]


def video_tag(chat):
    """The video's part of the folded line, or ``""``; a failed video keeps the card open instead."""
    video = getattr(chat, "video", "")
    tag = T.VIDEO_FOLDED.get(video, "")
    if video == "rendering":
        return tag % getattr(chat, "video_progress", 0)
    if video == "photos":
        message = getattr(chat, "video_message", "")
        return tag % message if message else tag.replace(" %s", "")
    if video == "generating":
        return tag % clock(getattr(chat, "video_seconds", 0))
    return tag


def video_actions(chat):
    """The video's pills outside the Video tab: Stop while it is made; Retry after a failed or stopped one; Open
    Sequencer and Show file after one. A new video starts on the Video tab."""
    video = getattr(chat, "video", "")
    if video in ("rendering", "photos", "generating"):
        return ["video_stop"]  # one video at a time
    if video in ("failed", "stopped"):
        return ["video_retry"] if getattr(chat, "video_job", "") else []
    if video == "done":
        return ["video_open", "video_file"]
    return []
