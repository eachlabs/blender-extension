"""The bar's buttons: action pills (Play split with its camera menu part), the consent card, and the plan card."""

from .fonts import ELLIPSIS, cut, measure
from . import tokens as T
from .draw import _META_INSET, _flow, _icon, _icon_width, _meta, _paint, _paragraph_row, _text


try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None


_ACTION_LABELS = {"play": "Play", "frame": "Frame result", "keep": "Keep the scene", "prefs": "Open preferences",
                  "network": "Open preferences",
                  "new": "New scene", "code": "Show code", "halt": "Stop",
                  "consent_check": "Build with code check", "consent_plain": "Build without check",
                  "consent_cancel": "Cancel", "plan_build": "Build", "plan_cancel": "Cancel",
                  "missing": "Build the missing things", "plan_limit": "Build within my limit",
                  "final": "Final render"}
_ACTION_ICONS = {"play", "retry", "frame", "undo", "code"}
CONSENT_ACTIONS = ("consent_check", "consent_plain", "consent_cancel")
PLAN_ACTIONS = ("plan_build", "plan_cancel")
BUDGET_ACTIONS = ("plan_limit", "plan_raise", "plan_cancel")  # a plan that needs more rounds than the limit
_PLAIN = ("consent_cancel", "plan_cancel")  # drawn as text, right-aligned on the last line



def action_label(action, stages, undo_stage="", widen="", raise_label="", missing_label=""):
    if action == "consent_plain" and not T.CODE_CHECK_AVAILABLE:
        return "Build"
    if action == "widen" and widen:
        return widen
    if action == "plan_raise" and raise_label:
        return raise_label
    if action == "missing" and missing_label:
        return missing_label
    if action == "retry":
        failed = [s for s, v in stages.items() if v in ("failed", "partial")]
        return "Retry %s stage" % failed[0] if failed else "Retry"
    if action == "undo" and undo_stage:
        return "Undo stage: %s" % undo_stage.capitalize()
    if action == "undo":
        done = [s for s, v in stages.items() if v == "done"]
        return "Undo stage: %s" % done[-1].capitalize() if done else "Undo stage"
    return _ACTION_LABELS.get(action, action.capitalize())



def play_label(state, room=None):
    """The Play button's text: ``Pause`` while the animation plays, ``Play as <camera>`` when the scene has a
    camera, else ``Play``; the camera's name is cut at ``PLAY_NAME_MAX`` and to fit ``room`` px of text."""
    if state.playing:
        return T.PAUSE
    if not state.play_camera:
        return T.PLAY
    head = T.PLAY_AS % ""
    name_room = T.PLAY_NAME_MAX
    if room is not None:
        name_room = min(name_room, room - measure(head, "medium", T.PILL_SIZE))
    return head + cut(state.play_camera, "medium", T.PILL_SIZE, max(name_room, 0))



def _play_split(state):
    """The Play button's camera menu part: ``"open"`` or ``"closed"`` with a camera to choose while the animation
    is not playing, else ``""`` (no part)."""
    if not state.play_camera or state.playing:
        return ""
    return "open" if state.camera_menu else "closed"



def _pill(action, state, width=None):
    """``(width, height, item)`` of an action pill; ``item`` is (action, label, icon name or None, split part)."""
    h = T.PILL_LINE + 2 * T.PILL_PAD_Y
    if action == "play":
        icon = "pause" if state.playing else "play"
        split = _play_split(state)
        fixed = T.PILL_PAD_LEFT + T.PILL_ICON + T.PILL_ICON_GAP + T.PILL_PAD_RIGHT + (
            T.SPLIT_CHEVRON_W if split else 0)
        label = play_label(state, None if width is None else width - fixed)
        return fixed + measure(label, "medium", T.PILL_SIZE), h, (action, label, icon, split)
    label = action_label(action, state.stages, state.undo_stage, state.widen_label, state.raise_label,
                         state.missing_label)
    icon = action if action in _ACTION_ICONS else None
    if action in _PLAIN:  # plain text, no pill
        return measure(label, "medium", T.PILL_SIZE) + 2 * T.PILL_PAD_Y, h, (action, label, None, "")
    w = T.PILL_PAD_LEFT + (_icon_width(action) + T.PILL_ICON_GAP if icon else 0) + T.PILL_PAD_RIGHT
    return w + measure(label, "medium", T.PILL_SIZE), h, (action, label, icon, "")



def _draw_pill(canvas, x, y, w, h, item, hits):
    action, label, icon, split = item
    hits[action] = (x, y, w - T.SPLIT_CHEVRON_W if split else w, h)
    if action in _PLAIN:
        _text(canvas, label, x + T.PILL_PAD_Y, y + T.PILL_PAD_Y, T.PILL_LINE, "medium", T.PILL_SIZE, T.CANCEL_TEXT)
        return
    rect = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), h / 2, h / 2)
    if action in T.PRIMARY_ACTIONS or (action == "consent_plain" and not T.CODE_CHECK_AVAILABLE):
        canvas.drawRRect(rect, _paint(T.PRIMARY_FILL))
    else:
        canvas.drawRRect(rect, _paint(T.SECONDARY_FILL))
        inner = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x + 0.5, y + 0.5, w - 1, h - 1), h / 2, h / 2)
        canvas.drawRRect(inner, _paint(T.SECONDARY_STROKE, stroke=1))
    tx = x + T.PILL_PAD_LEFT
    if icon:
        _icon(canvas, icon, tx, y + (h - T.PILL_ICON) / 2, T.PILL_ICON, T.PILL_TEXT)
        tx += _icon_width(icon) + T.PILL_ICON_GAP
    _text(canvas, label, tx, y + T.PILL_PAD_Y, T.PILL_LINE, "medium", T.PILL_SIZE, T.PILL_TEXT)
    if split:  # the camera menu's part: a divider, then the chevron
        left = x + w - T.SPLIT_CHEVRON_W
        canvas.drawLine(left, y + 5, left, y + h - 5, _paint(T.SPLIT_DIVIDER, stroke=1))
        _icon(canvas, "chevron_down" if split == "open" else "chevron_up",  # as the quality pill
              left + (T.SPLIT_CHEVRON_W - T.QUALITY_CHEVRON) / 2 - 1, y + (h - T.QUALITY_CHEVRON) / 2,
              T.QUALITY_CHEVRON, T.PILL_TEXT)
        hits["play_menu"] = (left, y, T.SPLIT_CHEVRON_W, h)



def _actions_row(state, width, meta=""):
    """The action pills, wrapping onto more lines as needed. ``meta`` (the cost) is right-aligned on the
    last line, or on a line of its own when it does not fit there. *Cancel* of the consent card is
    right-aligned the same way."""
    line_h = T.PILL_LINE + 2 * T.PILL_PAD_Y
    items = [_pill(a, state, width) for a in state.actions]
    right = items.pop() if items and items[-1][2][0] in _PLAIN else None
    placed, height = _flow(items, width, T.PILL_GAP)
    meta_w = measure(meta.upper(), "mono", T.META_SIZE) + _META_INSET if meta else 0
    tail_w = right[0] if right else meta_w
    tail_y = 0.0
    if tail_w:
        last_y = placed[-1][1] if placed else 0.0
        last_end = max((px + pw for px, py, pw, ph, _ in placed if py == last_y), default=0.0)
        if placed and last_end + T.INLINE_GAP + tail_w > width:
            tail_y = height + T.PILL_GAP
            height = tail_y + line_h
        else:
            tail_y = last_y
            height = max(height, line_h)

    def paint(canvas, x, y, w, hits):
        for px, py, pw, ph, item in placed:
            _draw_pill(canvas, x + px, y + py, pw, ph, item, hits)
        if right:
            _draw_pill(canvas, x + w - right[0], y + tail_y, right[0], right[1], right[2], hits)
        elif meta:
            _meta(canvas, meta, x + w - _META_INSET, y + tail_y, line_h)
    return height, paint



def _consent_rows(state, width):
    """The consent card above the input: title, body, the buttons, and the Code check hint when it is offered."""
    rows = [_paragraph_row(T.CONSENT_TITLE, "semibold", T.TITLE_SIZE, T.TITLE_LINE, T.REPLY, width),
            _paragraph_row(T.CONSENT_BODY, "regular", T.BODY_SIZE, T.BODY_LINE, T.BODY, width),
            _actions_row(state, width)]
    if T.CODE_CHECK_AVAILABLE:
        rows.append(_paragraph_row(T.CONSENT_HINT, "medium", T.HINT_SIZE, T.HINT_LINE, T.HINT, width))
    return rows



def _plan_label(label, cached, width):
    """A plan chip's text, cut with an ellipsis so the chip fits ``width``."""
    text = "%s · %s" % (label, T.PLAN_CACHED) if cached else label
    room = width - 2 * T.CHIP_PAD_X - T.DOT - T.DOT_GAP
    if measure(text, "medium", T.CHIP_TEXT_SIZE) <= room:
        return text
    while text and measure(text + ELLIPSIS, "medium", T.CHIP_TEXT_SIZE) > room:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS



def _plan_chips_row(chips, width):
    """One chip per item, wrapping; a 3D item is orange, a code item grey. Each chip is a hit."""
    h = T.CHIP_LINE + 2 * T.CHIP_PAD_Y
    items = []
    for index, label, mode, cached in chips:
        text = _plan_label(label, cached and mode == "3d", width)
        w = T.CHIP_PAD_X * 2 + T.DOT + T.DOT_GAP + measure(text, "medium", T.CHIP_TEXT_SIZE)
        items.append((w, h, (index, text, mode)))
    placed, height = _flow(items, width, T.CHIP_GAP)

    def paint(canvas, x, y, w, hits):
        for cx, cy, cw, ch, (index, text, mode) in placed:
            left, top = x + cx, y + cy
            rect = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(left + 0.5, top + 0.5, cw - 1, ch - 1), ch / 2, ch / 2)
            three_d = mode == "3d"
            canvas.drawRRect(rect, _paint(T.PLAN_3D_FILL if three_d else T.CHIP_FILL))
            canvas.drawRRect(rect, _paint(T.PLAN_3D_STROKE if three_d else T.CHIP_STROKE, stroke=1))
            dx = left + T.CHIP_PAD_X
            canvas.drawCircle(dx + T.DOT / 2, top + ch / 2, T.DOT / 2, _paint(T.PLAN_3D_DOT if three_d else T.DOT_TODO))
            _text(canvas, text, dx + T.DOT + T.DOT_GAP, top + T.CHIP_PAD_Y, T.CHIP_LINE, "medium", T.CHIP_TEXT_SIZE,
                  T.CHIP_TEXT if three_d else T.CHIP_TEXT_TODO)
            if index < len(T.PLAN_HITS):
                hits[T.PLAN_HITS[index]] = (left, top, cw, ch)
    return height, paint



def _plan_rows(state, width):
    """The plan before anything is generated: the 3D line and its chips, the code line and its chips, the hint,
    then Build and Cancel."""
    rows = []
    if state.plan_3d:
        rows.append(_paragraph_row(state.plan_3d, "medium", T.PLAN_TITLE_SIZE, T.PLAN_TITLE_LINE, T.REPLY, width))
    three_d = [c for c in state.plan_chips if c[2] == "3d"]
    code = [c for c in state.plan_chips if c[2] == "code"]
    if three_d:
        rows.append(_plan_chips_row(three_d, width))
    if state.plan_code:  # the title when nothing is made in 3D
        if state.plan_3d:
            rows.append(_paragraph_row(state.plan_code, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.STATUS, width))
        else:
            rows.append(_paragraph_row(state.plan_code, "medium", T.PLAN_TITLE_SIZE, T.PLAN_TITLE_LINE, T.REPLY, width))
    if code:
        rows.append(_plan_chips_row(code, width))
    if state.plan_looks:  # a looks-only plan has this line alone, as its title
        looks_title = not state.plan_3d and not state.plan_code
        rows.append(_paragraph_row(state.plan_looks, "medium" if looks_title else "regular",
                                   T.PLAN_TITLE_SIZE if looks_title else T.TEXT_SIZE,
                                   T.PLAN_TITLE_LINE if looks_title else T.STATUS_LINE,
                                   T.REPLY if looks_title else T.STATUS, width))
    rows.append(_paragraph_row(state.plan_note or T.PLAN_HINT, "medium", T.HINT_SIZE, T.HINT_LINE, T.HINT, width))
    rows.append(_actions_row(state, width))
    return rows
