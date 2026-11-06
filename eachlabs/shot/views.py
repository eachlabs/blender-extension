"""Which things the camera shows at each frame of the move, for picking the key frames. Main thread only.

A thing's share at a frame comes from its parts' bounding boxes, projected by ``scene/camera_view.py`` (near-plane
cuts included) and scored by ``keyframes.share``."""

import bpy
from mathutils import Vector

from ..scene import camera_view
from ..scene.common import GEOMETRY
from ..things import registry
from . import keyframes


def things(scene):
    """``{root name: [geometry parts]}`` for every thing of the chat, nested ones too, each with its own parts only.
    A thing with no geometry (an aiming empty) has no box and is left out."""
    objects = list(scene.objects)
    out = {}
    for root in registry.roots(objects).values():
        parts = [o for o in registry.subtree_objects(objects, [root.name], children=False)
                 if o.type in GEOMETRY and not o.hide_render]
        if parts:
            out[root.name] = parts
    return out


def collect(scene, camera, frame_start, frame_end, step=6, size=None):
    """``{frame: {thing: share 0..1}}`` every ``step`` frames and at ``frame_end``; things out of view are left
    out, and so is a thing whose box holds the camera at any of these frames, since it surrounds the camera.
    ``size``: the picture's width and height, when it is not the scene's. The frame and size are put back."""
    found = things(scene)
    frames = list(range(frame_start, frame_end + 1, max(1, step)))
    if frames and frames[-1] != frame_end:
        frames.append(frame_end)
    near = max(getattr(camera.data, "clip_start", 0.01), 1e-4)
    current, subframe = scene.frame_current, scene.frame_subframe
    resolution = scene.render.resolution_x, scene.render.resolution_y
    layer = bpy.context.view_layer if bpy.context.scene == scene else None
    depsgraph = (layer or scene.view_layers[0]).depsgraph
    views = {}
    try:
        if size:
            scene.render.resolution_x, scene.render.resolution_y = size  # the view's shape decides what is in it
        around = set()  # things whose box holds the camera at some frame: rooms, ground blocks, sky domes
        for frame in frames:
            scene.frame_set(frame)
            cam_eval = camera.evaluated_get(depsgraph)
            eye = cam_eval.matrix_world.translation
            around.update(name for name, parts in found.items() if keyframes.surrounds(_corners(parts, depsgraph), eye))
            shares = {name: _share(parts, depsgraph, scene, cam_eval, near) for name, parts in found.items()}
            views[frame] = {name: share for name, share in shares.items() if share > 0.0}
    finally:
        scene.render.resolution_x, scene.render.resolution_y = resolution
        scene.frame_set(current, subframe=subframe)
    return {frame: {name: share for name, share in shown.items() if name not in around}
            for frame, shown in views.items()}


def _corners(parts, depsgraph):
    corners = []
    for obj in parts:
        ev = obj.evaluated_get(depsgraph)
        corners += [tuple(ev.matrix_world @ Vector(c)) for c in ev.bound_box]
    return corners


def _share(parts, depsgraph, scene, cam_eval, near):
    boxes = [box[:4] for box in (camera_view.projected_box(o, depsgraph, scene, cam_eval, near) for o in parts) if box]
    return keyframes.share(boxes)
