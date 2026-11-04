"""The bar's status: stage chips, the asked prompt, checking and thinking lines, 3D job rows and errors."""

import dataclasses

from .fonts import MAX_TEXT_LINES, clamp, measure, wrap
from . import tokens as T
from .action_rows import _actions_row, _draw_pill, _pill
from .draw import _META_INSET, _RUNNING, _flow, _meta, _paint, _paragraph_row, _shield, _spinner, _text
from .input_rows import _hint_row, _input_layout, _text_width, menu_rows


try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None


OBJECT_LINE_MAX = 2  # lines one 3D job's row may take



def _chip_width(stage, state):
    lead = T.SPINNER if state == "active" else T.DOT
    return T.CHIP_PAD_X * 2 + lead + T.DOT_GAP + measure(stage.capitalize(), "medium", T.CHIP_TEXT_SIZE)



def _draw_chip(canvas, x, y, w, h, stage, state, phase):
    rect = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x + 0.5, y + 0.5, w - 1, h - 1), h / 2, h / 2)
    fill, stroke, dot = {
        "active": (T.CHIP_ACTIVE_FILL, T.CHIP_ACTIVE_STROKE, None),
        "done": (T.CHIP_FILL, T.CHIP_STROKE, T.DOT_DONE),
        "failed": (T.CHIP_FAILED_FILL, T.CHIP_FAILED_STROKE, T.DOT_FAILED),
        "partial": (T.CHIP_FILL, T.CHIP_STROKE, T.DOT_DONE),
    }.get(state, (T.CHIP_FILL, T.CHIP_STROKE, T.DOT_TODO))
    canvas.drawRRect(rect, _paint(fill))
    canvas.drawRRect(rect, _paint(stroke, stroke=1))
    cy = y + h / 2
    lx = x + T.CHIP_PAD_X
    if dot is None:
        r = T.SPINNER / 2 - 0.75
        canvas.drawCircle(lx + T.SPINNER / 2, cy, r, _paint(T.SPINNER_RING, stroke=1.5))
        arc = skia.Path()
        arc.addArc(skia.Rect.MakeXYWH(lx + T.SPINNER / 2 - r, cy - r, 2 * r, 2 * r), phase * 360 - 90, 100)
        canvas.drawPath(arc, _paint(T.ORANGE + (1.0,), stroke=1.5))
        lx += T.SPINNER
    elif state == "partial":  # partly done: a half-filled dot
        r = T.DOT / 2
        canvas.drawCircle(lx + r, cy, r - 0.5, _paint(dot, stroke=1))
        half = skia.Path()
        half.addArc(skia.Rect.MakeXYWH(lx, cy - r, 2 * r, 2 * r), 90, 180)
        half.close()
        canvas.drawPath(half, _paint(dot))
        lx += T.DOT
    else:
        canvas.drawCircle(lx + T.DOT / 2, cy, T.DOT / 2, _paint(dot))
        lx += T.DOT
    color = T.CHIP_TEXT_TODO if state in ("todo", "cancelled") else T.CHIP_TEXT
    _text(canvas, stage.capitalize(), lx + T.DOT_GAP, y + T.CHIP_PAD_Y, T.CHIP_LINE, "medium", T.CHIP_TEXT_SIZE, color)



def _badge_width():
    return 2 * T.BADGE_PAD_X + T.BADGE_ICON + T.BADGE_ICON_GAP + measure(T.BADGE_TEXT, "mono", T.BADGE_SIZE)



def _draw_badge(canvas, x, cy):
    """The green ``CODE CHECK`` badge, its left edge at x, centred on cy."""
    w, h = _badge_width(), T.BADGE_LINE + 2 * T.BADGE_PAD_Y
    y = cy - h / 2
    rect = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x + 0.5, y + 0.5, w - 1, h - 1), h / 2, h / 2)
    canvas.drawRRect(rect, _paint(T.BADGE_FILL))
    canvas.drawRRect(rect, _paint(T.BADGE_STROKE, stroke=1))
    _shield(canvas, x + T.BADGE_PAD_X, cy - T.BADGE_ICON / 2, T.BADGE_ICON, T.BADGE_INK)
    _text(canvas, T.BADGE_TEXT, x + T.BADGE_PAD_X + T.BADGE_ICON + T.BADGE_ICON_GAP, y + T.BADGE_PAD_Y,
          T.BADGE_LINE, "mono", T.BADGE_SIZE, T.BADGE_INK)



def _chips_row(state, width):
    """Stage chips with the round (or Done, Stopped) right-aligned; the Code check badge sits left of the
    round. When the chips cannot share a line with them, the round and badge take a line of their own."""
    meta = {"building": "Round %d of %d" % (state.round, state.total), "waiting": "Round %d of %d"
            % (state.round, state.total), "done": "Done", "stopped": "Stopped"}.get(state.mode, "")
    badge = state.code_check and state.mode in _RUNNING
    text_w = measure(meta.upper(), "mono", T.META_SIZE) if meta else 0
    meta_w = text_w + (_badge_width() + T.BADGE_GAP if badge else 0) + T.INLINE_GAP + _META_INSET if meta else 0
    h = T.CHIP_LINE + 2 * T.CHIP_PAD_Y
    items = [(_chip_width(s, v), h, (s, v)) for s, v in state.stages.items()]
    own_line = bool(meta and items and width - meta_w < max(w for w, _, _ in items))
    placed, height = _flow(items, width if own_line else width - meta_w, T.CHIP_GAP)
    top = h + T.CHIP_GAP if own_line else 0

    def paint(canvas, x, y, w, hits):
        for cx, cy, cw, ch, (stage, value) in placed:
            _draw_chip(canvas, x + cx, y + top + cy, cw, ch, stage, value, state.spinner_phase)
        if meta:
            right = x + w - _META_INSET
            _meta(canvas, meta, right, y, h)
            if badge:
                _draw_badge(canvas, right - text_w - T.BADGE_GAP - _badge_width(), y + h / 2)
    return top + height, paint



def _asked_row(state, width):
    """"You asked: …" in quiet text: one line cut with an ellipsis, or the whole prompt once clicked."""
    text = "%s %s" % (T.ASKED_LABEL, " ".join(state.asked.split()))
    shown = clamp(text, wrap(text, "regular", T.HINT_SIZE, width), "regular", T.HINT_SIZE, width,
                  max_lines=T.ASKED_LINES_OPEN if state.asked_open else 1)

    def paint(canvas, x, y, w, hits):
        for i, part in enumerate(shown):
            _text(canvas, part, x, y + i * T.HINT_LINE, T.HINT_LINE, "regular", T.HINT_SIZE, T.HINT)
        hits["asked"] = (x, y, w, len(shown) * T.HINT_LINE)
    return len(shown) * T.HINT_LINE, paint



def _checking_row(state, width):
    """A spinner, then *Code check: reading the step before it runs…*."""
    indent = T.SPINNER + T.INLINE_GAP
    height, text = _paragraph_row(state.status, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.STATUS, width - indent)

    def paint(canvas, x, y, w, hits):
        _spinner(canvas, x, y + T.STATUS_LINE / 2, state.spinner_phase)
        text(canvas, x + indent, y, w - indent, hits)
    return height, paint



def _object_row(line, state, width):
    """A 3D job's line with a small orange dot in front."""
    indent = T.DOT + T.INLINE_GAP
    room = width - indent
    shown = clamp(line, wrap(line, "regular", T.SLOW_SIZE, room), "regular", T.SLOW_SIZE, room, OBJECT_LINE_MAX)

    def paint(canvas, x, y, w, hits):
        canvas.drawCircle(x + T.DOT / 2, y + T.SLOW_LINE / 2, T.DOT / 2, _paint(T.PLAN_3D_DOT))
        for i, part in enumerate(shown):
            _text(canvas, part, x + indent, y + i * T.SLOW_LINE, T.SLOW_LINE, "regular", T.SLOW_SIZE, T.STATUS)
    return len(shown) * T.SLOW_LINE, paint



def _thinking_row(state):
    def paint(canvas, x, y, w, hits):
        end = _text(canvas, T.THINKING, x, y, T.STATUS_LINE, "regular", T.TEXT_SIZE, T.STATUS)
        step = int(state.spinner_phase * 3) % 3
        dx = end + T.INLINE_GAP
        for i in range(3):
            alpha = T.THINKING_ALPHAS[(i - step) % 3]
            canvas.drawCircle(dx + T.THINKING_DOT / 2, y + T.STATUS_LINE / 2, T.THINKING_DOT / 2,
                              _paint(T.ORANGE + (alpha,)))
            dx += T.THINKING_DOT + T.THINKING_DOT_GAP
        text = "%d s" % int(state.thinking_seconds)
        _meta(canvas, text, dx - T.THINKING_DOT_GAP + T.INLINE_GAP + measure(text.upper(), "mono", T.META_SIZE),
              y, T.STATUS_LINE)
    return T.STATUS_LINE, paint



def error_lines(error, weight, width):
    """(wrapped lines, lines to draw) of an error; a Code check stop always keeps its last sentence, which
    says how to turn Code check off, and cuts the reason instead."""
    lines = wrap(error, weight, T.TEXT_SIZE, width)
    shown = clamp(error, lines, weight, T.TEXT_SIZE, width)
    tail = " " + T.CHECK_OFF_TEXT
    if len(lines) > MAX_TEXT_LINES and error.endswith(tail):
        head = error[:-len(tail)]
        rest = clamp(T.CHECK_OFF_TEXT, wrap(T.CHECK_OFF_TEXT, weight, T.TEXT_SIZE, width), weight, T.TEXT_SIZE, width)
        keep = max(1, MAX_TEXT_LINES - len(rest))
        shown = clamp(head, wrap(head, weight, T.TEXT_SIZE, width), weight, T.TEXT_SIZE, width, keep) + rest
    return lines, shown



def _error_rows(state, width):
    """The error line with a red dot; one action pill sits on the same line when it fits."""
    indent = T.ERROR_DOT + T.INLINE_GAP
    weight = T.ERROR_WEIGHT.get(state.mode, "regular")
    lines, shown = error_lines(state.error, weight, width - indent)
    pills = [_pill(a, state) for a in state.actions]
    text_w = measure(shown[0], weight, T.TEXT_SIZE) if len(lines) == 1 else 0
    inline = len(lines) == 1 and len(pills) == 1 and indent + text_w + T.INLINE_GAP + pills[0][0] <= width
    height = max(T.STATUS_LINE, pills[0][1]) if inline else len(shown) * T.STATUS_LINE
    top = (height - T.STATUS_LINE) / 2 if inline else 0

    def paint(canvas, x, y, w, hits):
        canvas.drawCircle(x + T.ERROR_DOT / 2, y + top + T.STATUS_LINE / 2, T.ERROR_DOT / 2, _paint(T.DOT_FAILED))
        for i, part in enumerate(shown):
            _text(canvas, part, x + indent, y + top + i * T.STATUS_LINE, T.STATUS_LINE,
                  weight, T.TEXT_SIZE, T.ERROR_TEXT)
        if inline:
            pw, ph, item = pills[0]
            _draw_pill(canvas, x + indent + text_w + T.INLINE_GAP, y + (height - ph) / 2, pw, ph, item, hits)
    rows = [(height, paint)]
    if pills and not inline:
        rows.append(_actions_row(state, width))
    return rows



def _camera_menu_rows(state, width):
    """The open camera menu: its title, one item per camera with its hint, and how many more the sidebar lists."""
    rows = menu_rows(state.camera_menu[:T.CAMERA_MENU_MAX], T.CAMERA_MENU_TITLE, T.CAMERA_HITS, width)
    more = len(state.camera_menu) - T.CAMERA_MENU_MAX
    if more > 0:
        rows.append(_paragraph_row(T.CAMERA_MORE % more, "medium", T.HINT_SIZE, T.HINT_LINE, T.HINT, width))
    return rows



def _status_rows(state, width):
    """The rows of the bar's state: stage chips, status or reply, error, actions; the hint row on top."""
    rows = []
    if state.stages and state.mode in _RUNNING + ("done", "stopped", "error"):
        rows.append(_chips_row(state, width))
    if state.asked and state.mode in _RUNNING + ("done", "stopped", "error"):
        rows.append(_asked_row(state, width))
    if state.mode == "building" and state.error:  # a step Code check stopped
        rows.extend(_error_rows(state, width))
    elif state.mode == "building" and state.status == T.CHECKING_TEXT:
        rows.append(_checking_row(state, width))
    elif state.mode == "building" and state.status:
        rows.append(_paragraph_row(state.status, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.STATUS, width))
    elif state.mode == "waiting":
        rows.append(_thinking_row(state))
        if state.thinking_seconds >= T.SLOW_AFTER:
            rows.append(_paragraph_row(T.SLOW_TEXT, "regular", T.SLOW_SIZE, T.SLOW_LINE, T.SLOW, width))
    if state.mode in _RUNNING:
        for line in state.objects:  # one line per 3D job: "Generating the car… 2:10"
            rows.append(_object_row(line, state, width))
    elif state.mode == "done":
        if state.error:  # a run that changed nothing: the bar's own line comes before the model's reply
            rows.extend(_error_rows(dataclasses.replace(state, actions=[]), width))
        if state.reply:
            rows.append(_paragraph_row(state.reply, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.REPLY, width))
        if state.note:
            rows.append(_paragraph_row(state.note, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.REPLY, width))
        if state.camera_menu:  # above the actions, so the Play button stays under it
            rows.extend(_camera_menu_rows(state, width))
        if state.actions:
            rows.append(_actions_row(state, width, state.cost_text))
        elif state.cost_text:
            rows.append(_paragraph_row(state.cost_text.upper(), "mono", T.META_SIZE, T.META_LINE, T.META, width))
    elif state.error:
        rows.extend(_error_rows(state, width))
        if state.note:
            rows.append(_paragraph_row(state.note, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.REPLY, width))
    elif state.note:  # idle with a note: the note and its actions
        rows.append(_paragraph_row(state.note, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.REPLY, width))
        if state.actions:
            rows.append(_actions_row(state, width))
    elif state.status:
        rows.append(_paragraph_row(state.status, "regular", T.TEXT_SIZE, T.STATUS_LINE, T.STATUS, width))
    if state.focused and state.mode not in _RUNNING and _visual_lines(state, width) > 1:
        rows.insert(0, _hint_row(width))
    return rows



def _visual_lines(state, width):
    lines, first, end, _ = _input_layout(state, _text_width(state, width))
    return end - first
