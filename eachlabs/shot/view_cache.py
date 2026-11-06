"""What the camera sees over its move, measured once per camera, aspect and frame range. Main thread only.

Measuring (``views.collect``) steps through the move's frames, which takes seconds in a big scene, so it never runs on
the bar's draw and never after an edit on its own: the Video tab measures when it opens, when its camera or aspect
changes, and on Send, which measures afresh so the confirmed price is what the scene shows. Between those the price
is the last measure's, marked with ``≈``. A duration only picks again from the measured frames. Opening another file
forgets every measure, since its scenes and cameras may carry the same names."""

import bpy

from .. import timing as scene_timing
from . import keyframes, models, timing, views

KEEP = 8  # measures kept: one per camera and aspect the person tried
BAR_INPUT = "EACHLABS_OT_bar_input"  # the bar's own modal operator, running while it has the keys
_found = {}  # key -> {frame: {thing: share}}
_picks = {}  # (key, plan's first and last frame) -> key frames
_loads = [0]  # bumped when another file opens; part of every key


def _fps(scene):
    return scene_timing.scene_fps(scene.render.fps, scene.render.fps_base)


def move_range(scene):
    """The frames the longest video can use: the frame range, at most ``max_seconds`` of it."""
    longest = round(models.VIDEO["max_seconds"] * _fps(scene))
    return scene.frame_start, min(scene.frame_end, scene.frame_start + longest - 1)


def key(scene, camera, aspect):
    start, end = move_range(scene)
    return scene.name, camera.name, aspect, start, end, round(_fps(scene), 4), _loads[0]


def measured(scene, camera, aspect):
    """True when this camera's view is measured for this frame range in this file."""
    return key(scene, camera, aspect) in _found


def can_measure():
    """False while a modal operator other than the bar's own runs (a grab, a knife, a paint stroke): stepping the
    frames under it would fight it."""
    wm = bpy.context.window_manager
    return not any(op.bl_idname not in (BAR_INPUT, "eachlabs.bar_input")
                   for window in (wm.windows if wm else ()) for op in window.modal_operators)


def measure(scene, camera, aspect):
    """Measure the camera's view over the move now and keep it. Seconds in a big scene: never call it on a draw."""
    start, end = move_range(scene)
    found = views.collect(scene, camera, start, end, size=timing.clip_size(aspect))
    k = key(scene, camera, aspect)
    _found.pop(k, None)
    while len(_found) >= KEEP:
        _found.pop(next(iter(_found)))
    _found[k] = found
    for pick in [p for p in _picks if p[0] == k]:
        del _picks[pick]
    return found


def frames(scene, camera, aspect, plan, fresh=False):
    """The key frames of ``plan`` from the measured view, measured first when ``fresh`` or not measured yet."""
    if fresh or not measured(scene, camera, aspect):
        measure(scene, camera, aspect)
    k = key(scene, camera, aspect)
    pick = (k, plan.frame_start, plan.frame_end)
    if pick not in _picks:
        if len(_picks) > 64:
            _picks.clear()
        _picks[pick] = keyframes.pick_until(_found[k], plan.frame_start, plan.frame_end, models.VIDEO["max_images"])
    return _picks[pick]


def plan_for(scene, seconds):
    return timing.plan(scene.frame_start, scene.frame_end, _fps(scene), seconds)


def photos(scene, camera, aspect, seconds):
    """How many photos a video of ``seconds`` needs by the last measure, or ``None`` before any. Only reads."""
    if not measured(scene, camera, aspect):
        return None
    return len(frames(scene, camera, aspect, plan_for(scene, seconds)))


def forget():
    """Another file opens, or the add-on goes: no measure is kept."""
    _found.clear()
    _picks.clear()
    _loads[0] += 1
