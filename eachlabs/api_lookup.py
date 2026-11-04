"""The model's Blender API lookup: what a type has, read live from Blender's own type data (RNA), for this version.

A step that guesses a property or an enum value fails and costs a round; the answer here is exact for the Blender the
person runs. Read only: it lists names, types, enum values and short descriptions, never runs anything. ``lookup`` is
called on the main thread; ``resolve`` and ``describe`` take plain values, so the unit tests cover them.
"""

CHARS_MAX = 3500  # longest answer, so a lookup costs about a step's reply
PROPS_MAX = 60
ENUM_MAX = 40
DESC_CHARS = 70


def split_name(text):
    """``("Light", "type")`` from "Light.type", "bpy.types.Light.type" or "bpy.types.Light"; ``(type, None)`` for a
    type alone."""
    text = " ".join(str(text or "").split()).replace(" ", "")
    for prefix in ("bpy.types.", "types."):
        if text.startswith(prefix):
            text = text[len(prefix):]
    head, _dot, prop = text.partition(".")
    return head, (prop or None)


def describe(type_name, props, version, prop=None):
    """The answer text. ``props``: ``[{"id", "type", "enum", "desc", "readonly"}]``; ``prop`` names one of them."""
    lines = ["Blender %s, bpy.types.%s:" % (version, type_name)]
    chosen = [p for p in props if prop is None or p["id"] == prop]
    if prop is not None and not chosen:
        near = [p["id"] for p in props if prop.lower() in p["id"].lower()][:8]
        return "bpy.types.%s has no property %s.%s" % (
            type_name, prop, (" Close names: %s." % ", ".join(near)) if near else
            " Its properties: %s." % ", ".join(p["id"] for p in props[:PROPS_MAX]))
    for p in chosen[:PROPS_MAX]:
        line = "- %s: %s%s" % (p["id"], p["type"], " (read only)" if p.get("readonly") else "")
        if p.get("enum"):
            line += ", one of " + ", ".join(p["enum"][:ENUM_MAX])
        if p.get("desc"):
            line += " — " + p["desc"][:DESC_CHARS]
        lines.append(line)
    text = "\n".join(lines)
    return text if len(text) <= CHARS_MAX else text[:CHARS_MAX - 1] + "…"


def _props(rna):
    out = []
    for p in rna.properties:
        if p.identifier == "rna_type":
            continue
        kind = p.type.lower()
        if p.type == "POINTER" and getattr(p, "fixed_type", None) is not None:
            kind = "pointer to %s" % p.fixed_type.identifier
        elif p.type == "COLLECTION" and getattr(p, "fixed_type", None) is not None:
            kind = "collection of %s" % p.fixed_type.identifier
        elif getattr(p, "array_length", 0):
            kind = "%s[%d]" % (kind, p.array_length)
        entry = {"id": p.identifier, "type": kind, "desc": " ".join((p.description or "").split()),
                 "readonly": bool(p.is_readonly)}
        if p.type == "ENUM":
            entry["enum"] = [item.identifier for item in p.enum_items] or ["(set at run time)"]
        out.append(entry)
    return out


def lookup(name):
    """Main thread: the answer for ``name`` ("Light.type", "bpy.types.EeveeSettings")."""
    import bpy

    type_name, prop = split_name(name)
    cls = getattr(bpy.types, type_name, None) if type_name else None
    if cls is None or not hasattr(cls, "bl_rna"):
        near = [n for n in dir(bpy.types) if type_name and type_name.lower() in n.lower()][:10]
        return {"answer": "There is no bpy.types.%s.%s" % (
            type_name, (" Close names: %s." % ", ".join(near)) if near else "")}
    version = ".".join(str(v) for v in bpy.app.version)
    answer = describe(type_name, _props(cls.bl_rna), version, prop)
    if prop is None and issubclass(cls, bpy.types.ShaderNode):
        answer = (_sockets(bpy, type_name) + "\n" + answer)[:CHARS_MAX]  # the sockets first: they are what steps guess
    return {"answer": answer}


def _sockets(bpy, type_name):
    """A shader node's input and output socket names, from a node made in a throwaway material and removed."""
    material = bpy.data.materials.new("eachlabs api lookup")
    try:
        material.use_nodes = True
        node = material.node_tree.nodes.new(type_name)
        ins = ", ".join('"%s"' % s.name for s in node.inputs)
        outs = ", ".join('"%s"' % s.name for s in node.outputs)
        return "Inputs: %s\nOutputs: %s" % (ins or "none", outs or "none")
    except (RuntimeError, TypeError):  # a node this tree type does not take
        return ""
    finally:
        bpy.data.materials.remove(material)
