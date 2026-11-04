"""Glow that reads as flat white shapes: strong emission in a near-white colour with nothing varying it.

Seen in a cabin whose fire stayed sharp white cones although the rules asked for warm, varied flames. Real light
sources are tinted, and fire varies in colour and brightness; a strong untinted emitter with a plain colour input
renders as a cut-out. Measured from the chat's materials; nothing here knows what any object is.
"""

STRENGTH_MIN = 5.0  # emission strength from which a flat colour reads as a cut-out
WHITE_SATURATION = 0.2  # below this the colour reads as white
WHITE_VALUE = 0.8  # and above this brightness
# A strongly coloured glow brighter than this (strength times its brightest channel) washes out to white under
# AgX and Filmic: the cabin's amber flames at strength 5 rendered as pale crystals. Near-white glows (a bulb) are
# meant to read white and are not listed for it.
WASHED_OUT = 3.0
COLOURED = 0.5  # saturation from which a glow is meant to show its colour
LISTED = 6


def is_harsh(color, strength, varied):
    """``color``: linear RGB; ``varied``: the colour or strength comes from another node (a noise, a ramp)."""
    if varied or strength < STRENGTH_MIN:
        return False
    high, low = max(color), min(color)
    if high < WHITE_VALUE:
        return False
    return (high - low) / high < WHITE_SATURATION


def washes_out(colors, strength):
    """True when a glow meant to show a colour is so bright it renders white. ``colors``: the colours it can take
    (its own, or every stop of the ramp it comes through)."""
    for color in colors:
        high, low = max(color), min(color)
        if high > 0 and (high - low) / high >= COLOURED and high * strength > WASHED_OUT:
            return True
    return False


def _colours(socket):
    """The colours a colour socket can take: its own value, or the stops of a Color Ramp feeding it; ``None`` when
    another node decides it."""
    if not socket.is_linked:
        return [tuple(socket.default_value)[:3]]
    node = socket.links[0].from_node
    if node.type == "VALTORGB":
        return [tuple(e.color)[:3] for e in node.color_ramp.elements]
    return None


def _emission_inputs(material):
    """``(colour socket, strength socket)`` pairs of the material's emitting nodes."""
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return []
    pairs = []
    for node in tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            color, strength = node.inputs.get("Emission Color") or node.inputs.get("Emission"), \
                node.inputs.get("Emission Strength")
        elif node.type == "EMISSION":
            color, strength = node.inputs.get("Color"), node.inputs.get("Strength")
        else:
            continue
        if color is not None and strength is not None:
            pairs.append((color, strength))
    return pairs


def harsh_emitters(objects, owns):
    """``[{"material", "objects", "strength"}]`` for the chat's strong near-white emitters nothing varies."""
    users = {}
    for obj in objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        for slot in obj.material_slots:
            if slot.material is not None and owns(slot.material):
                users.setdefault(slot.material.name, (slot.material, []))[1].append(obj.name)
    found = []
    for name, (material, names) in users.items():
        for color, strength in _emission_inputs(material):
            varied = color.is_linked or strength.is_linked
            value = float(strength.default_value)
            colours = _colours(color)
            if is_harsh(tuple(color.default_value)[:3], value, varied):
                found.append({"material": name, "objects": names[:3], "strength": round(value, 1)})
                break
            if not strength.is_linked and colours is not None and washes_out(colours, value):
                found.append({"material": name, "objects": names[:3], "strength": round(value, 1),
                              "washes_out": True})
                break
    return found[:LISTED]
