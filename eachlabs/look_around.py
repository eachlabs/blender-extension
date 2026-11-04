"""Looking around the scene for the model: four sides of the scene or of one thing, solid or X-ray. Main thread only.

The visual check shows what the scene camera sees; this shows what it does not: the back of a building, a part
hidden inside another, the scene with a blocking thing taken away. Every view uses temporary cameras, never the
scene camera, and objects are hidden from the render for the frames only; everything is put back in a ``finally``.
"""

import base64
import os
import shutil
import tempfile
import time

import bpy
from mathutils import Vector

from . import render_export, visual_check

MODES = ("solid", "xray")
SIZE = (384, 288)  # pixels of each view: four of them cost about one camera frame
HIDE_MAX = 12
_SHADING = visual_check._CLOSE_SETTINGS + (("display.shading", "show_xray"), ("display.shading", "xray_alpha"))
_GEOMETRY = ("MESH", "CURVE", "SURFACE", "FONT", "META")


def _corners(objects):
    return [o.matrix_world @ Vector(c) for o in objects if o.type in _GEOMETRY and not o.hide_render
            for c in o.bound_box]


def render_view(build, target=None, hide=(), mode="solid", frame_on=(), views=visual_check.CLOSE_VIEWS):
    """Render ``target`` (one of the chat's roots and its parts) or everything the chat built, from four sides.

    ``hide``: names of the chat's objects left out of the frames. ``mode``: ``solid`` or ``xray`` (surfaces half
    see-through, to show what lies inside what). ``frame_on``: names of the chat's roots the views are fitted to,
    with everything still shown. ``views``: ``(degrees around, degrees up)`` of each view. Returns
    ``{"images", "views", "seconds"}``, or ``images`` empty with a ``reason``."""
    if render_export.busy() or bpy.app.is_job_running("RENDER"):
        return {"images": [], "reason": "another render is running"}
    if mode not in MODES:
        return {"images": [], "reason": "mode is one of %s" % ", ".join(MODES)}
    scene = build.scene
    if target:
        root = scene.objects.get(target)
        if root is None or not build.owns(root):
            return {"images": [], "reason": "%s is not one of your objects" % target}
        shown = [root] + list(root.children_recursive)
    else:
        shown = list(build.frame_targets())
    gone = set()
    for name in list(hide)[:HIDE_MAX]:
        obj = scene.objects.get(name)
        if obj is not None and build.owns(obj):
            gone.update(o.session_uid for o in [obj] + list(obj.children_recursive))
    corners = _corners([o for o in shown if o.session_uid not in gone])
    roots = [scene.objects.get(name) for name in frame_on]
    picked = [o for r in roots if r is not None and build.owns(r) for o in [r] + list(r.children_recursive)]
    corners = _corners([o for o in picked if o.session_uid not in gone]) or corners
    if not corners:
        return {"images": [], "reason": "nothing to show"}
    current, subframe = scene.frame_current, scene.frame_subframe
    saved = visual_check._snapshot(scene)
    shading = [(p, a, getattr(visual_check._owner(scene, p), a)) for p, a in _SHADING
               if hasattr(visual_check._owner(scene, p), a)]
    kept = {s.session_uid for s in shown}
    hidden = [(o, o.hide_render) for o in scene.objects
              if o.session_uid in gone or (target and o.session_uid not in kept and o.type in _GEOMETRY)]
    folder = tempfile.mkdtemp(prefix="eachlabs-around-")
    cameras, out = [], {"images": [], "views": [], "seconds": []}
    coloured = []
    try:
        coloured = visual_check._true_colours(shown)
        visual_check._lower(scene, folder)
        engines = [e.identifier for e in scene.render.bl_rna.properties["engine"].enum_items]
        if "BLENDER_WORKBENCH" in engines:
            scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x, scene.render.resolution_y = SIZE
        display = scene.display.shading
        display.light, display.color_type = "STUDIO", "MATERIAL"
        display.show_cavity, display.show_shadows, display.show_object_outline = True, mode == "solid", False
        if hasattr(display, "show_xray"):
            display.show_xray = mode == "xray"
            if hasattr(display, "xray_alpha"):
                display.xray_alpha = 0.4
        for obj, _was in hidden:
            obj.hide_render = True
        for turn, up in views:
            cameras.append(visual_check._close_camera(scene, corners, turn, up))
            started = time.monotonic()
            bpy.ops.render.render(write_still=True, scene=scene.name)
            out["seconds"].append(round(time.monotonic() - started, 2))
            with open(scene.render.filepath, "rb") as handle:
                data = handle.read()
            os.remove(scene.render.filepath)
            out["images"].append("data:image/png;base64," + base64.b64encode(data).decode("ascii"))
            out["views"].append("from %d degrees around, %d up" % (turn, up))
        return out
    except (RuntimeError, OSError, ReferenceError) as exc:  # looking is extra: the stage goes on without it
        return {"images": [], "reason": str(exc) or type(exc).__name__}
    finally:
        visual_check._put_colours(coloured)
        for obj, was in hidden:
            try:
                obj.hide_render = was
            except ReferenceError:
                pass
        visual_check._restore(scene, shading)
        visual_check._restore(scene, saved)
        for cam in cameras:
            visual_check._drop(cam)
        scene.frame_set(current, subframe=subframe)
        shutil.rmtree(folder, ignore_errors=True)
