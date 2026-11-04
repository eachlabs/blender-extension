"""The bar's tab row: Scene, Assets and Characters above the input, the chosen one marked, and a line under them
saying what the next prompt does, with a chip for the selected thing it changes. Dimmed and without hits while a
run is going."""

from .fonts import clamp, cut, measure, wrap
from . import tokens as T
from .draw import _paint, _text


try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None


def _tab_width(label):
    return T.PILL_PAD_LEFT + measure(label, "medium", T.PILL_SIZE) + T.PILL_PAD_LEFT


def tab_line(state):
    """The line under the tabs, or ``None`` without a tab. On Assets and Characters a selected thing
    (``state.thing``) is changed instead of a new one added; Scene ignores the selection."""
    if not state.tab:
        return None
    if state.tab == "asset":
        return T.TAB_LINE_ASSET_CHANGE % state.thing if state.thing else T.TAB_LINE_ASSET
    if state.tab == "character":
        return T.TAB_LINE_CHARACTER_CHANGE % state.thing if state.thing else T.TAB_LINE_CHARACTER
    return T.TAB_LINE_SCENE_NEXT if state.has_scene else T.TAB_LINE_SCENE_FIRST


def chip_label(state):
    """The chip's name, cut with an ellipsis; ``""`` when no chip shows."""
    if state.tab not in ("asset", "character") or not state.thing:
        return ""
    return cut(state.thing, "medium", T.TAB_CHIP_SIZE, T.TAB_CHIP_NAME_MAX)


def _chip_width(label):
    return T.TAB_CHIP_PAD_X + measure(label, "medium", T.TAB_CHIP_SIZE) + T.TAB_CHIP_GAP + T.TAB_CHIP_CROSS + (
        T.TAB_CHIP_PAD_X)


def line_layout(state, width):
    """``(lines, chip)`` of the line under the tabs: at most ``TAB_LINE_LINES`` strings; ``chip`` is ``None``, ``"inline"`` (after the last line) or ``"below"`` (a line of its own)."""
    text = tab_line(state)
    if text is None:
        return [], None
    lines = clamp(text, wrap(text, "regular", T.TAB_LINE_SIZE, width), "regular", T.TAB_LINE_SIZE, width,
                  T.TAB_LINE_LINES)
    label = chip_label(state)
    if not label:
        return lines, None
    room = width - measure(lines[-1], "regular", T.TAB_LINE_SIZE) - T.TAB_CHIP_GAP
    return lines, "inline" if _chip_width(label) <= room else "below"


def _line_heights(lines, chip):
    heights = [T.TAB_LINE_LINE] * len(lines)
    if chip == "inline":
        heights[-1] = max(T.TAB_LINE_LINE, T.TAB_CHIP_H)
    elif chip == "below":
        heights.append(T.TAB_CHIP_H)
    return heights


def _draw_chip(canvas, label, x, y, hits, enabled):
    w, h = _chip_width(label), T.TAB_CHIP_H
    rect = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), h / 2, h / 2)
    canvas.drawRRect(rect, _paint(T.CHIP_ACTIVE_FILL))
    inner = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x + 0.5, y + 0.5, w - 1, h - 1), h / 2, h / 2)
    canvas.drawRRect(inner, _paint(T.CHIP_ACTIVE_STROKE, stroke=1))
    end = _text(canvas, label, x + T.TAB_CHIP_PAD_X, y, h, "medium", T.TAB_CHIP_SIZE, T.PILL_TEXT)
    cx, cy, r = end + T.TAB_CHIP_GAP + T.TAB_CHIP_CROSS / 2, y + h / 2, T.TAB_CHIP_CROSS / 2
    cross = _paint(T.PILL_TEXT, stroke=1.4)
    canvas.drawLine(cx - r, cy - r, cx + r, cy + r, cross)
    canvas.drawLine(cx - r, cy + r, cx + r, cy - r, cross)
    if enabled:
        hits[T.TAB_CLEAR] = (x, y, w, h)


def tab_row(state, width):
    """``(height, paint)`` of the tab row and its line, left-aligned with the prompt text."""
    pill_h = T.PILL_LINE + 2 * T.PILL_PAD_Y
    lines, chip = line_layout(state, width)
    heights = _line_heights(lines, chip)
    h = pill_h + (T.TAB_LINE_GAP + sum(heights) if lines else 0)

    def paint(canvas, x, y, w, hits):
        if not state.tabs_enabled:
            canvas.saveLayerAlpha(skia.Rect.MakeXYWH(x - 1, y - 1, w + 2, h + 2), round(T.SEND_DISABLED_ALPHA * 255))
        left = x
        for (target, label), hit_id in zip(T.TABS, T.TAB_HITS):
            tw = _tab_width(label)
            chosen = target == state.tab
            rect = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(left, y, tw, pill_h), pill_h / 2, pill_h / 2)
            canvas.drawRRect(rect, _paint(T.CHIP_ACTIVE_FILL if chosen else T.SECONDARY_FILL))
            inner = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(left + 0.5, y + 0.5, tw - 1, pill_h - 1), pill_h / 2,
                                          pill_h / 2)
            canvas.drawRRect(inner, _paint(T.CHIP_ACTIVE_STROKE if chosen else T.SECONDARY_STROKE, stroke=1))
            _text(canvas, label, left + T.PILL_PAD_LEFT, y + T.PILL_PAD_Y, T.PILL_LINE, "medium", T.PILL_SIZE,
                  T.PILL_TEXT if chosen else T.TAB_TEXT)
            if state.tabs_enabled:
                hits[hit_id] = (left, y, tw, pill_h)
            left += tw + T.PILL_GAP
        top = y + pill_h + T.TAB_LINE_GAP
        for i, line in enumerate(lines):
            lh = heights[i]
            end = _text(canvas, line, x, top, lh, "regular", T.TAB_LINE_SIZE, T.HINT)
            if chip == "inline" and i == len(lines) - 1:
                _draw_chip(canvas, chip_label(state), end + T.TAB_CHIP_GAP, top + (lh - T.TAB_CHIP_H) / 2, hits,
                           state.tabs_enabled)
            top += lh
        if chip == "below":
            _draw_chip(canvas, chip_label(state), x, top, hits, state.tabs_enabled)
        if not state.tabs_enabled:
            canvas.restore()
    return h, paint
