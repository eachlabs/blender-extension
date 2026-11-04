"""The bar's typefaces, fallback fonts for other scripts, and measuring and wrapping text with Skia."""

import bisect
import os
import re

try:
    import skia
except ImportError:  # The bar is not drawn; ``available()`` says so.
    skia = None

from . import tokens as T


_DIR = os.path.dirname(os.path.abspath(__file__))
_FONT_FILES = {
    "regular": ("inter", "Inter-Regular.ttf"),
    "medium": ("inter", "Inter-Medium.ttf"),
    "semibold": ("inter", "Inter-SemiBold.ttf"),
    "mono": ("geist-mono", "GeistMono-Medium.ttf"),
}
MAX_TEXT_LINES = 6  # reply, status and error rows; longer text ends in an ellipsis
ELLIPSIS = "\u2026"
FONT_DIR = os.path.join(_DIR, os.pardir, "fonts")



def available():
    """Skia imports and every bundled font loads."""
    return skia is not None and _typefaces_loaded()



_typefaces = {}  # (font dir, weight) -> Typeface | None
_fonts = {}



def _typefaces_loaded():
    # Only the bundled files: system font matching crashes skia-python 144 on macOS, and
    # ``skia.Font(None, ...)`` would go there, so a missing file must stop the bar instead.
    for weight, (folder, name) in _FONT_FILES.items():
        key = (FONT_DIR, weight)
        if key not in _typefaces:
            _typefaces[key] = skia.Typeface.MakeFromFile(os.path.join(FONT_DIR, folder, name))
        if _typefaces[key] is None:
            return False
    return True



def _typeface(weight):
    if isinstance(weight, tuple):  # ("fallback", path)
        return _fallback_face(weight[1])
    if not _typefaces_loaded():
        raise RuntimeError("The prompt bar's bundled fonts are missing from %s" % FONT_DIR)
    return _typefaces[(FONT_DIR, weight)]



_fallback_paths = []
_fallback_faces = {}  # path -> Typeface | None
_choices = {}  # (weight, char) -> index into _fallback_paths, or -1 for the bundled font



def set_fallback_fonts(paths):
    """Font files, tried in order, for characters the bundled fonts lack (CJK, emoji).

    Files only: system font matching crashes skia-python, so it is never used.
    """
    _fallback_paths[:] = list(paths)
    _choices.clear()



def _fallback_face(path):
    if path not in _fallback_faces:
        _fallback_faces[path] = skia.Typeface.MakeFromFile(path) if os.path.isfile(path) else None
    return _fallback_faces[path]



def _choice(weight, ch):
    key = (weight, ch)
    if key not in _choices:
        _choices[key] = -1
        cp = ord(ch)
        if not ch.isspace() and _typeface(weight).unicharToGlyph(cp) == 0:
            for i, path in enumerate(_fallback_paths):
                face = _fallback_face(path)
                if face is not None and face.unicharToGlyph(cp):
                    _choices[key] = i
                    break
    return _choices[key]



def _runs(text, weight, size):
    """(start, end, font) runs of ``text``, each drawn with one font."""
    runs = []
    for i, ch in enumerate(text):
        c = _choice(weight, ch)
        if runs and runs[-1][2] == c:
            runs[-1][1] = i + 1
        else:
            runs.append([i, i + 1, c])
    return [(a, b, _font(weight if c < 0 else ("fallback", _fallback_paths[c]), size)) for a, b, c in runs]



def _font(weight, size):
    key = (FONT_DIR, weight, size)
    if key not in _fonts:
        font = skia.Font(_typeface(weight), size)
        font.setSubpixel(True)
        font.setEdging(skia.Font.Edging.kAntiAlias)
        font.setHinting(skia.FontHinting.kNone)
        _fonts[key] = font
    return _fonts[key]



def _spacing(weight, size):
    return (T.META_SPACING if weight == "mono" else T.TEXT_SPACING) * size



def _positions(text, weight, size):
    """The x of each character from the start of the line, and the line width."""
    spacing = _spacing(weight, size)
    xs, x = [], 0.0
    for start, end, font in _runs(text, weight, size):
        for w in font.getWidths(font.textToGlyphs(text[start:end])):
            xs.append(x)
            x += w + spacing
    return xs, (x - spacing if xs else 0.0)



def measure(text, weight, size):
    return _positions(text, weight, size)[1]



def wrap(text, weight, size, width):
    """Lines of ``text`` that fit ``width``, as (start, end) indices; ``\\n`` always breaks."""
    lines = []
    pos = 0
    for para in text.split("\n"):
        _wrap_para(para, pos, weight, size, width, lines)
        pos += len(para) + 1
    return lines



def _wrap_para(para, offset, weight, size, width, lines):
    """Greedy word wrap; a word wider than ``width`` breaks between characters. Linear in the length:
    each character is measured once, and a line's width is a difference of running sums."""
    spacing = _spacing(weight, size)
    xs, total = _positions(para, weight, size)
    edges = xs + [total + spacing]  # edges[i]: where character i starts, spacing included

    def span(a, b):  # width of para[a:b] without its trailing spaces
        while b > a and para[b - 1].isspace():
            b -= 1
        return edges[b] - edges[a] - spacing if b > a else 0.0

    start = 0
    for m in re.finditer(r"\S+\s*|\s+", para):
        if span(start, m.end()) <= width:
            continue
        if m.start() > start:
            lines.append((offset + start, offset + m.start()))
            start = m.start()
        word_end = m.start() + len(m.group().rstrip())
        while span(start, m.end()) > width:
            cut = bisect.bisect_right(edges, edges[start] + spacing + width, start + 1, m.end() + 1) - 1
            cut = max(cut, start + 1)
            if cut >= word_end:
                break
            lines.append((offset + start, offset + cut))
            start = cut
    lines.append((offset + start, offset + len(para)))



def clamp(text, lines, weight, size, width, max_lines=MAX_TEXT_LINES):
    """The strings to draw for wrapped ``lines``: at most ``max_lines``, the last ending in an ellipsis
    when text was cut."""
    shown = [text[s:e].rstrip() for s, e in lines[:max_lines]]
    if len(lines) > max_lines:
        last = shown[-1]
        while last and measure(last + ELLIPSIS, weight, size) > width:
            last = last[:-1]
        shown[-1] = last.rstrip() + ELLIPSIS
    return shown


def cut(text, weight, size, room):
    """``text`` cut with an ellipsis so it measures at most ``room``."""
    if measure(text, weight, size) <= room:
        return text
    while text and measure(text + ELLIPSIS, weight, size) > room:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS
