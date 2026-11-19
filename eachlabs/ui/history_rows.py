"""The bar's chat history: the scene chat's earlier prompts and answers in a view that scrolls, above the input.

The newest entry sits at the bottom. ``state.history_scroll`` is how far the view is moved up from there, in
logical px; ``max_scroll`` is the furthest it goes."""

from .fonts import cut, wrap
from . import tokens as T
from .draw import _icon, _paint, _text


try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None


def _label(role, meta):
    if role == "user":
        return T.HISTORY_YOU
    return T.HINT_SEPARATOR.join(part for part in (T.HISTORY_BAR, meta) if part)


def _layout(entries, width):
    """``([(top, label, role, lines)], height)`` of every entry laid out top to bottom at ``width``."""
    text_w = width - T.HISTORY_SCROLL_W
    items, top = [], 0
    for role, text, meta in entries:
        lines = [text[s:e].rstrip("\n") for s, e in wrap(text, "regular", T.TEXT_SIZE, text_w)] or [""]
        items.append((top, cut(_label(role, meta).upper(), "mono", T.META_SIZE, text_w), role, lines))
        top += T.META_LINE + T.HISTORY_LABEL_GAP + len(lines) * T.TEXT_LINE + T.HISTORY_GAP
    return items, max(0, top - T.HISTORY_GAP)


def view_height(entries, width):
    """The height of the scrolling view: the entries' own, up to ``HISTORY_MAX_H``."""
    return min(_layout(entries, width)[1], T.HISTORY_MAX_H) if entries else T.TEXT_LINE


def max_scroll(entries, width):
    """How far the view can move up from the newest entry, in logical px; 0 when everything fits."""
    return max(0, _layout(entries, width)[1] - T.HISTORY_MAX_H) if entries else 0


def clamp_scroll(scroll, entries, width):
    return min(max(0.0, float(scroll)), float(max_scroll(entries, width)))


PAGE_KEYS = ("PAGE_UP", "PAGE_DOWN")


def step(kind, value, moved=0):
    """Logical px an input event moves the view (positive: towards earlier prompts), or 0 for an event that does
    not scroll it. ``kind`` and ``value`` are Blender's event type and value; ``moved``: how far up the fingers
    moved on a trackpad, in px."""
    if kind == "WHEELUPMOUSE":
        return T.HISTORY_STEP
    if kind == "WHEELDOWNMOUSE":
        return -T.HISTORY_STEP
    if kind == "TRACKPADPAN":
        return -moved  # the content follows the fingers
    if kind in PAGE_KEYS and value == "PRESS":
        return T.HISTORY_MAX_H * 0.8 * (1 if kind == "PAGE_UP" else -1)
    return 0


def _button(canvas, name, x, y, hits, hit):
    s = T.HISTORY_BUTTON
    _icon(canvas, name, x + (s - T.HISTORY_ICON) / 2, y + (s - T.HISTORY_ICON) / 2, T.HISTORY_ICON, T.META)
    hits[hit] = (x, y, s, s)


def rows(state, width):
    """The open history: a title row with Close (and the scroll arrows when it scrolls), then the view."""
    entries = list(state.history)
    items, total = _layout(entries, width)
    view_h = view_height(entries, width)
    furthest = max(0, total - view_h)
    scroll = min(max(0.0, float(state.history_scroll)), float(furthest))

    def title(canvas, x, y, w, hits):
        _text(canvas, T.HISTORY_TITLE.upper(), x, y, T.HISTORY_BUTTON, "mono", T.META_SIZE, T.META)
        right = x + w - T.HISTORY_BUTTON
        _button(canvas, "close", right, y, hits, "history_close")
        if furthest:
            _button(canvas, "chevron_down", right - T.HISTORY_BUTTON, y, hits, "history_down")
            _button(canvas, "chevron_up", right - 2 * T.HISTORY_BUTTON, y, hits, "history_up")

    def view(canvas, x, y, w, hits):
        if not entries:
            _text(canvas, T.HISTORY_EMPTY, x, y, T.TEXT_LINE, "regular", T.TEXT_SIZE, T.PLACEHOLDER)
            return
        canvas.save()
        canvas.clipRect(skia.Rect.MakeXYWH(x, y, w, view_h))
        shift = y - (furthest - scroll)  # scroll 0 shows the end
        for top, label, role, lines in items:
            height = T.META_LINE + T.HISTORY_LABEL_GAP + len(lines) * T.TEXT_LINE
            if shift + top + height < y or shift + top > y + view_h:
                continue
            _text(canvas, label, x, shift + top, T.META_LINE, "mono", T.META_SIZE, T.META)
            color = T.TEXT if role == "user" else T.HISTORY_ANSWER
            first = shift + top + T.META_LINE + T.HISTORY_LABEL_GAP
            for i, line in enumerate(lines):
                ly = first + i * T.TEXT_LINE
                if y - T.TEXT_LINE <= ly <= y + view_h:
                    _text(canvas, line, x, ly, T.TEXT_LINE, "regular", T.TEXT_SIZE, color)
        canvas.restore()
        if furthest:  # the thumb: where the view is in the whole history
            track = view_h - 2 * T.HISTORY_THUMB_INSET
            thumb = max(T.HISTORY_THUMB_MIN, track * view_h / total)
            at = (track - thumb) * (1 - scroll / furthest)
            rect = skia.Rect.MakeXYWH(x + w - T.HISTORY_THUMB_W, y + T.HISTORY_THUMB_INSET + at, T.HISTORY_THUMB_W,
                                      thumb)
            canvas.drawRRect(skia.RRect.MakeRectXY(rect, T.HISTORY_THUMB_W / 2, T.HISTORY_THUMB_W / 2),
                             _paint(T.HISTORY_THUMB))
    return [(T.HISTORY_BUTTON, title), (view_h, view)]
