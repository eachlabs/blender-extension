"""Play through a camera: the 3D view looks through the chosen camera while the animation plays, and the view and
the scene camera are put back when it stops, by Pause or any other way (Esc, Space, the timeline)."""

import bpy
import traceback
from bpy.app.handlers import persistent

from .. import compat, main_thread
from . import play_cameras, undo_watch
from .live import chat_run

TRANSFORM = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")


def _cameras(scene):
    return [o for o in scene.objects if o.type == "CAMERA"]


def _curves(obj):
    """``[(frame, value), ...]`` per transform channel of the object and of its parents."""
    curves = []
    while obj is not None:
        for fc in compat.object_fcurves(obj):
            if fc.data_path in TRANSFORM:
                curves.append([(kp.co[0], kp.co[1]) for kp in fc.keyframe_points])
        obj = obj.parent
    return curves


def chat_camera(scene):
    """The camera the chat built in this scene: the scene camera when it is the chat's, else another of its
    cameras; ``""`` when it has none."""
    build = chat_run._build
    if build is None:
        return ""
    try:
        if build.scene != scene:
            return ""
        cam = scene.camera
        if cam is not None and cam.type == "CAMERA" and build._mine(cam):
            return cam.name
        return next((o.name for o in _cameras(scene) if build._mine(o)), "")
    except (RuntimeError, ReferenceError):  # the run's scene is gone
        return ""


def menu(scene):
    """``(name, hint, chosen)`` per camera of the scene, the chat's own first (``play_cameras.menu``)."""
    cameras = {o.name: _curves(o) for o in _cameras(scene)}
    if not cameras:
        return []
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    scene_cam = scene.camera.name if scene.camera is not None else ""
    return play_cameras.menu(cameras, chat_run.STATE.play_camera, chat_camera(scene), scene_cam,
                             (scene.frame_start, scene.frame_end), fps)


def chosen(scene):
    """The camera Play looks through, or ``""`` for a scene without one."""
    names = [o.name for o in _cameras(scene)]
    scene_cam = scene.camera.name if scene.camera is not None else ""
    return play_cameras.chosen(names, chat_run.STATE.play_camera, chat_camera(scene), scene_cam)


def is_playing(context=None):
    wm = (context or bpy.context).window_manager
    return any(w.screen.is_animation_playing for w in (wm.windows if wm else ()))


def _view_area(context):
    area = getattr(context, "area", None)
    if area is not None and area.type == "VIEW_3D":
        return area
    screen = getattr(context, "screen", None)
    return next((a for a in screen.areas if a.type == "VIEW_3D"), None) if screen else None


def _region_3d(area):
    return area.spaces.active.region_3d if area is not None else None


def _play_op(context, area):
    """Start playback, in the 3D view's area when there is one."""
    region = next((r for r in area.regions if r.type == "WINDOW"), None) if area is not None else None
    if region is not None and getattr(context, "window", None) is not None:
        with context.temp_override(area=area, region=region):
            bpy.ops.screen.animation_play()
    else:
        bpy.ops.screen.animation_play()


def _cancel_op(context):
    bpy.ops.screen.animation_cancel(restore_frame=False)


def play(context, name, region_3d=None):
    """Look through camera ``name`` in the 3D view and play; the view and the scene camera are kept to put back.
    Without that camera (a scene with none), play as Blender does. ``region_3d`` stands in for the view's."""
    scene = context.scene
    cam = scene.objects.get(name) if name else None
    area = _view_area(context)
    if cam is not None and cam.type == "CAMERA":
        rv3d = region_3d if region_3d is not None else _region_3d(area)
        if not chat_run._play_saved:  # a second Play before the first was put back keeps the first's view
            chat_run._play_saved.update(
                scene=scene.name, camera=scene.camera.name if scene.camera is not None else None,
                area=area.as_pointer() if area is not None and region_3d is None else None,
                view=_view(rv3d) if rv3d is not None else None, rv3d=region_3d)
        scene.camera = cam
        if rv3d is not None:
            rv3d.view_perspective = "CAMERA"
        undo_watch._settle()
    try:
        _play_op(context, area)
    except RuntimeError:
        restore()
        raise
    main_thread.tag_redraw()


def pause(context):
    """Stop playback where it is; the view and the scene camera go back (``restore``)."""
    if is_playing(context):
        _cancel_op(context)
    restore()


def _view(rv3d):
    return {"view_perspective": rv3d.view_perspective, "view_location": rv3d.view_location.copy(),
            "view_rotation": rv3d.view_rotation.copy(), "view_distance": rv3d.view_distance,
            "view_camera_zoom": rv3d.view_camera_zoom, "view_camera_offset": tuple(rv3d.view_camera_offset)}


def _saved_region_3d(saved):
    if saved.get("rv3d") is not None:
        return saved["rv3d"]
    pointer = saved.get("area")
    wm = bpy.context.window_manager
    for window in wm.windows if wm and pointer else ():
        for area in window.screen.areas:
            if area.as_pointer() == pointer:
                area.tag_redraw()
                return _region_3d(area)
    return None


def restore():
    """Put back the view and the scene camera Play changed; nothing when nothing is saved. Returns whether it did."""
    if not chat_run._play_saved:
        return False
    saved = dict(chat_run._play_saved)
    chat_run._play_saved.clear()
    rv3d = _saved_region_3d(saved)
    scene = bpy.data.scenes.get(saved["scene"])
    if scene is not None:
        cam = bpy.data.objects.get(saved["camera"]) if saved["camera"] else None
        if cam is None or scene.objects.get(cam.name) is not None:  # a camera removed meanwhile is not put back
            scene.camera = cam
    if rv3d is not None and saved["view"] is not None:
        for key, value in saved["view"].items():
            if key != "view_perspective":
                setattr(rv3d, key, value)
        rv3d.view_perspective = saved["view"]["view_perspective"]
    undo_watch._settle()
    main_thread.tag_redraw()
    return True


@persistent
def _on_play(*_args):
    main_thread.tag_redraw()  # the bar reads Pause


@persistent
def _on_stop(*_args):
    try:
        restore()
    except Exception:  # Putting the view back must never break playback.
        traceback.print_exc()
    main_thread.tag_redraw()


@persistent
def _on_load(*_args):
    chat_run._play_saved.clear()  # the saved view belongs to the closed file's screen


_HANDLERS = (("animation_playback_pre", _on_play), ("animation_playback_post", _on_stop), ("load_pre", _on_load))


def register():
    for name, func in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if func not in handlers:
            handlers.append(func)


def unregister():
    for name, func in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if func in handlers:
            handlers.remove(func)
