"""The bar's input row: the prompt field, the quality pill, the send button and the hint; and the menus' rows."""

from .fonts import clamp, cut, measure, wrap
from . import tokens as T
from . import video_texts as V
from .draw import _RUNNING, _draw_mark, _icon, _paint, _text


try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None


def hint_text(width):
    items = list(T.HINTS)
    while len(items) > 1 and measure(T.HINT_SEPARATOR.join(items), "medium", T.HINT_SIZE) > width:
        items.pop()
    return T.HINT_SEPARATOR.join(items)



def placeholder(state):
    """The empty field's example of what to type, by tab; on Assets and Characters a selected thing is changed."""
    if state.tab == "asset":
        return T.PLACEHOLDER_ASSET_CHANGE % state.thing if state.thing else T.PLACEHOLDER_ASSET
    if state.tab == "character":
        return T.PLACEHOLDER_CHARACTER_CHANGE % state.thing if state.thing else T.PLACEHOLDER_CHARACTER
    if state.tab == "video":
        return V.PLACEHOLDER
    return T.PLACEHOLDER_NEXT if state.has_scene else T.PLACEHOLDER_FIRST



def _quality_text(state):
    """The pill's label, cut with an ellipsis at ``QUALITY_PILL_MAX``."""
    return cut(state.quality_label, "medium", T.PILL_SIZE, T.QUALITY_PILL_MAX)



def _quality_width(state):
    return (T.PILL_PAD_LEFT + measure(_quality_text(state), "medium", T.PILL_SIZE) + T.PILL_ICON_GAP
            + T.QUALITY_CHEVRON + T.PILL_PAD_RIGHT)



def _field_width(width, state=None):
    """The text width of the input row without the quality pill (and without the settings button when shown)."""
    room = width - T.MARK_SIZE - T.MARK_GAP - T.BUTTON - T.BUTTON_GAP
    return room - (T.SETTINGS + T.PILL_GAP if state is not None and state.settings else 0)



def quality_inline(state, width):
    """True when the quality pill sits on the input row, left of the send button; else it has a row of its own
    above the input, so a narrow bar keeps room to type."""
    return bool(state.quality_label) and (
        _field_width(width, state) - _quality_width(state) - T.PILL_GAP >= T.QUALITY_FIELD_MIN)



def _text_width(state, width):
    if quality_inline(state, width):
        return _field_width(width, state) - _quality_width(state) - T.PILL_GAP
    return _field_width(width, state)



def _draw_quality_pill(canvas, state, x, y, hits):
    """The quality pill with its top-left at (x, y): the label and a chevron, dimmed while a run is going."""
    w, h = _quality_width(state), T.PILL_LINE + 2 * T.PILL_PAD_Y
    if not state.quality_enabled:
        canvas.saveLayerAlpha(skia.Rect.MakeXYWH(x - 1, y - 1, w + 2, h + 2), round(T.SEND_DISABLED_ALPHA * 255))
    rect = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), h / 2, h / 2)
    canvas.drawRRect(rect, _paint(T.SECONDARY_FILL))
    inner = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x + 0.5, y + 0.5, w - 1, h - 1), h / 2, h / 2)
    canvas.drawRRect(inner, _paint(T.MENU_CHOSEN_STROKE if state.quality_menu else T.SECONDARY_STROKE, stroke=1))
    end = _text(canvas, _quality_text(state), x + T.PILL_PAD_LEFT, y + T.PILL_PAD_Y, T.PILL_LINE, "medium",
                T.PILL_SIZE, T.PILL_TEXT)
    _icon(canvas, "chevron_down" if state.quality_menu else "chevron_up", end + T.PILL_ICON_GAP,
          y + (h - T.QUALITY_CHEVRON) / 2, T.QUALITY_CHEVRON, T.PILL_TEXT)
    if state.quality_enabled:
        hits["quality"] = (x, y, w, h)
    else:
        canvas.restore()



def _quality_row(state, width):
    """The quality pill on a row of its own, right-aligned above the send button."""
    h = T.PILL_LINE + 2 * T.PILL_PAD_Y

    def paint(canvas, x, y, w, hits):
        _draw_quality_pill(canvas, state, x + w - _quality_width(state), y, hits)
    return h, paint



def _menu_item(name, hint, width):
    """(height, hint lines, one line) of a menu item: the hint follows the name on its line when both fit."""
    text_w = width - 2 * T.MENU_PAD_X - T.DOT - T.DOT_GAP
    name_w = measure(name, "medium", T.MENU_NAME_SIZE)
    one_line = name_w + T.INLINE_GAP + measure(hint, "regular", T.MENU_HINT_SIZE) <= text_w
    if one_line:
        return 2 * T.MENU_PAD_Y + T.MENU_NAME_LINE, [hint], True
    lines = clamp(hint, wrap(hint, "regular", T.MENU_HINT_SIZE, text_w), "regular", T.MENU_HINT_SIZE, text_w, 2)
    return 2 * T.MENU_PAD_Y + T.MENU_NAME_LINE + len(lines) * T.MENU_HINT_LINE, lines, False



def _menu_rows(state, width):
    """The open quality menu: its title, then one item per mode with its hint; the current one is marked."""
    return menu_rows(state.quality_menu, T.MENU_TITLE, T.QUALITY_HITS, width)



def menu_rows(entries, title_text, hit_ids, width):
    """A menu's rows: its title, then one item per ``(name, hint, chosen)`` with its hint, the chosen one marked;
    item ``i`` gets the hit ``hit_ids[i]``. A name too long for the bar ends in an ellipsis."""
    room = width - 2 * T.MENU_PAD_X - T.DOT - T.DOT_GAP
    entries = [(cut(name, "medium", T.MENU_NAME_SIZE, room), hint, chosen) for name, hint, chosen in entries]
    items = [(_menu_item(name, hint, width), name, chosen) for name, hint, chosen in entries]
    height = sum(h for (h, _, _), _, _ in items) + T.MENU_GAP * (len(items) - 1)

    def title(canvas, x, y, w, hits):
        _text(canvas, title_text.upper(), x, y, T.META_LINE, "mono", T.META_SIZE, T.META)

    def paint(canvas, x, y, w, hits):
        top = y
        for i, ((h, lines, one_line), name, chosen) in enumerate(items):
            if chosen:
                rect = skia.Rect.MakeXYWH(x + 0.5, top + 0.5, w - 1, h - 1)
                canvas.drawRRect(skia.RRect.MakeRectXY(rect, T.MENU_RADIUS, T.MENU_RADIUS), _paint(T.MENU_CHOSEN_FILL))
                canvas.drawRRect(skia.RRect.MakeRectXY(rect, T.MENU_RADIUS, T.MENU_RADIUS),
                                 _paint(T.MENU_CHOSEN_STROKE, stroke=1))
            lx = x + T.MENU_PAD_X
            ty = top + T.MENU_PAD_Y
            canvas.drawCircle(lx + T.DOT / 2, ty + T.MENU_NAME_LINE / 2, T.DOT / 2,
                              _paint(T.ORANGE + (1.0,) if chosen else T.DOT_TODO))
            lx += T.DOT + T.DOT_GAP
            end = _text(canvas, name, lx, ty, T.MENU_NAME_LINE, "medium", T.MENU_NAME_SIZE, T.REPLY)
            if one_line:
                _text(canvas, lines[0], end + T.INLINE_GAP, ty, T.MENU_NAME_LINE, "regular", T.MENU_HINT_SIZE,
                      T.MENU_HINT)
            else:
                for j, part in enumerate(lines):
                    _text(canvas, part, lx, ty + T.MENU_NAME_LINE + j * T.MENU_HINT_LINE, T.MENU_HINT_LINE,
                          "regular", T.MENU_HINT_SIZE, T.MENU_HINT)
            if i < len(hit_ids):
                hits[hit_ids[i]] = (x, top, w, h)
            top += h + T.MENU_GAP
    return [(T.META_LINE, title), (height, paint)]



def _input_layout(state, text_w):
    f = state.field
    lines = wrap(f.text, "regular", T.TEXT_SIZE, text_w) if f.text else [(0, 0)]
    caret_line = next((i for i in range(len(lines) - 1, -1, -1) if lines[i][0] <= f.caret), 0)
    end = min(len(lines), max(T.MAX_LINES, caret_line + 1))
    first = max(0, end - T.MAX_LINES)
    return lines, first, end, caret_line



def _input_row(state, width):
    text_x = T.MARK_SIZE + T.MARK_GAP
    text_w = _text_width(state, width)
    inline = quality_inline(state, width)
    lines, first, end, caret_line = _input_layout(state, text_w)
    shown = end - first
    height = max(T.BUTTON, shown * T.TEXT_LINE)

    def paint(canvas, x, y, w, hits):
        f = state.field
        top = y + (height - shown * T.TEXT_LINE) / 2
        last_mid = top + (shown - 0.5) * T.TEXT_LINE
        _draw_mark(canvas, x, last_mid - T.MARK_SIZE / 2)
        tx = x + text_x
        if not f.text:
            hint = placeholder(state)  # one line, cut with an ellipsis before the send button
            hint = clamp(hint, wrap(hint, "regular", T.TEXT_SIZE, text_w), "regular", T.TEXT_SIZE, text_w, 1)[0]
            _text(canvas, hint, tx, top, T.TEXT_LINE, "regular", T.TEXT_SIZE, T.PLACEHOLDER)
        sel = f.selection() if state.focused else None
        for row, i in enumerate(range(first, end)):
            s, e = lines[i]
            ly = top + row * T.TEXT_LINE
            line = f.text[s:e]
            if sel and sel[0] < e + (1 if i < len(lines) - 1 else 0) and sel[1] > s:
                a, b = max(sel[0], s), min(sel[1], e)
                sx = tx + measure(line[:a - s], "regular", T.TEXT_SIZE)
                sw = max(measure(line[a - s:b - s], "regular", T.TEXT_SIZE), 3.0)
                canvas.drawRect(skia.Rect.MakeXYWH(sx, ly, sw, T.TEXT_LINE), _paint(T.SELECTION))
            if f.text:
                _text(canvas, line.rstrip("\n"), tx, ly, T.TEXT_LINE, "regular", T.TEXT_SIZE, T.TEXT)
            if state.focused and state.caret_on and i == caret_line:
                cx = tx + measure(line[:f.caret - s], "regular", T.TEXT_SIZE) if f.text else tx
                canvas.drawRect(skia.Rect.MakeXYWH(cx, ly + (T.TEXT_LINE - T.CARET_H) / 2, T.CARET_W, T.CARET_H),
                                _paint(T.CARET))
        hits["field"] = (tx, y, text_w, height)
        bx, by = x + w - T.BUTTON, y + (height - T.BUTTON) / 2
        _draw_button(canvas, state, bx, by, hits)
        left = bx
        if state.settings:
            left = bx - T.PILL_GAP - T.SETTINGS
            _draw_settings(canvas, left, y + (height - T.SETTINGS) / 2, hits)
        if inline:
            ph = T.PILL_LINE + 2 * T.PILL_PAD_Y
            _draw_quality_pill(canvas, state, left - T.PILL_GAP - _quality_width(state), y + (height - ph) / 2, hits)
    return height, paint



def _draw_settings(canvas, x, y, hits):
    """The settings button: a round secondary button with three slider lines and their knobs."""
    d = T.SETTINGS
    cx, cy = x + d / 2, y + d / 2
    canvas.drawCircle(cx, cy, d / 2, _paint(T.SECONDARY_FILL))
    canvas.drawCircle(cx, cy, d / 2 - 0.5, _paint(T.SECONDARY_STROKE, stroke=1))
    line = _paint(T.PILL_TEXT, stroke=1.4)
    for row, knob in ((-4.0, 2.5), (0.0, -2.5), (4.0, 1.0)):
        canvas.drawLine(cx - 6, cy + row, cx + 6, cy + row, line)
        canvas.drawCircle(cx + knob, cy + row, 1.9, _paint(T.PILL_TEXT))
    hits["settings"] = (x, y, d, d)



def _draw_button(canvas, state, x, y, hits):
    d = T.BUTTON
    cx, cy = x + d / 2, y + d / 2
    if state.mode in _RUNNING + ("plan",):  # Stop on the plan is its Cancel
        canvas.drawCircle(cx, cy, d / 2, _paint(T.STOP_FILL))
        canvas.drawCircle(cx, cy, d / 2 - 0.5, _paint(T.STOP_STROKE, stroke=1))
        s = T.STOP_SQUARE
        canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(cx - s / 2, cy - s / 2, s, s), 2.5, 2.5),
                         _paint(T.WHITE + (1.0,)))
        hits["stop"] = (x, y, d, d)
        return
    if not state.send_enabled:
        canvas.saveLayerAlpha(skia.Rect.MakeXYWH(x - 1, y - 1, d + 2, d + 2), round(T.SEND_DISABLED_ALPHA * 255))
    canvas.drawCircle(cx, cy, d / 2, _paint(T.ORANGE + (1.0,)))
    _icon(canvas, "send", cx - 6, cy - 6, 12, T.WHITE + (1.0,))
    if state.send_enabled:
        hits["send"] = (x, y, d, d)
    else:
        canvas.restore()
        if state.send_tip:  # no action, only its tooltip saying why
            hits[V.SEND_OFF] = (x, y, d, d)



def _hint_row(width):
    text = hint_text(width)

    def paint(canvas, x, y, w, hits):
        _text(canvas, text, x, y, T.HINT_LINE, "medium", T.HINT_SIZE, T.HINT)
    return T.HINT_LINE, paint
