"""Whether a thing has the colour the request asked for: the plan gives each such thing's colour, and the colour of
its biggest surfaces is compared with it. Seen on a cabin whose "red sofa" came out a dull brown. The colour maths
is pure; ``off_colours`` reads the objects' materials in Blender."""

import math

DIFFERENT = 30.0  # colour difference (CIE76 on Lab) over which a surface is not the asked colour
SHARE_MIN = 0.25  # a material counts when it covers at least this share of the thing's surface
LIST_MAX = 6


def hex_rgb(text):
    """``"#b01818"`` as sRGB 0-1, or ``None``."""
    text = str(text or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None


def hex_of(srgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255))) for c in srgb)


def to_srgb(linear):
    """A linear colour (what a material holds) as sRGB 0-1 (what a person names)."""
    return tuple(12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
                 for c in (max(0.0, min(1.0, float(v))) for v in linear[:3]))


def lab(srgb):
    def linear(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(c) for c in srgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def difference(a, b):
    """How far apart two sRGB colours look (CIE76 on Lab)."""
    return math.dist(lab(a), lab(b))


def closest(asked, surfaces):
    """Of ``surfaces`` (``[(share, srgb)]``), the colour nearest ``asked`` among those covering ``SHARE_MIN`` or
    more, and its difference; ``(None, None)`` when there are none."""
    big = [c for share, c in surfaces if share >= SHARE_MIN] or [c for _s, c in sorted(surfaces, reverse=True)[:1]]
    if not big:
        return None, None
    best = min(big, key=lambda c: difference(asked, c))
    return best, difference(asked, best)


def _base_colour(mat):
    if mat is None:
        return (0.8, 0.8, 0.8)
    if mat.use_nodes and mat.node_tree is not None:
        node = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if node is not None and not node.inputs["Base Color"].is_linked:
            return tuple(node.inputs["Base Color"].default_value[:3])
    return tuple(mat.diffuse_color[:3])


def surfaces(objects):
    """``[(share of the surface, sRGB)]`` per material of the mesh ``objects``, by face area."""
    areas = {}
    for obj in objects:
        if obj.type != "MESH" or obj.data is None or not obj.data.polygons:
            continue
        mesh = obj.data
        count = len(mesh.polygons)
        size, index = [0.0] * count, [0] * count
        mesh.polygons.foreach_get("area", size)
        mesh.polygons.foreach_get("material_index", index)
        scale = abs(obj.matrix_world.to_scale()[0] * obj.matrix_world.to_scale()[1])
        slots = [s.material for s in obj.material_slots]
        for area, i in zip(size, index):
            mat = slots[i] if i < len(slots) else None
            key = mat.name if mat is not None else ""
            if key not in areas:
                areas[key] = [0.0, to_srgb(_base_colour(mat))]
            areas[key][0] += area * scale
    total = sum(a for a, _c in areas.values()) or 1.0
    return [(a / total, c) for a, c in areas.values()]


def off_colours(roots, asked, words_of):
    """``[{"thing", "asked", "has"}]`` for each asked colour (``{item name: "#rrggbb"}``) that the thing whose root
    is named after the item does not have; ``words_of(name)`` gives a name's plain words."""
    found = []
    for item, colour in asked.items():
        want = hex_rgb(colour)
        item_words = set(words_of(item))
        if want is None or not item_words:
            continue
        for root in roots:
            if not item_words <= set(words_of(root.name)):
                continue
            has, gap = closest(want, surfaces([root] + list(root.children_recursive)))
            if gap is not None and gap > DIFFERENT:
                found.append({"thing": root.name, "asked": colour, "has": hex_of(has)})
            break
    return found[:LIST_MAX]
