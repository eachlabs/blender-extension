"""The answer to a failed step's error, looked up by the add-on so the model's next step does not guess again.

The model rarely asks blender_api before a step; an error that names a missing attribute or a missing key is the
moment it needs the answer. ``hint`` reads the error text and returns one line (or ``""``): close names for a missing
attribute, read from the live type, and what bmesh's create operators return. Main thread only, like the step.
"""

import difflib
import re

_ATTRIBUTE = re.compile(r"AttributeError: '([A-Za-z_][\w.]*)' object has no attribute '(\w+)'")
_TYPE_ATTRIBUTE = re.compile(r"AttributeError: type object '([A-Za-z_][\w.]*)' has no attribute '(\w+)'")
_KEY = re.compile(r"KeyError: '(\w+)'")
CLOSE_MAX = 6
CREATE_KEYS = ("faces", "edges")  # keys the model expects from bmesh.ops.create_* that they do not return


def _find_type(name):
    """The class named ``name`` among Blender's types, mathutils and bmesh's types, or ``None``."""
    import bmesh
    import bpy
    import mathutils
    for space in (bpy.types, mathutils, bmesh.types, mathutils.bvhtree, mathutils.geometry):
        found = getattr(space, name.rsplit(".", 1)[-1], None)
        if isinstance(found, type):
            return found
    return None


def close_names(wanted, names):
    """Up to ``CLOSE_MAX`` public names like ``wanted``; a name that contains it, or that it contains, comes first."""
    public = sorted({n for n in names if not n.startswith("_")})
    within = [n for n in public if wanted.lower() in n.lower() or n.lower() in wanted.lower()]
    near = difflib.get_close_matches(wanted, public, CLOSE_MAX, 0.5)
    return list(dict.fromkeys(within + near))[:CLOSE_MAX]


def hint(error, code=""):
    """One line that answers the error, or ``""``."""
    text = str(error or "")
    found = _ATTRIBUTE.search(text) or _TYPE_ATTRIBUTE.search(text)
    if found:
        type_name, wanted = found.groups()
        kind = _find_type(type_name)
        if kind is not None:
            close = close_names(wanted, dir(kind))
            if close:
                return "%s has no %s. Names it has that are close: %s." % (type_name, wanted, ", ".join(close))
            return "%s has no %s; ask blender_api for %s to see what it has." % (type_name, wanted, type_name)
    found = _KEY.search(text)
    if found and found.group(1) in CREATE_KEYS and "bmesh.ops.create_" in str(code or ""):
        return ("bmesh.ops.create_cube, create_cone, create_uvsphere and create_grid return only {\"verts\": [...]}; "
                "take the faces with list({f for v in ret[\"verts\"] for f in v.link_faces}).")
    return ""
