"""The three tools the chat model can call: JSON schemas, argument rules and row labels.

Units are metres, Z is up, the ground is at z = 0. Nothing here touches Blender.
"""

import re

from .polyhaven import tools as haven_tools
from .checks.free_space import FREE_AREAS, FREE_CELLS, fits, free_areas  # noqa: F401
from .checks.part_groups import ASSEMBLY_MIN, _groups, _label, _overlap, _plain, _tokens  # noqa: F401
from .checks.loose_parts import LOOSE_MAX, LOOSE_NAMES, TOUCH_GAP, loose_parts  # noqa: F401
from .checks.overlaps import (  # noqa: F401
    FOOTPRINT_SHARE,
    GROUND_RATIO,
    INSIDE_SHARE,
    LIFTED,
    ON_GAP,
    OVERLAP_MAX,
    SOLID_MIN,
    STAND_HEIGHT,
    _first_word,
    _footprint_share,
    _ground_like,
    _shared,
    _things,
    _union,
    _volume,
    overlaps,
)

LABEL_CHARS = 48


class ToolArgError(ValueError):
    """Bad tool arguments. The message is written for the model to act on."""


def _tool(name, description, properties=None, required=()):
    return {"type": "function", "function": {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": list(required)},
    }}


TOOLS = {
    "run_python": _tool(
        "run_python",
        "Run one step of Blender Python in the scene. Available: bpy, bmesh, mathutils, math, random, and scene "
        "(the scene you build in); no other imports. Start the code with a one-line # comment saying what the step builds. Returns a summary of "
        "what the step created, removed or changed, anything it printed, or the error.",
        {"code": {"type": "string", "description": "Blender Python for one part of the scene."}},
        ("code",),
    ),
    "read_scene": _tool(
        "read_scene",
        "List every object you built (name, type, location, dimensions in metres, world bounds when the geometry "
        "is away from the origin, extent: the centre and size in the world of a thing of many parts, materials, "
        "modifiers), the lights, the world, the scene camera, its frame "
        "range and how far it moves from the first to the last frame (move_m), and the objects that are not yours. Three or more objects of one kind are one entry: the first and "
        "the last name, the name pattern (# for numbers), the count and the space they fill. loose_parts lists "
        "the figures and objects whose parts do not touch (one parent and its children, or names such as "
        "Person_A_*), with the parts apart from the rest. overlaps lists the things of yours that stand on or "
        "inside another thing of yours, with the part they touch. crossing lists two separate things of yours whose "
        "surfaces pass through each other; hidden_parts lists parts that lie mostly inside a bigger part of the "
        "same thing; ends_closed names meshes whose small flat open ends the add-on closed. generated_3d, when there is one, lists the 3D "
        "models ordered for the approved objects: pending until it arrives, then ready with the names of its "
        "copies, or failed.",
    ),
    "camera_view": _tool(
        "camera_view",
        "What the scene camera sees at the first and the last frame, and how far it moves between them "
        "(camera_move_m): each of your objects in view with its share "
        "of the frame and whether the frame cuts it off, the empty share of the frame, objects behind the "
        "camera, the share and count of objects that are not yours in view (not_yours_cover_pct, "
        "not_yours_in_view), whether the camera is enclosed by your objects on all four sides "
        "(camera_enclosed), and the first object between the camera and its aim point (toward_target). Measured "
        "from bounding boxes and rays, so it is approximate.",
    ),
    "generate_texture": _tool(
        "generate_texture",
        "Order a real, seamless photo texture for one of your materials. It is drawn in about a minute and then set "
        "as the material's Base Color, box-projected so one tile covers tile_m metres; keep working meanwhile.",
        {"description": {"type": "string", "description": "What the surface looks like, e.g. weathered red brick."},
         "material": {"type": "string", "description": "The exact name of one of your materials."},
         "tile_m": {"type": "number", "description": "Metres one tile of the texture covers, 0.3-4; 1 when unsure."}},
        ("description", "material"),
    ),
    "look_at": _tool(
        "look_at",
        "Look at the scene from four sides with temporary cameras (the scene camera stays as it is): everything "
        "you built, or one of your things and its parts alone. hide leaves named things of yours out of the "
        "pictures; mode xray shows surfaces half see-through, to see what lies inside what. Use it to check the "
        "back of a thing, a part hidden inside another, or what a blocking thing covers.",
        {"object": {"type": "string", "description": "One of your root objects; leave out for the whole scene."},
         "hide": {"type": "array", "items": {"type": "string"}, "description": "Names of your things to leave out."},
         "mode": {"type": "string", "enum": ["solid", "xray"], "description": "solid (default) or xray."}},
    ),
    "blender_api": _tool(
        "blender_api",
        "Look up this Blender's own API before guessing: a type's properties with their kinds, enum values and "
        "short descriptions, read live from the running Blender. Ask for a type (Light, EeveeSettings, "
        "ShaderNodeTexNoise) or one property (Light.type, SceneEEVEE.use_raytracing). It runs nothing.",
        {"name": {"type": "string", "description": "A bpy.types name, or Type.property."}},
        ("name",),
    ),
}
TOOLS.update(haven_tools.TOOLS)
BASE_TOOLS = ("run_python", "read_scene", "camera_view", "blender_api")  # every stage's; others are offered apart


def not_a_tool(name):
    return "%s is not a tool; use run_python, read_scene, camera_view or blender_api" % name


def validate(name, args):
    """Return a clean copy of ``args``, or raise ``ToolArgError``."""
    if name not in TOOLS:
        raise ToolArgError(not_a_tool(name))
    if not isinstance(args, dict):
        raise ToolArgError("%s: arguments must be a JSON object." % name)
    fields = TOOLS[name]["function"]["parameters"]["properties"]
    unknown = [k for k in args if k not in fields]
    if unknown:
        raise ToolArgError("%s: unknown argument %s. Valid arguments: %s." % (
            name, ", ".join(unknown), ", ".join(fields) or "none"))
    if name in haven_tools.TOOLS:
        try:
            return haven_tools.validate(name, args)
        except haven_tools.ArgError as exc:
            raise ToolArgError(str(exc)) from exc
    if name == "run_python":
        code = args.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ToolArgError("run_python: code is required, as a string of Blender Python.")
        return {"code": code}
    if name == "generate_texture":
        description, material = args.get("description"), args.get("material")
        if not isinstance(description, str) or not description.strip():
            raise ToolArgError("generate_texture: description is required, as a short text.")
        if not isinstance(material, str) or not material.strip():
            raise ToolArgError("generate_texture: material is required, the exact name of one of your materials.")
        tile = args.get("tile_m", 1.0)
        if isinstance(tile, bool) or not isinstance(tile, (int, float)) or not 0.05 <= tile <= 20:
            raise ToolArgError("generate_texture: tile_m is a number of metres, 0.3-4.")
        return {"description": " ".join(description.split())[:200], "material": material.strip(),
                "tile_m": float(tile)}
    if name == "blender_api":
        value = args.get("name")
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            raise ToolArgError("blender_api: name is a bpy.types name or Type.property, e.g. Light.type.")
        return {"name": value.strip()}
    if name == "look_at":
        target, hide, mode = args.get("object"), args.get("hide", []), args.get("mode", "solid")
        if target is not None and (not isinstance(target, str) or not target.strip()):
            raise ToolArgError("look_at: object is the exact name of one of your root objects, or left out.")
        if not isinstance(hide, list) or not all(isinstance(h, str) for h in hide):
            raise ToolArgError("look_at: hide is a list of names of your objects.")
        if mode not in ("solid", "xray"):
            raise ToolArgError("look_at: mode is solid or xray.")
        return {"object": target.strip() if target else None, "hide": [h.strip() for h in hide][:12], "mode": mode}
    return {}


def first_comment(code):
    """The text of the code's first ``#`` comment line, or ``""``."""
    for line in (code or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            return " ".join(line.lstrip("#").split())
        return ""
    return ""


def summary(name, args):
    """Short label for the chat row, at most ``LABEL_CHARS`` characters."""
    args = args or {}
    if name == "run_python":
        code = args.get("code") or ""
        text = first_comment(code)
        if not text:
            lines = len([line for line in code.splitlines() if line.strip()])
            text = "run code · %d line%s" % (lines, "" if lines == 1 else "s")
    elif name == "read_scene":
        text = "read the scene"
    elif name == "camera_view":
        text = "check the camera view"
    elif name == "generate_texture":
        text = "texture: %s" % args.get("description", "")
    elif name == "look_at":
        text = "look at %s from four sides" % (args.get("object") or "the scene")
    elif name == "blender_api":
        text = "look up %s" % args.get("name", "the API")
    elif name in haven_tools.TOOLS:
        text = "%s: %s" % ("sky" if name == "free_sky" else "free texture", args.get("description", ""))
    else:
        text = name
    if len(text) > LABEL_CHARS:
        text = text[:LABEL_CHARS - 1] + "…"
    return text
