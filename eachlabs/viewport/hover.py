"""Tooltips on the bar: which control the mouse rests on, the wait before its tooltip shows, and the card in the 3D
view. The texts are in ``ui/tooltips.py``, the card's layout and pixels in ``ui/tooltip_card.py``."""

import bpy

from . import draw, live
from ..ui import tooltip_card, tooltips, tokens as T

_CACHE_MAX = 16  # cards kept as textures


def track(region, name):
    """The mouse is over control ``name`` of the bar in ``region`` (``None``: over no control). A tooltip that was
    showing goes at once; the new one shows after ``TIP_DELAY``. Redraws only when a shown tooltip goes."""
    ui = live.overlay.UI
    key = (region.as_pointer(), name) if region is not None and name and tooltips.text(name) else None
    if key == ui["hover"]:
        return
    shown = ui["tip"]
    ui["hover"], ui["tip"] = key, False
    if key is not None and key != ui["tip_quiet"]:
        ui["tip_quiet"] = None  # another control: its tooltip may show
    if shown:
        draw.tag_redraw()
    if bpy.app.timers.is_registered(_due):
        bpy.app.timers.unregister(_due)
    if key is not None and key != ui["tip_quiet"]:
        bpy.app.timers.register(_due, first_interval=T.TIP_DELAY)


def track_event(context, event):
    """A mouse move the input operator saw (the bar has the keys): the control under it in any 3D view."""
    from . import input as bar_input  # it calls this module

    screen = context.window.screen if context.window else None
    for area in screen.areas if screen else ():
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type == "WINDOW" and bar_input._inside(region, event.mouse_x, event.mouse_y):
                target = bar_input._target_at(area, region, event.mouse_x, event.mouse_y)
                track(region, target[0] if target else None)
                return
    track(None, None)


def _due():
    ui = live.overlay.UI
    if ui["hover"] is not None and ui["hover"] != ui["tip_quiet"]:
        ui["tip"] = True
        draw.tag_redraw()
    return None


def clicked():
    """A click hides the tooltip until the mouse moves to another control."""
    ui = live.overlay.UI
    if ui["tip"]:
        draw.tag_redraw()
    ui["tip"], ui["tip_quiet"] = False, ui["hover"]


def left(region, highlighted):
    """The bar's region redraws and its gizmo is not highlighted while the bar has no keys: the mouse left the
    region, so its tooltip goes."""
    ui = live.overlay.UI
    if ui["focused"] or ui["pressed"]:  # the input operator tracks the mouse; a held press is no leaving
        return
    if not highlighted and ui["hover"] is not None and ui["hover"][0] == region.as_pointer():
        track(None, None)


def stop():
    if bpy.app.timers.is_registered(_due):
        bpy.app.timers.unregister(_due)
    live.overlay.UI["hover"], live.overlay.UI["tip"] = None, False


def draw_tip(region, origin, frame, scale, left_px=0, right_px=0):
    """After the bar in ``region``: the tooltip card over its control, while one shows there and no menu is open."""
    ui = live.overlay.UI
    ptr = region.as_pointer()
    live.overlay._tip_placed.pop(ptr, None)
    hover = ui["hover"]
    if not ui["tip"] or hover is None or hover[0] != ptr or ui["quality_menu"] or ui["camera_menu"]:
        return
    rect = frame.hits.get(hover[1])
    text = tooltips.text(hover[1])
    if rect is None or not text:
        return
    cache = live.overlay._tip_cache
    if (text, scale) not in cache:
        if len(cache) >= _CACHE_MAX:
            cache.clear()
        card = tooltip_card.render(text, scale)
        cache[(text, scale)] = (card, draw._texture(card))
    card, texture = cache[(text, scale)]
    hx, hy, hw, hh = rect
    control = (origin[0] + hx, origin[1] + frame.height - hy - hh, hw, hh)
    x, y = tooltip_card.place((card.width, card.height), control, (region.width, region.height), scale, left_px,
                              right_px)
    live.overlay._tip_placed[ptr] = (x, y, card.width, card.height)
    draw._quad(texture, x, y, card.width, card.height)
