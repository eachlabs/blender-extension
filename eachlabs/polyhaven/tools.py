"""The model's two Poly Haven tools: their schemas, their arguments, and the run on the worker thread.

The worker downloads (no Blender there); only putting the files on the world or a material goes to the main
thread, as ``apply_free_sky`` or ``apply_free_texture`` through the same executor as every other tool.
"""

from . import catalog, fetch

SKY_STRENGTH_MAX = 10.0


def _tool(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)}}}


TOOLS = {
    "free_texture": _tool(
        "free_texture",
        "Put a free, real photo texture from Poly Haven (CC0) on one of your materials, at its real size: colour, "
        "roughness and bumps. Instant and free. Returns the texture used, or an error saying to build the look "
        "with procedural nodes instead.",
        {"description": {"type": "string", "description": "The surface, e.g. weathered red brick, oak planks."},
         "material": {"type": "string", "description": "The exact name of one of your materials."}},
        ("description", "material")),
    "free_sky": _tool(
        "free_sky",
        "Light the scene with a free, real sky picture from Poly Haven (CC0) on your own world: it gives the sky, "
        "soft light and reflections. Describe the time of day and the weather. Instant and free.",
        {"description": {"type": "string", "description": "The sky, e.g. clear night with stars, overcast noon."},
         "strength": {"type": "number", "description": "Brightness of the sky light, 0.05-10; 1 when unsure."},
         "rotation_deg": {"type": "number", "description": "Turns the sky around the vertical, in degrees."}},
        ("description",)),
}


class ArgError(ValueError):
    """Bad arguments, with a message for the model."""


def validate(name, args):
    description = args.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ArgError("%s: description is required, as a short text." % name)
    clean = {"description": " ".join(description.split())[:120]}
    if name == "free_texture":
        material = args.get("material")
        if not isinstance(material, str) or not material.strip():
            raise ArgError("free_texture: material is required, the exact name of one of your materials.")
        clean["material"] = material.strip()
        return clean
    strength = args.get("strength", 1.0)
    rotation = args.get("rotation_deg", 0.0)
    for key, value in (("strength", strength), ("rotation_deg", rotation)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ArgError("free_sky: %s is a number." % key)
    clean["strength"] = min(SKY_STRENGTH_MAX, max(0.0, float(strength)))
    clean["rotation_deg"] = float(rotation) % 360.0
    return clean


def on_worker(executor, client, folder, cancel):
    """``executor`` that handles the Poly Haven tools here: download on this thread, then apply on the main one."""
    haven = fetch.Haven(client, folder, cancel)

    def call(name, args):
        if name not in TOOLS:
            return executor(name, args)
        try:
            if name == "free_sky":
                found = haven.sky(args["description"])
                applied = {"path": found["path"], "strength": args["strength"], "rotation_deg": args["rotation_deg"]}
            else:
                found = haven.texture(args["description"])
                applied = {"maps": found["maps"], "tile_m": found["tile_m"], "material": args["material"]}
        except fetch.HavenError as exc:
            return {"ok": False, "error": str(exc)}
        result = executor("apply_" + name, dict(applied, name=found["name"], id=found["id"]))
        if isinstance(result, dict) and result.get("ok"):
            result.setdefault("credit", catalog.CREDIT)
        return result
    return call
