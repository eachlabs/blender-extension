"""Generated textures on the chat's materials. Main thread only.

The picture comes from ``generation.run_texture``; here it becomes an Image Texture node with box projection on
world positions, scaled so one tile covers ``tile_m`` metres on every axis, into the material's Base Color.
"""

import bpy

NODE_PREFIX = "Eachlabs texture"
BOX_BLEND = 0.25  # how softly box projection blends where two faces of a box meet
VARIATION_PATCH = 0.2  # the shift's patches are about five tiles across
VARIATION = 0.35  # how far, in tiles, the shift moves a tile at most


def apply(build, material_name, path, tile_m=1.0):
    """Set the picture at ``path`` on the build's material ``material_name``; returns the material's name.
    Raises ``LookupError`` when the build has no such material."""
    mat, tree, bsdf = prepare(build, material_name)
    image = bpy.data.images.load(path, check_existing=True)
    build.tag(image)
    vector = world_vector(tree, bsdf, tile_m)
    texture = image_node(tree, "image", image, bsdf.location.x - 300, bsdf.location.y)
    tree.links.new(vector, texture.inputs["Vector"])
    tree.links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
    build.note_change()
    return mat.name


def prepare(build, material_name):
    """``(material, node tree, Principled BSDF)`` of the build's material, with earlier texture nodes removed."""
    mat = bpy.data.materials.get(material_name)
    if mat is None or not build.owns(mat):
        raise LookupError("no material of the chat's own named %s" % material_name)
    if mat.node_tree is None:
        mat.use_nodes = True
    tree = mat.node_tree
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None) or tree.nodes.new(
            "ShaderNodeOutputMaterial")
        tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    for node in [n for n in tree.nodes if n.name.startswith(NODE_PREFIX)]:  # a texture set again replaces the old
        tree.nodes.remove(node)
    return mat, tree, bsdf


def image_node(tree, label, image, x, y, colour=True):
    """A box-projected Image Texture node named with ``NODE_PREFIX``; ``colour=False`` reads it as data."""
    node = tree.nodes.new("ShaderNodeTexImage")
    node.name = node.label = "%s %s" % (NODE_PREFIX, label)
    node.image = image
    if not colour:
        image.colorspace_settings.name = "Non-Color"
    node.projection = "BOX"
    node.projection_blend = BOX_BLEND
    node.location = (x, y)
    return node


def world_vector(tree, bsdf, tile_m):
    """The output socket of a world-position mapping where one tile covers ``tile_m`` metres on every axis."""
    # World position, in metres: one tile covers tile_m on every axis whatever the object's scale. Object
    # coordinates carry the object's scale, so a plane scaled 100 times showed grass 100 times too big and a cube
    # stretched into a long wall stretched its stones.
    coords = tree.nodes.new("ShaderNodeNewGeometry")
    mapping = tree.nodes.new("ShaderNodeMapping")
    noise = tree.nodes.new("ShaderNodeTexNoise")  # a slow, small shift of the tiles hides their repeats
    wobble = tree.nodes.new("ShaderNodeVectorMath")
    shifted = tree.nodes.new("ShaderNodeVectorMath")
    for node, label in ((coords, "coordinates"), (mapping, "mapping"), (noise, "variation"), (wobble, "variation size"),
                        (shifted, "varied")):
        node.name = node.label = "%s %s" % (NODE_PREFIX, label)
    tile = max(0.05, float(tile_m or 1.0))
    scale = 1.0 / tile
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    noise.inputs["Scale"].default_value = VARIATION_PATCH
    wobble.operation, shifted.operation = "SCALE", "ADD"
    wobble.inputs["Scale"].default_value = VARIATION
    for i, node in enumerate((coords, mapping, noise, wobble, shifted)):
        node.location = (bsdf.location.x - 1300 + 200 * i, bsdf.location.y + (200 if node in (noise, wobble) else 0))
    tree.links.new(coords.outputs["Position"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    tree.links.new(noise.outputs["Color"], wobble.inputs[0])
    tree.links.new(mapping.outputs["Vector"], shifted.inputs[0])
    tree.links.new(wobble.outputs["Vector"], shifted.inputs[1])
    return shifted.outputs["Vector"]


STRETCH_MAX = 3.0  # a texture this many times longer along one axis of an object than another reads as stretched
BLOWN_UP = 5.0  # an object scaled this many times blows up a texture on its own coordinates by as much
COVERS_MAX = 4.0  # metres: a texture on Generated coordinates spans the whole object, one picture over all of it
SCALE_MAX = 8  # entries listed


def _coordinates(tree):
    """How the material's textures are placed: "generated", "object" or "" (UV, world position or none)."""
    kinds = set()
    for node in tree.nodes:
        if node.type == "TEX_COORD":
            for name, kind in (("Generated", "generated"), ("Object", "object")):
                if node.outputs[name].is_linked and node.object is None:
                    kinds.add(kind)
        elif node.type.startswith("TEX_") and node.type != "TEX_IMAGE" and "Vector" in node.inputs:
            if not node.inputs["Vector"].is_linked:
                kinds.add("generated")  # an unlinked procedural texture uses Generated coordinates
    return "generated" if "generated" in kinds else "object" if "object" in kinds else ""


def _mapping_scale(tree):
    """The Scale of the material's Mapping node, or ``(1, 1, 1)`` without one."""
    mapping = next((n for n in tree.nodes if n.type == "MAPPING" and "Scale" in n.inputs
                    and not n.name.startswith(NODE_PREFIX)), None)
    if mapping is None:
        return (1.0, 1.0, 1.0)
    return tuple(abs(float(v)) or 1.0 for v in mapping.inputs["Scale"].default_value)


def pattern_stretch(dimensions, scale):
    """How many times longer a Generated-coordinates pattern repeats along one of an object's two long sides than
    along the other: each side's length over the mapping's scale on that axis."""
    sides = sorted(range(3), key=lambda i: -abs(dimensions[i]))[:2]
    lengths = [abs(dimensions[i]) / (scale[i] or 1.0) for i in sides]
    if min(lengths) <= 0:
        return 1.0
    return max(lengths) / min(lengths)


def rescale(material):
    """Place a material's patterns by world position instead of Generated or Object coordinates, so a pattern's
    scale reads as repeats per metre on every axis of every object it is on; returns whether anything changed.
    Image textures on UV maps and coordinates taken from another object are left as they are."""
    tree = material.node_tree
    if tree is None:
        return False
    position = None

    def world():
        nonlocal position
        if position is None:
            geometry = tree.nodes.new("ShaderNodeNewGeometry")
            geometry.name = geometry.label = "%s world position" % NODE_PREFIX
            position = geometry.outputs["Position"]
        return position

    changed = False
    for node in list(tree.nodes):
        if node.type == "TEX_COORD" and node.object is None:
            for name in ("Generated", "Object"):
                for link in list(node.outputs[name].links):
                    tree.links.new(world(), link.to_socket)
                    changed = True
        elif node.type.startswith("TEX_") and node.type not in ("TEX_IMAGE", "TEX_COORD", "TEX_ENVIRONMENT") \
                and "Vector" in node.inputs and not node.inputs["Vector"].is_linked:
            tree.links.new(world(), node.inputs["Vector"])
            changed = True
    return changed


def rescale_reported(objects, owns):
    """Rescale the chat's materials that ``scale_problems`` lists; returns their names."""
    done = []
    for entry in scale_problems(objects, owns, limit=None):
        mat = bpy.data.materials.get(entry["material"])
        if mat is not None and mat.name not in done and rescale(mat):
            done.append(mat.name)
    return done


def scale_problems(objects, owns, limit=SCALE_MAX):
    """Textures that read at the wrong size on the chat's objects: stretched along one axis, or one picture blown
    up over a whole large object, at most ``limit`` (``None``: all).
    ``[{"material", "object", "stretch" | "blown_up" | "covers_m"}]``."""
    found, seen = [], set()
    for obj in objects:
        if obj.type != "MESH" or obj.hide_render or obj.data is None:
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or not owns(mat) or mat.node_tree is None or (mat.name, obj.data.name) in seen:
                continue
            seen.add((mat.name, obj.data.name))
            kind = _coordinates(mat.node_tree)
            entry = None
            if kind == "generated":
                ratio = pattern_stretch(obj.dimensions, _mapping_scale(mat.node_tree))
                if ratio >= STRETCH_MAX:
                    entry = {"stretch": round(ratio, 1)}
                elif max(obj.dimensions) >= COVERS_MAX:
                    entry = {"covers_m": round(max(obj.dimensions), 1)}
            elif kind == "object":
                scale = sorted(abs(v) for v in obj.scale)  # the thinnest axis shows no length of texture
                if scale[1] > 0 and scale[2] / scale[1] >= STRETCH_MAX:
                    entry = {"stretch": round(scale[2] / scale[1], 1)}
                elif scale[2] >= BLOWN_UP:
                    entry = {"blown_up": round(scale[2], 1)}
            if entry:
                found.append(dict(material=mat.name, object=obj.name, **entry))
                if limit is not None and len(found) >= limit:
                    return found
    return found
