"""The prompt bar drawn with Skia into premultiplied RGBA pixels, with no Blender code.

``render`` lays the bar out top to bottom (hint, stage chips, status or reply, error, actions,
input), paints it with a transparent margin for the shadow, and returns the pixels with the hit
rectangles of its controls in image pixels (rows top to bottom).
"""

import bisect
import dataclasses
import os
import re

from . import tokens as T
from .text_field import TextField, clean
from .fonts import (  # noqa: F401
    MAX_TEXT_LINES,
    _choice,
    _positions,
    _typeface,
    available,
    clamp,
    measure,
    set_fallback_fonts,
    wrap,
)
from .draw import _RUNNING, _paint  # noqa: F401
from .action_rows import (  # noqa: F401
    BUDGET_ACTIONS,
    CONSENT_ACTIONS,
    PLAN_ACTIONS,
    _ACTION_LABELS,
    _consent_rows,
    _plan_rows,
    action_label,
    play_label,
)
from .input_rows import (  # noqa: F401
    _input_layout,
    _input_row,
    _menu_rows,
    _quality_row,
    _text_width,
    hint_text,
    quality_inline,
    placeholder,
)
from .status_rows import _status_rows, error_lines  # noqa: F401
from .tab_row import tab_row

try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None


@dataclasses.dataclass
class BarState:
    mode: str = "idle"  # idle | typing | building | done | error | stopped | waiting | consent
    field: TextField = dataclasses.field(default_factory=TextField)
    stages: dict = dataclasses.field(default_factory=dict)  # stage -> todo | active | done | failed | cancelled
    status: str = ""
    round: int = 0
    total: int = 0
    reply: str = ""
    error: str = ""
    cost_text: str = ""
    thinking_seconds: float = 0.0
    actions: list = dataclasses.field(default_factory=list)  # hit ids, see bar_state._HIT_ORDER
    focused: bool = False
    caret_on: bool = True
    spinner_phase: float = 0.0  # 0..1, one turn of the spinner
    send_enabled: bool = True
    undo_stage: str = ""  # the last stage that changed the scene; names the Undo pill
    widen_label: str = ""  # the "Also let it change ..." pill: names the objects an edit was kept from
    raise_label: str = ""  # "Use 46 for this run" on a plan that needs more rounds than the person's limit
    asked: str = ""  # the prompt of the run shown or under way; the field is empty for the next one
    asked_open: bool = False  # the person clicked it: the whole prompt shows, not one line
    missing_label: str = ""  # "Build the missing things (about 8 rounds)"
    has_scene: bool = False  # the next prompt changes the current scene ("Ask for a change…")
    code_check: bool = False  # Code check is on for the running run: the badge beside the round count
    note: str = ""  # a plain line under the reply or the error, such as the hidden startup Cube
    tab: str = ""  # the chosen tab ("scene", "asset", "character"); empty draws no tab row
    tabs_enabled: bool = True  # False while a run is going: the row is dimmed and has no hits
    thing: str = ""  # on Assets and Characters, the selected thing the next prompt changes; empty: it adds one
    settings: bool = False  # the settings button on the input row (the prompt bar always shows it)
    quality_label: str = ""  # the quality pill's text: Prototype or Final; empty draws no pill
    quality_enabled: bool = True  # False while a run is going: the pill is dimmed and has no hit
    quality_menu: list = dataclasses.field(default_factory=list)  # (name, hint, chosen) per item while it is open
    plan_3d: str = ""  # the plan's 3D line: "3D: car, tree · 2 × $0.45 · about 3 min"
    plan_code: str = ""  # its code line
    plan_looks: str = ""  # its line for the concept picture and the textures, when they are on
    plan_chips: list = dataclasses.field(default_factory=list)  # (index, label, "3d" | "code", cached) per item
    plan_note: str = ""  # the hint under the chips, or why the last click did nothing
    objects: list = dataclasses.field(default_factory=list)  # a line per 3D job while a run goes
    play_camera: str = ""  # the camera Play looks through ("Play as Camera"); empty: plain Play, no camera menu
    playing: bool = False  # the animation plays: the Play button reads Pause
    camera_menu: list = dataclasses.field(default_factory=list)  # (name, hint, chosen) per camera while it is open


@dataclasses.dataclass
class Frame:
    rgba: bytes  # premultiplied RGBA, rows top to bottom
    width: int
    height: int
    hits: dict  # id -> (x, y, w, h) in image pixels
    bar_rect: tuple  # the bar inside the image, without the shadow margin


# -- fonts and text ------------------------------------------------------------------------------


# -- icons ----------------------------------------------------------------------------------------


# -- layout ---------------------------------------------------------------------------------------
# Each row is (height, paint) where paint(canvas, x, y, w, hits) draws it with its top-left at (x, y).


def _rows(state, width):
    """Every row above the input row, top to bottom."""
    if state.quality_menu and state.mode not in _RUNNING + ("consent", "plan"):
        rows = _menu_rows(state, width)
    elif state.mode == "plan":
        rows = _plan_rows(state, width)
    elif state.mode == "consent":
        rows = _consent_rows(state, width)
    else:
        rows = _status_rows(state, width)
    if state.tab and state.mode not in ("consent", "plan") and not state.quality_menu:
        rows.append(tab_row(state, width))
    if state.quality_label and not quality_inline(state, width):
        rows.append(_quality_row(state, width))
    return rows


def index_at(state, width, x, y):
    """Caret index for a click at (x, y): logical px from the top-left of the ``field`` hit rect."""
    f = state.field
    if not f.text:
        return 0
    lines, first, end, _ = _input_layout(state, _text_width(state, width - T.PAD_LEFT - T.PAD_RIGHT))
    shown = end - first
    top = (max(T.BUTTON, shown * T.TEXT_LINE) - shown * T.TEXT_LINE) / 2
    start, stop = lines[first + min(max(int((y - top) // T.TEXT_LINE), 0), shown - 1)]
    xs, w = _positions(f.text[start:stop], "regular", T.TEXT_SIZE)
    edges = xs + [w]
    return start + min(range(len(edges)), key=lambda i: abs(edges[i] - x))


# -- render ---------------------------------------------------------------------------------------

def _px(rect, scale):
    x, y, w, h = rect
    x0, y0 = round(x * scale), round(y * scale)
    return (x0, y0, round((x + w) * scale) - x0, round((y + h) * scale) - y0)


def render(state, width, scale):
    if skia is None:
        raise RuntimeError("The prompt bar needs skia-python")
    _typeface("regular")  # raises when a bundled font is missing
    # Model text can hold lone surrogates (JSON "\\ud800"), which Skia cannot encode.
    state = dataclasses.replace(state, reply=clean(state.reply), error=clean(state.error), status=clean(state.status),
                                note=clean(state.note), plan_3d=clean(state.plan_3d), plan_code=clean(state.plan_code),
                                plan_note=clean(state.plan_note), plan_looks=clean(state.plan_looks),
                                plan_chips=[(i, clean(t), m, c) for i, t, m, c in state.plan_chips],
                                objects=[" ".join(clean(line).split()) for line in state.objects])
    inner = width - T.PAD_LEFT - T.PAD_RIGHT
    rows = _rows(state, inner)
    input_h, input_paint = _input_row(state, inner)
    pad_top = T.PAD_TOP_ROWS if rows else T.PAD_TOP
    height = pad_top + sum(h + T.ROW_GAP for h, _ in rows) + input_h + T.PAD_BOTTOM
    radius = height / 2 if not rows and input_h <= T.BUTTON else T.RADIUS_ROWS
    bar = (T.MARGIN_X, T.MARGIN_TOP, width, height)

    img_w = round((width + 2 * T.MARGIN_X) * scale)
    img_h = round((height + T.MARGIN_TOP + T.MARGIN_BOTTOM) * scale)
    surface = skia.Surface.MakeRaster(skia.ImageInfo.Make(img_w, img_h, skia.kRGBA_8888_ColorType,
                                                          skia.kPremul_AlphaType))
    canvas = surface.getCanvas()
    canvas.clear(skia.Color4f(0, 0, 0, 0))
    canvas.scale(scale, scale)

    shape = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(*bar), radius, radius)
    canvas.save()
    canvas.clipRRect(shape, skia.ClipOp.kDifference, True)
    shadow = _paint(T.SHADOW)
    shadow.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, T.SHADOW_BLUR / 2))
    canvas.drawRRect(shape.makeOffset(0, T.SHADOW_DY), shadow)
    canvas.restore()
    canvas.drawRRect(shape, _paint(T.BAR_FILL))
    edge = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(bar[0] + 0.5, bar[1] + 0.5, width - 1, height - 1),
                                 radius - 0.5, radius - 0.5)
    canvas.drawRRect(edge, _paint(T.BAR_FOCUS if state.focused else T.BAR_STROKE, stroke=1))

    hits = {}
    x, y = bar[0] + T.PAD_LEFT, bar[1] + pad_top
    for h, paint in rows:
        paint(canvas, x, y, inner, hits)
        y += h + T.ROW_GAP
    input_paint(canvas, x, y, inner, hits)

    hits = {k: _px(v, scale) for k, v in hits.items()}
    hits["bar"] = _px(bar, scale)
    rgba = surface.makeImageSnapshot().tobytes()
    return Frame(rgba=rgba, width=img_w, height=img_h, hits=hits, bar_rect=hits["bar"])


def save_png(frame, path):
    image = skia.Image.frombytes(frame.rgba, skia.ISize(frame.width, frame.height), skia.kRGBA_8888_ColorType,
                                 skia.kPremul_AlphaType)
    image.save(path, skia.kPNG)
