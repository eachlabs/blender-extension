"""Timing a shot video: which frames the clip takes, how long it runs and its size. No ``bpy``."""

import math
from dataclasses import dataclass

from . import models

CLIP_SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (960, 960),
    "4:3": (1104, 828),
    "3:4": (828, 1104),
    "21:9": (1456, 624),
}


@dataclass(frozen=True)
class Plan:
    frame_start: int
    frame_end: int
    hold: int  # Frames the last view is held to fill the clip.
    seconds: int
    too_long: bool  # The move is longer than the longest clip, so only its first part is used.


def plan(move_start, move_end, fps, seconds):
    """The clip for a move. ``seconds=None`` takes the move's length rounded up, within the model's limits."""
    low, high = models.VIDEO["min_seconds"], models.VIDEO["max_seconds"]
    length = move_end - move_start + 1
    wanted = math.ceil(length / fps - 1e-9) if seconds is None else int(seconds)
    clip = max(low, min(high, wanted))
    clip_frames = round(clip * fps)
    frame_end = min(move_end, move_start + clip_frames - 1)
    hold = clip_frames - (frame_end - move_start + 1)
    return Plan(move_start, frame_end, hold, clip, seconds is None and wanted > high)


STILL_SECONDS = 5  # a camera that does not move: the video is a still shot of this length unless the person picks one


def longest(move_start, move_end, fps, moves):
    """The longest video: a move's length rounded up, within the model's limits; any length up to the model's
    limit for a camera that does not move, since there is no move to stay inside."""
    low, high = models.VIDEO["min_seconds"], models.VIDEO["max_seconds"]
    if not moves:
        return high
    return max(low, min(high, math.ceil((move_end - move_start + 1) / fps - 1e-9)))


def default_seconds(move_start, move_end, fps, moves):
    """The duration the dialog starts at: the whole move, or ``STILL_SECONDS`` for a camera that does not move.
    ``plan`` then holds the last frame of a range shorter than that."""
    return longest(move_start, move_end, fps, moves) if moves else STILL_SECONDS


def clip_size(aspect):
    """Width and height of the clip's pictures, inside the video model's pixel limits."""
    return CLIP_SIZES[aspect]
