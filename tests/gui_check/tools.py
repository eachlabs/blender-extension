"""Presses on the bar never reach the active tool."""

import bpy

from tests.gui_check.bar_input import bar_point, key, modal_names, move, view3d_region, viewport_centre
from tests.gui_check.common import area_of, check, override, window


def set_tool(idname):
    with override():
        bpy.ops.wm.tool_set_by_id(name=idname)


def press(x, y, button="LEFTMOUSE"):
    """Press and release at (x, y); returns the modal operators running while the button was down."""
    move(x, y)
    yield 0.2
    window().event_simulate(button, "PRESS", x=x, y=y)
    yield 0.2
    held = modal_names()
    window().event_simulate(button, "RELEASE", x=x, y=y)
    yield 0.3
    return held


def tool_presses():
    """Presses on the bar never reach the active tool; presses off it still do."""
    from eachlabs import overlay

    cursor = bpy.context.scene.cursor
    set_tool("builtin.cursor")
    yield 0.3
    cursor.location = (0, 0, 0)
    held = yield from press(*bar_point("field"))
    check("bar: with the 3D Cursor tool, a click on the bar focuses it and the cursor stays",
          overlay.UI["focused"] and tuple(cursor.location) == (0, 0, 0),
          "%s %s %s" % (overlay.UI["focused"], tuple(cursor.location), held))
    key("ESC")
    yield 0.3
    yield from press(*viewport_centre())
    check("bar: with the 3D Cursor tool, a click off the bar still places the cursor",
          tuple(cursor.location) != (0, 0, 0) and not overlay.UI["focused"], str(tuple(cursor.location)))
    set_tool("builtin.annotate")
    yield 0.3
    held = yield from press(*bar_point("field"))
    check("bar: with the Annotate tool, a click on the bar focuses it and draws nothing",
          overlay.UI["focused"] and not any("annotate" in n.lower() for n in held), str(held))
    key("ESC")
    yield 0.3
    set_tool("builtin.select_box")
    yield 0.3
    for button in ("RIGHTMOUSE", "MIDDLEMOUSE"):
        held = yield from press(*bar_point("bar", 0.5, 0.15), button=button)
        yield 0.2
        check("bar: a %s press on the bar does not reach Blender" % button.lower().replace("mouse", ""),
              held == ["GIZMOGROUP_OT_gizmo_tweak"] and not overlay.UI["focused"], str(held))
        key("ESC")  # closes a context menu if one opened anyway
        yield 0.2

    cube = bpy.data.objects["Cube"]
    before = [tuple(v.co) for v in cube.data.vertices]
    with override():
        bpy.context.view_layer.objects.active = cube
        bpy.ops.object.mode_set(mode="SCULPT")
    yield 1.0
    overlay.tag_redraw()
    yield 0.4
    held = yield from press(*bar_point("field"))
    focused = overlay.UI["focused"]
    key("ESC")
    yield 0.3
    shelf = overlay.bottom_inset(area_of("VIEW_3D"), view3d_region())
    with override():
        bpy.ops.object.mode_set(mode="OBJECT")
    yield 0.4
    check("bar: in Sculpt mode a click on the bar focuses it and no brush stroke starts",
          focused and not any("brush_stroke" in n.lower() for n in held)
          and [tuple(v.co) for v in cube.data.vertices] == before, "%s %s shelf %d px" % (focused, held, shelf))
    cube.select_set(True)
    yield 0.2
