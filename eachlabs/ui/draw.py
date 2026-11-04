"""Drawing primitives for the bar: paints, text, icons, the spinner, the mark, flowing items and a paragraph row."""

import os

try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None

from . import tokens as T
from .fonts import _DIR, _font, _positions, _runs, clamp, measure, wrap


_RUNNING = ("building", "waiting")



def _paint(color, stroke=0.0):
    r, g, b, a = color
    p = skia.Paint(Color4f=skia.Color4f(r / 255, g / 255, b / 255, a), AntiAlias=True)
    if stroke:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke)
        p.setStrokeCap(skia.Paint.kRound_Cap)
        p.setStrokeJoin(skia.Paint.kRound_Join)
    return p



def _text(canvas, text, x, top, line, weight, size, color):
    """Draw one line of text vertically centred in a box ``line`` tall; returns the end x."""
    metrics = _font(weight, size).getMetrics()
    baseline = top + (line - (metrics.fDescent - metrics.fAscent)) / 2 - metrics.fAscent
    xs, width = _positions(text, weight, size)
    for start, end, font in _runs(text, weight, size) if xs else ():
        blob = skia.TextBlob.MakeFromPosTextH(text[start:end], [x + p for p in xs[start:end]], baseline, font)
        canvas.drawTextBlob(blob, 0, 0, _paint(color))
    return x + width



_META_INSET = T.TEXT_RIGHT - T.PAD_RIGHT  # rows end at PAD_RIGHT; right-aligned text sits further in



def _meta(canvas, text, right, top, line):
    text = text.upper()
    _text(canvas, text, right - measure(text, "mono", T.META_SIZE), top, line, "mono", T.META_SIZE, T.META)



def _icon_width(name):
    return measure(T.CODE_ICON, "mono", T.PILL_SIZE) if name == "code" else T.PILL_ICON



def _shield(canvas, x, y, s, color):
    """The Code check badge's shield with a tick, ``s`` px, top-left at (x, y)."""
    path = skia.Path()
    path.moveTo(x + s * 0.5, y + s * 0.04)
    path.lineTo(x + s * 0.9, y + s * 0.2)
    path.cubicTo(x + s * 0.9, y + s * 0.6, x + s * 0.72, y + s * 0.84, x + s * 0.5, y + s * 0.96)
    path.cubicTo(x + s * 0.28, y + s * 0.84, x + s * 0.1, y + s * 0.6, x + s * 0.1, y + s * 0.2)
    path.close()
    canvas.drawPath(path, _paint(color, stroke=s * 0.1))
    tick = skia.Path()
    tick.moveTo(x + s * 0.32, y + s * 0.5)
    tick.lineTo(x + s * 0.46, y + s * 0.64)
    tick.lineTo(x + s * 0.7, y + s * 0.38)
    canvas.drawPath(tick, _paint(color, stroke=s * 0.1))



def _icon(canvas, name, x, y, s, color):
    """A ``s``-sized icon with its top-left at (x, y)."""
    if name == "code":  # the "</>" glyphs, as in the mockup
        _text(canvas, T.CODE_ICON, x, y + (s - T.PILL_LINE) / 2, T.PILL_LINE, "mono", T.PILL_SIZE, color)
        return
    paint = _paint(color, stroke=s * 0.13)
    path = skia.Path()
    if name == "play":
        path.moveTo(x + s * 0.15, y + s * 0.05)
        path.lineTo(x + s * 0.95, y + s * 0.5)
        path.lineTo(x + s * 0.15, y + s * 0.95)
        path.close()
        canvas.drawPath(path, _paint(color))
        return
    if name == "pause":  # two bars
        for left in (0.15, 0.6):
            canvas.drawRect(skia.Rect.MakeXYWH(x + s * left, y + s * 0.08, s * 0.25, s * 0.84), _paint(color))
        return
    if name == "send":  # up arrow
        cx = x + s / 2
        path.moveTo(cx, y + s * 0.9)
        path.lineTo(cx, y + s * 0.1)
        path.moveTo(cx - s * 0.38, y + s * 0.48)
        path.lineTo(cx, y + s * 0.1)
        path.lineTo(cx + s * 0.38, y + s * 0.48)
        paint.setStrokeWidth(s * 0.15)
    elif name == "retry":  # clockwise circle open at the top right, arrow head at the top
        r = s * 0.38
        cx, cy = x + s / 2, y + s / 2
        path.addArc(skia.Rect.MakeXYWH(cx - r, cy - r, 2 * r, 2 * r), 0, 270)
        path.moveTo(cx - s * 0.2, cy - r - s * 0.22)
        path.lineTo(cx, cy - r)
        path.lineTo(cx - s * 0.2, cy - r + s * 0.22)
    elif name == "frame":  # diagonal two-way arrow
        a, b = s * 0.12, s * 0.88
        path.moveTo(x + a, y + b)
        path.lineTo(x + b, y + a)
        for px, py, dx in ((x + b, y + a, -1), (x + a, y + b, 1)):
            path.moveTo(px + dx * s * 0.38, py)
            path.lineTo(px, py)
            path.lineTo(px, py - dx * s * 0.38)
    elif name in ("chevron_up", "chevron_down"):
        top, low = (y + s * 0.3, y + s * 0.7) if name == "chevron_up" else (y + s * 0.7, y + s * 0.3)
        path.moveTo(x + s * 0.1, low)
        path.lineTo(x + s * 0.5, top)
        path.lineTo(x + s * 0.9, low)
    elif name == "undo":  # arc over the top, arrow head at the left end
        r = s * 0.34
        cx, cy = x + s * 0.55, y + s * 0.62
        path.addArc(skia.Rect.MakeXYWH(cx - r, cy - r, 2 * r, 2 * r), 0, -180)
        path.moveTo(cx - r - s * 0.26, cy - s * 0.18)
        path.lineTo(cx - r, cy + s * 0.08)
        path.lineTo(cx - r + s * 0.24, cy - s * 0.16)
    canvas.drawPath(path, paint)



def _flow(items, width, gap):
    """Place (width, height, item) boxes left to right, wrapping; returns [(x, y, item)] and height."""
    placed, x, y, line_h = [], 0.0, 0.0, 0.0
    for w, h, item in items:
        if x > 0 and x + w > width:
            x, y, line_h = 0.0, y + line_h + gap, 0.0
        placed.append((x, y, w, h, item))
        x += w + gap
        line_h = max(line_h, h)
    return placed, y + line_h



def _paragraph_row(text, weight, size, line, color, width):
    shown = clamp(text, wrap(text, weight, size, width), weight, size, width)

    def paint(canvas, x, y, w, hits):
        for i, part in enumerate(shown):
            _text(canvas, part, x, y + i * line, line, weight, size, color)
    return len(shown) * line, paint



def _spinner(canvas, x, cy, phase):
    """The stage chips' spinner, ``SPINNER`` px, its left edge at x, centred on cy."""
    r = T.SPINNER / 2 - 0.75
    canvas.drawCircle(x + T.SPINNER / 2, cy, r, _paint(T.SPINNER_RING, stroke=1.5))
    arc = skia.Path()
    arc.addArc(skia.Rect.MakeXYWH(x + T.SPINNER / 2 - r, cy - r, 2 * r, 2 * r), phase * 360 - 90, 100)
    canvas.drawPath(arc, _paint(T.ORANGE + (1.0,), stroke=1.5))



_mark = []



def _draw_mark(canvas, x, y):
    if not _mark:
        _mark.append(skia.SVGDOM.MakeFromStream(skia.Stream.MakeFromFile(os.path.join(_DIR, "assets", "mark.svg"))))
        _mark[0].setContainerSize(skia.Size(9, 9))
    canvas.save()
    canvas.translate(x, y)
    canvas.scale(T.MARK_SIZE / 9, T.MARK_SIZE / 9)
    _mark[0].render(canvas)
    canvas.restore()
