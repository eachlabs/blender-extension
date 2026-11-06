"""The Video tab's rows: its card above the tabs (confirm, stages, ready, failed), the tab row, an open chip's menu,
the settings chips with the price, and the notes under them. No Blender code."""

from .fonts import cut, measure
from . import tokens as T
from . import video_texts as V
from .action_rows import _actions_row
from .draw import _META_INSET, _flow, _icon, _meta, _paint, _paragraph_row, _spinner, _text
from .input_rows import _menu_rows, menu_rows
from .status_rows import _chip_width, _draw_chip
from .tab_row import tab_row

try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None

CHIP_NAME_MAX = 150  # a longer camera name ends in an ellipsis
ERROR = T.RED + (1.0,)


def _chip_text(hit, label):
    return cut(label, "medium", T.PILL_SIZE, CHIP_NAME_MAX) if hit == V.CHIP_HITS[0] else label


def _chip_w(hit, label):
    ring = T.PILL_ICON + T.PILL_ICON_GAP if hit == V.CHIP_HITS[0] else 0
    return (T.PILL_PAD_LEFT + ring + measure(_chip_text(hit, label), "medium", T.PILL_SIZE) + T.PILL_ICON_GAP
            + T.QUALITY_CHEVRON + T.PILL_PAD_RIGHT)


def _draw_setting(canvas, x, y, w, h, hit, label, open_):
    """One settings chip, drawn as the quality pill: its label (the camera's with a ring first) and a chevron."""
    rect = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), h / 2, h / 2)
    canvas.drawRRect(rect, _paint(T.SECONDARY_FILL))
    inner = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x + 0.5, y + 0.5, w - 1, h - 1), h / 2, h / 2)
    canvas.drawRRect(inner, _paint(T.MENU_CHOSEN_STROKE if open_ else T.SECONDARY_STROKE, stroke=1))
    tx = x + T.PILL_PAD_LEFT
    if hit == V.CHIP_HITS[0]:
        _icon(canvas, "ring", tx, y + (h - T.PILL_ICON) / 2, T.PILL_ICON, T.PILL_TEXT)
        tx += T.PILL_ICON + T.PILL_ICON_GAP
    end = _text(canvas, _chip_text(hit, label), tx, y + T.PILL_PAD_Y, T.PILL_LINE, "medium", T.PILL_SIZE, T.PILL_TEXT)
    _icon(canvas, "chevron_down" if open_ else "chevron_up", end + T.PILL_ICON_GAP, y + (h - T.QUALITY_CHEVRON) / 2,
          T.QUALITY_CHEVRON, T.PILL_TEXT)


def settings_row(state, width):
    """The settings chips, wrapping as needed, with the price right-aligned on the last line (or below it)."""
    h = T.PILL_LINE + 2 * T.PILL_PAD_Y
    items = [(_chip_w(hit, label), h, (hit, label)) for hit, label in state.video_chips]
    placed, height = _flow(items, width, T.PILL_GAP)
    price_w = measure(state.video_price.upper(), "mono", T.META_SIZE) + _META_INSET if state.video_price else 0
    last_y = placed[-1][1] if placed else 0.0
    last_end = max((px + pw for px, py, pw, _ph, _ in placed if py == last_y), default=0.0)
    price_y = last_y
    if price_w and last_end + T.INLINE_GAP + price_w > width:
        price_y = height + T.PILL_GAP
        height = price_y + h

    def paint(canvas, x, y, w, hits):
        for px, py, pw, ph, (hit, label) in placed:
            name = V.CHIPS[V.CHIP_HITS.index(hit)]
            _draw_setting(canvas, x + px, y + py, pw, ph, hit, label, state.video_open_chip == name)
            hits[hit] = (x + px, y + py, pw, ph)
        if state.video_price:
            _meta(canvas, state.video_price, x + w - _META_INSET, y + price_y, h)
    return height, paint


def _stage_row(state, width):
    """The stage chips with the card's meta right-aligned; the meta takes a line of its own when they do not fit."""
    h = T.CHIP_LINE + 2 * T.CHIP_PAD_Y
    meta_w = measure(state.video_meta.upper(), "mono", T.META_SIZE) + T.INLINE_GAP + _META_INSET
    items = [(_chip_width(label, value), h, (label, value)) for label, value in state.stages.items()]
    whole = sum(w for w, _h, _i in items) + T.CHIP_GAP * (len(items) - 1)
    own_line = bool(state.video_meta) and whole > width - meta_w
    placed, height = _flow(items, width if own_line else width - meta_w, T.CHIP_GAP)
    top = h + T.CHIP_GAP if own_line else 0

    def paint(canvas, x, y, w, hits):
        for cx, cy, cw, ch, (label, value) in placed:
            _draw_chip(canvas, x + cx, y + top + cy, cw, ch, label, value, state.spinner_phase)
        if state.video_meta:
            _meta(canvas, state.video_meta, x + w - _META_INSET, y, h)
    return top + height, paint


def _live_row(state, width):
    """The spinner and the stage's live line."""
    indent = T.SPINNER + T.INLINE_GAP
    height, text = _paragraph_row(state.video_line, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.STATUS, width - indent)

    def paint(canvas, x, y, w, hits):
        _spinner(canvas, x, y + T.STATUS_LINE / 2, state.spinner_phase)
        text(canvas, x + indent, y, w - indent, hits)
    return height, paint


def card_rows(state, width):
    """The card above the tabs for the confirm, the video being made, made, failed or stopped."""
    card = state.video_card
    if not card:
        return []
    if card == "confirm":
        rows = [_paragraph_row(state.video_meta.upper(), "mono", T.META_SIZE, T.META_LINE, T.META, width)]
    else:
        rows = [_stage_row(state, width)]
    if state.video_text:
        rows.append(_paragraph_row(state.video_text, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.REPLY, width))
    if state.video_error:
        rows.append(_paragraph_row(state.video_error, "medium", T.TEXT_SIZE, T.STATUS_LINE, ERROR, width))
    if card == "progress" and state.video_line:
        rows.append(_live_row(state, width))
    if state.video_ask:
        rows.append(_paragraph_row(state.video_ask, "medium", T.TEXT_SIZE, T.STATUS_LINE, T.REPLY, width))
    if state.actions:
        rows.append(_actions_row(state, width))
    return rows


def rows(state, width):
    """Every row of the Video tab above the input row."""
    out = card_rows(state, width)
    out.append(tab_row(state, width))
    if state.quality_menu:  # the quality pill's menu, above the chips as on the other tabs
        out.extend(_menu_rows(state, width))
    elif state.video_menu:
        out.extend(menu_rows(state.video_menu, state.video_menu_title, V.MENU_HITS, width))
    if state.video_chips:
        out.append(settings_row(state, width))
    for note in state.video_notes:
        quiet = bool(state.video_chips)  # with no camera, the note is the tab's whole message
        out.append(_paragraph_row(note, "regular", T.TAB_LINE_SIZE if quiet else T.TEXT_SIZE,
                                  T.TAB_LINE_LINE if quiet else T.STATUS_LINE, T.HINT if quiet else T.REPLY, width))
    return out
