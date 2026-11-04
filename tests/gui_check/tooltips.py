"""Tooltips on the bar's controls."""

from tests.gui_check.bar_input import bar_point, click, move, placed, view3d_region, viewport_centre
from tests.gui_check.common import check, screenshot


def tooltip_checks():
    """Resting on a control shows its tooltip above it; moving away or a click hides it."""
    from eachlabs import overlay

    region = view3d_region()
    ptr = region.as_pointer()
    move(*bar_point("tab_character"))
    yield 0.8
    tip = overlay._tip_placed.get(ptr)
    origin, frame = placed()[:2]
    _hx, hy, _hw, _hh = frame.hits["tab_character"]
    control_top = origin[1] + frame.height - hy
    check("tooltips: resting on a tab for 0.8 s shows its tooltip above it, inside the 3D view",
          overlay.UI["tip"] and overlay.UI["hover"] == (ptr, "tab_character") and tip is not None
          and tip[1] >= control_top and tip[0] >= 0 and tip[0] + tip[2] <= region.width
          and tip[1] + tip[3] <= region.height, "%s %s %s %d" % (overlay.UI["hover"], overlay.UI["tip"], tip,
                                                                   control_top))
    overlay.tag_redraw()  # the screenshot reads the last frame shown: one more draw puts the card in it
    yield 0.3
    screenshot("bar-07-tooltip.png")
    move(*viewport_centre())
    yield 0.4
    check("tooltips: moving the mouse off the control hides its tooltip",
          not overlay.UI["tip"] and overlay._tip_placed.get(ptr) is None, "%s %s" % (overlay.UI["hover"],
                                                                                   overlay._tip_placed.get(ptr)))
    move(*bar_point("tab_scene"))
    yield 0.8
    shown = overlay.UI["tip"]
    click(*bar_point("tab_scene"))
    yield 0.8
    check("tooltips: a click hides the tooltip and it stays hidden over the same control",
          shown and not overlay.UI["tip"] and overlay._tip_placed.get(ptr) is None, "%s %s" % (shown,
                                                                                            overlay.UI["tip"]))
