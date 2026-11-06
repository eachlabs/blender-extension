"""The Video tab's card for a video being made, made, failed or stopped: its stage chips, the time and price, one
sentence on the stage and the next, the live line and its buttons. No Blender code."""

import math
import re

from ..shot import models, price
from . import video_texts as V
from .video_line import clock

RUNNING = ("rendering", "photos", "generating")
ORDER = tuple(key for key, _label in V.STAGES)
FREE = ("camera", "keys")  # nothing was sent to each::labs yet in these stages
_LOOK = re.compile(r"(\d+) of (\d+)")


def _info(chat):
    return getattr(chat, "video_info", None) or {}


def _photos_done(chat):
    """``(k, n)`` from the look's ``"k of n"``, or ``None``."""
    found = _LOOK.fullmatch(getattr(chat, "video_message", "") or "")
    return (int(found.group(1)), int(found.group(2))) if found else None


def stage(chat):
    """The stage the video is at, or failed or stopped at: ``camera``, ``keys``, ``look``, ``video``, ``sequencer``."""
    current = getattr(chat, "video_stage", "") or "camera"
    return current if current in ORDER else "camera"


def chips(chat):
    """``{label: chip state}`` of the five stages, in order, for the video's state."""
    video = getattr(chat, "video", "")
    current = ORDER.index(stage(chat))
    mark = {"failed": "failed", "stopped": "cancelled"}.get(video, "active")
    out = {}
    for index, (key, label) in enumerate(V.STAGES):
        if video == "done" or index < current:
            state = "done"
        elif index == current:
            state = mark
        else:
            state = "todo"
        if key == "look" and state == "active":
            done = _photos_done(chat)
            n = done[1] if done else _info(chat).get("photos", 0)
            if n:
                label = "%s %d/%d" % (label, done[0] if done else 0, n)
        out[label] = state
    return out


def _price(chat):
    total = _info(chat).get("price")
    return price.text(total) if isinstance(total, (int, float)) else ""


def meta(chat, now):
    """The card's meta: ``0:41 · $1.45`` while it is made, ``4 min · $1.45`` once made, ``Failed`` or ``Stopped``."""
    video, info = getattr(chat, "video", ""), _info(chat)
    started, ended = info.get("started"), info.get("ended")
    cost = _price(chat)
    if video in RUNNING:
        parts = [clock(now - started) if started is not None else "", cost]
    elif video == "done":
        minutes = max(1, math.ceil(((ended or now) - started) / 60.0)) if started is not None else 0
        parts = ["%d min" % minutes if minutes else "", cost]
    elif video == "failed":
        parts = ["Failed", price.text(0) if stage(chat) in FREE else ""]
    else:
        parts = ["Stopped"]
    return " · ".join(p for p in parts if p)


def sentence(chat):
    """One sentence on the current stage and the next, with its rough time."""
    key = stage(chat)
    if key != "look":
        return V.NOW[key]
    n = _info(chat).get("photos", 0) or (_photos_done(chat) or (0, 1))[1]
    return V.NOW["look"] % (("the key frame", "a photo") if n == 1 else ("the %d key frames" % n, "photos"))


def live(chat):
    """The spinner's line: how far the current stage is."""
    key = stage(chat)
    if key in FREE:
        return V.LIVE[key] % getattr(chat, "video_progress", 0)
    if key == "look":
        done = _photos_done(chat)
        return V.LIVE["look"] % ("%d of %d" % done) if done else V.LIVE["upload"]
    if key == "video":
        return V.LIVE["video"] % (models.VIDEO["label"], clock(getattr(chat, "video_seconds", 0)))
    return V.LIVE["sequencer"]


def failed_text(chat):
    """The failed card's line: what failed and why, and that nothing more was spent when no paid work had started."""
    reason = (getattr(chat, "video_message", "") or "unknown error").strip().rstrip(".")
    reason = reason[:1].lower() + reason[1:]
    text = V.FAILED % (V.FAILED_WHAT[stage(chat)], reason)
    return text + " " + V.NOTHING_MORE if stage(chat) in FREE else text


def apply(s, chat, shot, now):
    """The video's card on ``s``, when the chat has a video; nothing otherwise."""
    video = getattr(chat, "video", "")
    if video not in RUNNING + ("done", "failed", "stopped"):
        return
    s.stages, s.video_meta = chips(chat), meta(chat, now)
    if video in RUNNING:
        s.video_card, s.video_text, s.video_line = "progress", sentence(chat), live(chat)
        if shot.stop_ask:
            s.video_ask = V.STOP_ASK_FREE if stage(chat) in FREE else V.STOP_ASK
            s.actions = ["video_stop_yes", "video_stop_no"]
        else:
            s.actions = ["video_stop"]
    elif video == "done":
        s.video_card, s.video_text = "ready", V.READY % _info(chat).get("seconds", shot.seconds)
        s.actions = ["video_open", "video_file", "video_another"]
    else:
        s.video_card = video
        s.video_error = failed_text(chat) if video == "failed" else V.STOPPED
        s.actions = (["video_retry"] if getattr(chat, "video_job", "") else []) + ["video_edit"]
