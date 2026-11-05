"""Folding the done card: when the run ended, when the mouse left the bar, and one redraw when the card is due
to fold. The rule is ``bar_state.folded``; the folded line is drawn by ``ui/status_rows.py``."""

import time

import bpy

from . import draw, live
from ..ui import bar_state, tokens as T


def over(on):
    """The mouse is on the bar (``on``) or off it. On it opens the card at once; off it folds after a while."""
    ui = live.overlay.UI
    if on == ui["over_bar"]:
        return
    ui["over_bar"] = on
    if on:
        draw.tag_redraw()
    else:
        ui["left_at"] = time.monotonic()
        _later()


def folded(state, now):
    """True when ``state``'s done card shows as one line now. Notes when a foldable card first shows."""
    ui = live.overlay.UI
    if not bar_state.foldable(state):
        ui["done_since"] = None
        return False
    if ui["done_since"] is None:
        ui["done_since"] = now
        _later()
    return bar_state.folded(ui["done_since"], ui["left_at"], ui["over_bar"], now)


def _later():
    if bpy.app.timers.is_registered(_due):
        bpy.app.timers.unregister(_due)
    bpy.app.timers.register(_due, first_interval=T.FOLD_AFTER + 0.05)


def _due():
    draw.tag_redraw()
    return None


def stop():
    if bpy.app.timers.is_registered(_due):
        bpy.app.timers.unregister(_due)
    ui = live.overlay.UI
    ui["over_bar"], ui["done_since"], ui["left_at"] = False, None, None
