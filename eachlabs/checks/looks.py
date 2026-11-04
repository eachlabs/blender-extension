"""Two looks in one scene: large material families with a picture texture next to large ones without.

Seen in a village whose town walls had photo stone while every house was flat colour. Measured from the chat's
materials and the surface of the objects that use them; nothing here knows what any object is.
"""

AREA_MIN_M2 = 6.0  # a family smaller than this is a detail and may differ
MIXED_LOW, MIXED_HIGH = 0.15, 0.85  # textured share of the large surface that reads as two looks
LISTED = 6


def has_picture(material):
    """True when the material's node tree shows an image (a photo or generated texture)."""
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return False
    return any(n.type == "TEX_IMAGE" and getattr(n, "image", None) is not None for n in tree.nodes)


def surface_m2(dimensions):
    """A box's outer surface, a rough measure of how much of a thing the camera can see."""
    x, y, z = (abs(float(v)) for v in dimensions)
    return 2.0 * (x * y + y * z + x * z)


def mixed(areas):
    """``areas``: ``{material: (surface m2, has picture)}``. ``{"textured", "plain"}`` names when the large
    families read as two looks, else ``None``."""
    large = {name: value for name, value in areas.items() if value[0] >= AREA_MIN_M2}
    total = sum(v[0] for v in large.values())
    textured = sum(v[0] for v in large.values() if v[1])
    if total <= 0 or not MIXED_LOW <= textured / total <= MIXED_HIGH:
        return None
    by_size = sorted(large.items(), key=lambda item: -item[1][0])
    return {"textured": [n for n, v in by_size if v[1]][:LISTED], "plain": [n for n, v in by_size if not v[1]][:LISTED],
            "textured_share": round(textured / total, 2)}


def mixed_looks(objects, owns):
    """``mixed`` for the chat's visible meshes and their materials, or ``None``."""
    areas = {}
    for obj in objects:
        if obj.type != "MESH" or obj.hide_render or obj.data is None:
            continue
        slots = [s.material for s in obj.material_slots if s.material is not None and owns(s.material)]
        if not slots:
            continue
        share = surface_m2(obj.dimensions) / len(slots)
        for mat in slots:
            area, picture = areas.get(mat.name, (0.0, has_picture(mat)))
            areas[mat.name] = (area + share, picture)
    return mixed(areas)
