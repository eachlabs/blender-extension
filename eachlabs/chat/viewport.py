"""The 3D viewport around a run: Material Preview, framing the result and showing the camera's path."""

import bpy
import math
import traceback
from mathutils import Vector

from .. import viewport_marks
from . import undo_watch


FRAME_MARGIN = 1.15  # framed objects fill this much less than the view



def _collection_alive(build):
    """A cheap check, run on every redraw, that the run's collection still exists."""
    name = build.collection_name

    def alive():
        coll = bpy.data.collections.get(name)
        return coll is not None and build._mine(coll)
    return alive



def _show_camera_path(build):
    """Show the scene camera's move while it is the run's keyed camera, and clear it once it is not; returns
    whether the drawn path changed."""
    try:
        path, look_at = build.camera_path(), build.camera_look_at()
        if not path:
            look_at = None
        if path == viewport_marks.camera_path() and look_at == viewport_marks.camera_target():
            return False
        viewport_marks.set_camera_path(path, look_at, _collection_alive(build) if path else None)
        return True
    except Exception:  # The path is decoration.
        traceback.print_exc()
    return False



def _area(pointer):
    """The 3D view area with this pointer in any window, else the first 3D view, else ``None``."""
    wm = bpy.context.window_manager
    areas = [a for w in (wm.windows if wm else ()) for a in w.screen.areas if a.type == "VIEW_3D"]
    return next((a for a in areas if a.as_pointer() == pointer), areas[0] if areas else None)



def material_preview(window_pointer, area_pointer=None):
    """Switch the 3D views of the run's window from Solid to Material Preview, so emission and lights
    show. Other shading types (Rendered, Wireframe, Material Preview) stay, and so does Solid when the
    render engine has no Material Preview (Workbench). Returns the views switched."""
    wm = bpy.context.window_manager
    windows = list(wm.windows) if wm else []
    window = next((w for w in windows if w.as_pointer() == window_pointer), None)
    if window is None and area_pointer is not None:
        window = next((w for w in windows if any(a.as_pointer() == area_pointer for a in w.screen.areas)), None)
    if window is None:
        return 0
    switched = 0
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        shading = area.spaces.active.shading
        if shading.type != "SOLID":
            continue
        try:
            shading.type = "MATERIAL"
        except TypeError:  # the render engine offers no Material Preview (Workbench)
            continue
        area.tag_redraw()
        switched += 1
    return switched



def frame_build(build, area, keep_camera_view=False):
    """Centre the 3D view on the run's buildings and lamps and zoom to fit them. The view keeps its
    rotation; the selection and the active object are not touched. Returns whether it framed."""
    if area is None:
        return False
    return frame_objects(build.frame_targets(), area, keep_camera_view)



def frame_objects(objects, area, keep_camera_view=False):
    """Centre the 3D view on ``objects`` and zoom to fit them, keeping its rotation; returns whether it framed."""
    if area is None or not objects:
        return False
    space = area.spaces.active
    rv3d = space.region_3d
    if rv3d.view_perspective == "CAMERA":
        if keep_camera_view:
            return False
        rv3d.view_perspective = "PERSP"
    corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    low = Vector([min(c[i] for c in corners) for i in range(3)])
    high = Vector([max(c[i] for c in corners) for i in range(3)])
    centre = (low + high) / 2
    radius = max(max((c - centre).length for c in corners), 1.0)
    half_fov = math.atan(18.0 / space.lens)  # the viewport's lens is on a 36 mm sensor
    rv3d.view_location = centre
    rv3d.view_distance = radius * FRAME_MARGIN / math.sin(half_fov)
    if rv3d.view_distance * 2 > space.clip_end:
        space.clip_end = rv3d.view_distance * 2
    area.tag_redraw()
    undo_watch._quiet()
    return True



def _view3d(context):
    screen = getattr(context, "screen", None)
    return next((a for a in screen.areas if a.type == "VIEW_3D"), None) if screen else None
