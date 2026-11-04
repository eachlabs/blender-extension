"""Putting downloaded Poly Haven files on the chat's world and materials. Main thread only."""

import math

import bpy

from .. import textures

SKY_WORLD = "Eachlabs sky"
SKY_NODE = "Eachlabs sky"
NORMAL_STRENGTH = 0.6  # Poly Haven's normal maps are strong for objects seen from a few metres


ZENITH_ROWS = (0.0, 0.2)  # share of the picture's height, from the top, averaged for the colour overhead
HORIZON_ROWS = (0.44, 0.5)  # rows just above the horizon, averaged for the colour at the horizon
SAMPLE_STEP = 8  # every n-th pixel is read for the averages; a 2k sky has 2 million


def _band_colours(image):
    """``(zenith, horizon)``: average RGB of the sky picture's top rows and of the rows just above its horizon."""
    width, height = image.size
    if not width or not height:
        return (0.35, 0.45, 0.6), (0.7, 0.7, 0.7)
    pixels = [0.0] * (width * height * 4)
    image.pixels.foreach_get(pixels)

    def band(rows):
        # Blender stores rows bottom first; the top of the picture is the last rows
        start, end = int(height * (1 - rows[1])), int(height * (1 - rows[0]))
        total, count = [0.0, 0.0, 0.0], 0
        for row in range(start, max(start + 1, end), SAMPLE_STEP // 2 or 1):
            base = row * width * 4
            for col in range(0, width, SAMPLE_STEP):
                i = base + col * 4
                total[0] += pixels[i]
                total[1] += pixels[i + 1]
                total[2] += pixels[i + 2]
                count += 1
        return tuple(c / max(count, 1) for c in total)

    return band(ZENITH_ROWS), band(HORIZON_ROWS)


def set_sky(build, path, strength=1.0, rotation_deg=0.0):
    """Light the scene with the sky picture at ``path`` on a world of the chat's own; returns the world's name.

    The picture lights the scene and shows in reflections, but the camera never sees it: past the chat's ground the
    camera sees a gradient from the picture's own horizon colour to its colour overhead. A sky picture is a photo of
    a real place, and seen directly it shows moorland or desert behind the scene."""
    scene = build.scene
    world = scene.world if scene.world is not None and build.owns(scene.world) else None
    if world is None:
        world = bpy.data.worlds.new(SKY_WORLD)
        build.tag(world)
    if world.node_tree is None:
        world.use_nodes = True
    tree = world.node_tree
    for node in [n for n in tree.nodes if n.name.startswith(SKY_NODE)]:
        tree.nodes.remove(node)
    background = next((n for n in tree.nodes if n.type == "BACKGROUND"), None) or tree.nodes.new(
        "ShaderNodeBackground")
    output = next((n for n in tree.nodes if n.type == "OUTPUT_WORLD"), None) or tree.nodes.new("ShaderNodeOutputWorld")
    image = bpy.data.images.load(path, check_existing=True)
    build.tag(image)
    coords = tree.nodes.new("ShaderNodeTexCoord")
    mapping = tree.nodes.new("ShaderNodeMapping")
    sky = tree.nodes.new("ShaderNodeTexEnvironment")
    height = tree.nodes.new("ShaderNodeSeparateXYZ")
    blend = tree.nodes.new("ShaderNodeMapRange")
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    seen = tree.nodes.new("ShaderNodeBackground")
    camera = tree.nodes.new("ShaderNodeLightPath")
    mix = tree.nodes.new("ShaderNodeMixShader")
    for node, label in ((coords, "coordinates"), (mapping, "turn"), (sky, "picture"), (height, "height"),
                        (blend, "horizon to zenith"), (ramp, "camera colours"), (seen, "camera sky"),
                        (camera, "camera rays"), (mix, "camera mix")):
        node.name = node.label = "%s %s" % (SKY_NODE, label)
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(float(rotation_deg or 0.0)))
    sky.image = image
    zenith, horizon = _band_colours(image)
    ramp.color_ramp.elements[0].color = (*horizon, 1.0)
    ramp.color_ramp.elements[1].color = (*zenith, 1.0)
    blend.inputs["From Min"].default_value, blend.inputs["From Max"].default_value = 0.0, 0.6
    tree.links.new(coords.outputs["Generated"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], sky.inputs["Vector"])
    tree.links.new(sky.outputs["Color"], background.inputs["Color"])
    tree.links.new(coords.outputs["Generated"], height.inputs["Vector"])
    tree.links.new(height.outputs["Z"], blend.inputs["Value"])
    tree.links.new(blend.outputs["Result"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], seen.inputs["Color"])
    tree.links.new(camera.outputs["Is Camera Ray"], mix.inputs["Fac"])
    tree.links.new(background.outputs["Background"], mix.inputs[1])
    tree.links.new(seen.outputs["Background"], mix.inputs[2])
    tree.links.new(mix.outputs["Shader"], output.inputs["Surface"])
    level = max(0.0, float(strength))
    background.inputs["Strength"].default_value = level
    seen.inputs["Strength"].default_value = level
    for i, node in enumerate((coords, mapping, sky)):
        node.location = (background.location.x - 900 + 300 * i, background.location.y)
    for i, node in enumerate((height, blend, ramp, seen)):
        node.location = (background.location.x - 900 + 300 * i, background.location.y - 350)
    camera.location = (background.location.x, background.location.y + 300)
    mix.location = (background.location.x + 250, background.location.y)
    scene.world = world
    build.note_change()
    return world.name


def set_maps(build, material_name, maps, tile_m):
    """Set a texture's colour, roughness and normal maps on the build's material, at their real size."""
    mat, tree, bsdf = textures.prepare(build, material_name)
    vector = textures.world_vector(tree, bsdf, tile_m)
    x, y = bsdf.location.x - 300, bsdf.location.y
    for index, role in enumerate(("color", "roughness", "normal")):
        if role not in maps:
            continue
        image = bpy.data.images.load(maps[role], check_existing=True)
        build.tag(image)
        node = textures.image_node(tree, role, image, x, y - 280 * index, colour=role == "color")
        tree.links.new(vector, node.inputs["Vector"])
        if role == "color":
            tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
        elif role == "roughness":
            tree.links.new(node.outputs["Color"], bsdf.inputs["Roughness"])
        else:
            bump = tree.nodes.new("ShaderNodeNormalMap")
            bump.name = bump.label = "%s normal strength" % textures.NODE_PREFIX
            bump.inputs["Strength"].default_value = NORMAL_STRENGTH
            bump.location = (x + 150, y - 280 * index)
            tree.links.new(node.outputs["Color"], bump.inputs["Color"])
            tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    build.note_change()
    return mat.name
