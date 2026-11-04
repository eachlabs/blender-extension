"""Simulated mouse and keys on the prompt bar, and what the screen shows."""

import bpy

from tests.gui_check.common import area_of, screenshot, window


# -- prompt bar ---------------------------------------------------------------------------------

MOUSE = [0, 0]


def view3d_region():
    return next(r for r in area_of("VIEW_3D").regions if r.type == "WINDOW")


def placed():
    from eachlabs import overlay

    return overlay._placed.get(view3d_region().as_pointer())


def bar_point(name, dx=0.5, dy=0.5):
    """Window px of a point inside the bar control ``name`` (fractions of its rect)."""
    region = view3d_region()
    origin, frame = placed()[:2]
    x, y, w, h = frame.hits[name]
    fx, fy = x + w * dx, y + h * dy
    return int(region.x + origin[0] + fx), int(region.y + origin[1] + frame.height - fy)


def move(x, y):
    MOUSE[:] = [x, y]
    window().event_simulate("MOUSEMOVE", "NOTHING", x=x, y=y)


def click(x, y):
    move(x, y)
    for value in ("PRESS", "RELEASE"):
        window().event_simulate("LEFTMOUSE", value, x=x, y=y)


def key(kind, char=None, **mods):
    for value in ("PRESS", "RELEASE"):
        window().event_simulate(kind, value, unicode=char if value == "PRESS" else None, x=MOUSE[0], y=MOUSE[1],
                                **mods)


def type_text(text):
    for ch in text:
        key("SPACE" if ch == " " else ch.upper(), ch)


def viewport_centre():
    region = view3d_region()
    return region.x + region.width // 2, region.y + region.height * 2 // 3


def answer_dialog(point, title, accept, shot=None):
    """Click the bar control at ``point``, which asks first; True when its dialog opened with ``title``. Then
    Enter confirms it, or Esc cancels it."""
    from eachlabs import confirm

    before = len(confirm.asked)
    click(*point)
    yield 0.6
    opened = len(confirm.asked) > before and confirm.asked[-1][0] == title
    if shot:
        screenshot(shot)
    key("RET" if accept else "ESC")
    yield 0.8
    return opened


def modal_names():
    return [op.bl_idname for op in window().modal_operators]


def grabbing():
    return any("translate" in n.lower() for n in modal_names())


def shot_pixel(path, x, y):
    import numpy

    image = bpy.data.images.load(path)
    try:
        w, h = image.size
        pixels = numpy.empty(w * h * 4, dtype=numpy.float32)
        image.pixels.foreach_get(pixels)
        i = (y * w + x) * 4
        return tuple(round(float(v) * 255) for v in pixels[i:i + 3])
    finally:
        bpy.data.images.remove(image)


def orange_pixels(path):
    """Orange-looking pixels in the upper part of a screenshot (the prompt bar sits at the bottom)."""
    import numpy

    image = bpy.data.images.load(path)
    try:
        w, h = image.size
        pixels = numpy.empty(w * h * 4, dtype=numpy.float32)
        image.pixels.foreach_get(pixels)
        rows = pixels.reshape(h, w, 4)[h // 3:, :, :3]  # image rows run bottom to top; drop the bottom third
        r, g, b = rows[..., 0], rows[..., 1], rows[..., 2]
        return int(((r > 0.75) & (g > 0.08) & (g < 0.45) & (b < 0.3)).sum())
    finally:
        bpy.data.images.remove(image)


def close(rgb, want, tolerance=14):
    return all(abs(a - b) <= tolerance for a, b in zip(rgb, want))


def kinds():
    """What the chat built, by kind: the buildings are "box", lights "lamp", the camera "camera"."""
    found = set()
    for o in bpy.context.scene.objects:
        if not o.get("eachlabs_id"):
            continue
        if o.type == "CAMERA":
            found.add("camera")
        elif o.type == "LIGHT":
            found.add("lamp")
        elif o.type == "MESH":
            found.add("box" if o.name.startswith("Building") else "ground")
        else:
            found.add(o.type.lower())
    return found


def reveal_cube():
    """Select Blender's startup Cube again, so later checks can use it as the person's object."""
    cube = bpy.data.objects["Cube"]
    cube.hide_set(False)
    cube.hide_render = False
    cube.select_set(True)  # hiding dropped it from the selection
    bpy.context.view_layer.objects.active = cube
    bpy.context.view_layer.update()


def screen_point(location):
    """Window px of a 3D point in the 3D view, or None when it is behind the view."""
    from bpy_extras import view3d_utils

    region = view3d_region()
    point = view3d_utils.location_3d_to_region_2d(region, area_of("VIEW_3D").spaces.active.region_3d, location)
    return None if point is None else (int(region.x + point.x), int(region.y + point.y))


def framed_on(objects):
    """The view is centred on the objects' bounding box and its centre is inside the view."""
    from mathutils import Vector

    corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    centre = Vector([(min(c[i] for c in corners) + max(c[i] for c in corners)) / 2 for i in range(3)])
    rv3d = area_of("VIEW_3D").spaces.active.region_3d
    region, point = view3d_region(), screen_point(centre)
    inside = point is not None and region.x <= point[0] < region.x + region.width \
        and region.y <= point[1] < region.y + region.height
    return (rv3d.view_location - centre).length < 0.01 and inside, "%s vs %s" % (tuple(rv3d.view_location),
                                                                                tuple(centre))
