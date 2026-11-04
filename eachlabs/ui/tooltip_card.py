"""The tooltip card the bar shows over a control the mouse rests on: its lines, where it sits in the 3D view, and its
pixels. No Blender code."""

import dataclasses

from .fonts import measure, wrap
from . import tokens as T
from .draw import _paint, _text

try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None


@dataclasses.dataclass
class Card:
    rgba: bytes  # premultiplied RGBA, rows top to bottom
    width: int
    height: int


def lines(text):
    """The card's lines: ``text`` wrapped at ``TIP_MAX`` logical px less the padding."""
    room = T.TIP_MAX - 2 * T.TIP_PAD_X
    return [text[s:e].rstrip() for s, e in wrap(text, "regular", T.TIP_SIZE, room)]


def size(text):
    """``(width, height)`` of the card in logical px: as wide as its longest line, at most ``TIP_MAX``."""
    shown = lines(text)
    widest = max((measure(line, "regular", T.TIP_SIZE) for line in shown), default=0)
    return (min(T.TIP_MAX, int(widest + 0.999) + 2 * T.TIP_PAD_X),
            len(shown) * T.TIP_LINE + 2 * T.TIP_PAD_Y)


def place(card, control, region, scale, left=0, right=0):
    """Bottom-left of a card ``(w, h)`` px in region px (y up): centred over ``control`` (x, bottom, w, h, region
    px), ``TIP_GAP`` above it, or below it when there is no room above; kept inside the width the toolbar (``left``
    px) and sidebar (``right`` px) leave free. It never covers the control."""
    w, h = card
    cx, cy, cw, ch = control
    region_w, region_h = region
    edge = round(T.TIP_EDGE * scale)
    gap = round(T.TIP_GAP * scale)
    x = cx + (cw - w) // 2
    x = max(left + edge, min(x, region_w - right - edge - w))
    y = cy + ch + gap
    if y + h > region_h - edge and cy - gap - h >= edge:
        y = cy - gap - h
    return x, y


def render(text, scale):
    """The card's pixels for ``text`` at ``scale``."""
    w, h = size(text)
    img_w, img_h = round(w * scale), round(h * scale)
    surface = skia.Surface.MakeRaster(skia.ImageInfo.Make(img_w, img_h, skia.kRGBA_8888_ColorType,
                                                          skia.kPremul_AlphaType))
    canvas = surface.getCanvas()
    canvas.clear(skia.Color4f(0, 0, 0, 0))
    canvas.scale(scale, scale)
    shape = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(0, 0, w, h), T.TIP_RADIUS, T.TIP_RADIUS)
    canvas.drawRRect(shape, _paint(T.TIP_FILL))
    edge = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(0.5, 0.5, w - 1, h - 1), T.TIP_RADIUS - 0.5, T.TIP_RADIUS - 0.5)
    canvas.drawRRect(edge, _paint(T.BAR_STROKE, stroke=1))
    for i, line in enumerate(lines(text)):
        _text(canvas, line, T.TIP_PAD_X, T.TIP_PAD_Y + i * T.TIP_LINE, T.TIP_LINE, "regular", T.TIP_SIZE, T.BODY)
    return Card(rgba=surface.makeImageSnapshot().tobytes(), width=img_w, height=img_h)
