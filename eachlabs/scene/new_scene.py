"""A fresh Blender scene for New scene, and the facts that tell Blender's startup Cube apart."""

import bpy


def blank_scene(old):
    """A new, empty Blender scene with its own World and ``old``'s render settings (engine, size, frame rate,
    colour). ``old`` and everything in it stay as they are."""
    scene = bpy.data.scenes.new(old.name)
    scene.world = bpy.data.worlds.new("World")
    src, dst = old.render, scene.render
    for name in ("engine", "resolution_x", "resolution_y", "resolution_percentage", "fps", "fps_base"):
        setattr(dst, name, getattr(src, name))
    scene.display_settings.display_device = old.display_settings.display_device
    for name in ("view_transform", "look", "exposure", "gamma"):
        try:
            setattr(scene.view_settings, name, getattr(old.view_settings, name))
        except (TypeError, ValueError):  # a look of another view transform
            pass
    scene.frame_start, scene.frame_end = old.frame_start, old.frame_end
    return scene


def cube_facts(obj, scene):
    """What ``startup_cube.matches`` compares, read from ``obj``."""
    data = obj.data
    mesh = isinstance(data, bpy.types.Mesh)
    basis = obj.matrix_basis
    hidden = obj.hide_viewport or obj.hide_render
    for layer in scene.view_layers:
        try:
            hidden = hidden or obj.hide_get(view_layer=layer)
        except RuntimeError:  # not in this view layer
            pass
    return {
        "name": obj.name, "type": obj.type, "data_name": data.name if data is not None else None,
        "vertices": [tuple(v.co) for v in data.vertices] if mesh else [],
        "faces": len(data.polygons) if mesh else 0,
        "location": tuple(basis.to_translation()), "rotation": tuple(basis.to_euler()),
        "scale": tuple(basis.to_scale()), "hidden": hidden, "modifiers": len(obj.modifiers),
        "parent": obj.parent is not None, "children": len(obj.children), "constraints": len(obj.constraints),
        "data_users": data.users if data is not None else 0,
        "animation": obj.animation_data is not None,
        "materials": [s.material.name if s.material is not None else None for s in obj.material_slots],
    }
