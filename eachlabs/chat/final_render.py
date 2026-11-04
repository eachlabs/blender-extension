"""Final render: the scene camera rendered once with Cycles (bounced light, denoised, depth of field on the
subject) and saved next to the .blend. The chat's previews stay EEVEE; this changes the scene's render settings
only while it renders and puts them back after. An animation renders its last frame as a still."""

import os
import time

import bpy
from mathutils import Vector

from .. import plan3d
from ..ui import tooltips
from . import final_settings
from .live import chat_run

_RUN = {}  # the render under way: scene name, saved settings, path, start time; empty when none
_TIMERS = []


def _subject(build, scene):
    """The root of the scene's first planned subject that exists, or ``None``."""
    roots = [o for o in scene.objects if build.owns(o) and o.parent is None]
    for name in getattr(build, "subjects", ()) or ():
        words = set(plan3d.name_words(name))
        for root in roots:
            if words and words <= set(plan3d.name_words(root.name)):
                return root
    return None


def _size(obj):
    """The biggest side in metres of ``obj`` with everything under it."""
    points = []
    for part in [obj] + list(obj.children_recursive):
        if part.type == "MESH":
            points += [part.matrix_world @ Vector(c) for c in part.bound_box]
    if not points:
        return 1.0
    return max(max(p[i] for p in points) - min(p[i] for p in points) for i in range(3))


def _apply(scene, subject):
    """Switch ``scene`` to the final settings; returns what to put back."""
    cycles, cam = scene.cycles, scene.camera.data
    saved = {"engine": scene.render.engine, "frame": scene.frame_current,
             "cycles": {k: getattr(cycles, k) for k in ("samples", "use_adaptive_sampling", "adaptive_threshold",
                                                        "use_denoising", "max_bounces", "device")},
             "dof": (cam.dof.use_dof, cam.dof.focus_object, cam.dof.aperture_fstop)}
    scene.render.engine = "CYCLES"
    cycles.samples, cycles.use_adaptive_sampling = final_settings.SAMPLES, True
    cycles.adaptive_threshold, cycles.use_denoising = final_settings.NOISE, True
    cycles.max_bounces = max(cycles.max_bounces, final_settings.BOUNCES)
    try:
        if bpy.context.preferences.addons["cycles"].preferences.has_active_device():
            cycles.device = "GPU"
    except (KeyError, AttributeError):
        pass
    if subject is not None and not cam.dof.use_dof:  # the model's own focus stays
        cam.dof.use_dof, cam.dof.focus_object = True, subject
        cam.dof.aperture_fstop = final_settings.fstop(_size(subject))
    scene.frame_set(scene.frame_end)  # an animation: its last frame, where the move ends
    return saved


def _restore(scene, saved):
    cam = scene.camera.data if scene.camera is not None else None
    scene.render.engine = saved["engine"]
    for key, value in saved["cycles"].items():
        try:
            setattr(scene.cycles, key, value)
        except (TypeError, ValueError):
            pass
    if cam is not None:
        cam.dof.use_dof, cam.dof.focus_object, cam.dof.aperture_fstop = saved["dof"]
    scene.frame_set(saved["frame"])


def _redraw():
    from .. import main_thread

    main_thread.tag_redraw()


def _end(state, error=""):
    """Main thread: save the picture (``state`` "saved") or not, put the settings back, and tell the bar."""
    run = dict(_RUN)
    _RUN.clear()
    for handlers, fn in ((bpy.app.handlers.render_complete, _completed), (bpy.app.handlers.render_cancel, _cancelled)):
        if fn in handlers:
            handlers.remove(fn)
    scene = bpy.data.scenes.get(run.get("scene", ""))
    STATE = chat_run.STATE
    if state == "saved":
        try:
            image = bpy.data.images["Render Result"]
            image.save_render(run["path"], scene=scene)
        except (KeyError, RuntimeError) as exc:
            state, error = "failed", str(exc) or type(exc).__name__
    if scene is not None and "saved" in run:
        _restore(scene, run["saved"])
    STATE.final_render, STATE.final_error = state, error
    STATE.final_path = run.get("path", "") if state == "saved" else ""
    STATE.final_seconds = time.monotonic() - run.get("started", time.monotonic())
    _redraw()
    return None


def _later(state):
    """Render handlers may run off the main thread: the work goes through a timer."""
    def fire():
        _end(state)
        return None
    bpy.app.timers.register(fire, first_interval=0.05)


def _completed(*_args):
    if _RUN:
        _later("saved")


def _cancelled(*_args):
    if _RUN:
        _later("cancelled")


def start(context):
    """Start the Final render of the chat's scene. In the interface the render runs as Blender's own render job,
    with its window, progress and Esc; in background mode it renders at once."""
    build = chat_run._build
    scene = build.scene
    if scene.camera is None:
        raise RuntimeError("The scene has no camera to render from.")
    from .. import preferences

    folder = preferences.user_folder("renders")
    path = final_settings.output_path(bpy.data.filepath, folder, os.path.exists)
    _RUN.update(scene=scene.name, path=path, started=time.monotonic())
    _RUN["saved"] = _apply(scene, _subject(build, scene))
    chat_run.STATE.final_render, chat_run.STATE.final_error, chat_run.STATE.final_path = "rendering", "", ""
    if bpy.app.background:
        try:
            bpy.ops.render.render(scene=scene.name)
        except RuntimeError as exc:
            _end("failed", str(exc))
            raise
        _end("saved")
        return
    bpy.app.handlers.render_complete.append(_completed)
    bpy.app.handlers.render_cancel.append(_cancelled)
    try:
        bpy.ops.render.render("INVOKE_DEFAULT", scene=scene.name)
    except RuntimeError as exc:
        _end("failed", str(exc))
        raise
    _redraw()


class EACHLABS_OT_chat_final_render(bpy.types.Operator):
    bl_idname = "eachlabs.chat_final_render"
    bl_label = "Final render"
    bl_description = tooltips.TEXTS["final"]

    @classmethod
    def poll(cls, context):
        return chat_run._build is not None and not chat_run.STATE.running and not _RUN

    def execute(self, context):
        try:
            start(context)
        except (RuntimeError, ReferenceError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (EACHLABS_OT_chat_final_render,)
