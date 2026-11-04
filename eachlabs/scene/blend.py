"""blend(): fuse round parts into one smooth surface, with modifiers and the depsgraph only (no bpy.ops, so it is
safe while the chat runs on Blender 4.2)."""

import bpy
from mathutils.bvhtree import BVHTree

from . import blend_size


def _depsgraph(scene):
    layer = bpy.context.view_layer if bpy.context.scene == scene else scene.view_layers[0]
    graph = layer.depsgraph
    graph.update()
    return graph


def _joined(parts, graph):
    """World-space points and faces of the parts' evaluated meshes, each face's material, and the materials."""
    points, faces, face_mats, materials, sizes = [], [], [], [], []
    for part in parts:
        ev = part.evaluated_get(graph)
        mesh = ev.to_mesh()
        try:
            world = ev.matrix_world
            # the evaluated object's materials are the depsgraph's own copies: a mesh must hold the originals
            slots = [s.material.original if s.material is not None else None for s in ev.material_slots]
            for mat in slots:
                if mat is not None and mat not in materials:
                    materials.append(mat)
            start = len(points)
            part_points = [world @ v.co for v in mesh.vertices]
            points.extend(part_points)
            for poly in mesh.polygons:
                faces.append(tuple(start + i for i in poly.vertices))
                mat = slots[poly.material_index] if poly.material_index < len(slots) else None
                face_mats.append(materials.index(mat) if mat in materials else -1)
            if part_points:
                sizes.append([max(p[i] for p in part_points) - min(p[i] for p in part_points) for i in range(3)])
        finally:
            ev.to_mesh_clear()
    return points, faces, face_mats, materials, sizes


def _top(parts):
    """The first part that no other part holds above it in the hierarchy (usually the thing's root), so it never
    loses a parent when the others are removed."""
    for part in parts:
        above, seen = part.parent, set()
        while above is not None and above not in parts and above.as_pointer() not in seen:
            seen.add(above.as_pointer())
            above = above.parent
        if above is None or above not in parts:
            return part
    return parts[0]


BLENDED = "blend_other"  # the face-corner colour the blended materials mix in: the other parts' colour and its share
THIN_NOTE = "blend(): left out as thin or flat parts, attached to %s: %s"


def _base_colour(mat):
    """The material's plain colour: the Principled BSDF's Base Color, or its viewport colour when that is linked."""
    node = _principled(mat)
    if node is not None and not node.inputs["Base Color"].is_linked:
        return tuple(node.inputs["Base Color"].default_value[:3])
    return tuple(mat.diffuse_color[:3])


def _principled(mat):
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def _socket(sockets, name, kind):
    return next(s for s in sockets if s.name == name and s.type == kind)


def _blended_copy(mat):
    """A copy of ``mat`` whose Base Color mixes in ``BLENDED`` by its alpha, or ``mat`` itself when it has nodes
    but no Principled BSDF. A copy, because the material may colour other objects too. A material without nodes
    (Blender 4.2's default) gets a Principled BSDF with its viewport colour, roughness and metallic."""
    plain = mat is not None and (not mat.use_nodes or mat.node_tree is None)
    if not plain and _principled(mat) is None:
        return mat
    copy = mat.copy()
    copy.name = mat.name + " blended"
    if plain:
        copy.use_nodes = True
    tree = copy.node_tree
    node = _principled(copy)
    if node is None:
        return mat
    if plain:
        node.inputs["Base Color"].default_value = tuple(mat.diffuse_color)
        node.inputs["Roughness"].default_value = mat.roughness
        node.inputs["Metallic"].default_value = mat.metallic
    base = node.inputs["Base Color"]
    attr = tree.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = BLENDED
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = "RGBA", "MIX"
    attr.location = (node.location.x - 520, node.location.y - 200)
    mix.location = (node.location.x - 260, node.location.y - 120)
    a = _socket(mix.inputs, "A", "RGBA")
    if base.is_linked:
        tree.links.new(base.links[0].from_socket, a)
    else:
        a.default_value = base.default_value[:]
    tree.links.new(attr.outputs["Color"], _socket(mix.inputs, "B", "RGBA"))
    tree.links.new(attr.outputs["Alpha"], _socket(mix.inputs, "Factor", "VALUE"))
    tree.links.new(_socket(mix.outputs, "Result", "RGBA"), base)
    return copy


def _soft_colours(result, points, faces, face_mats, materials, width):
    """Where two parts' colours meet, they fade into each other over ``width`` metres instead of following the
    remesh grid: each face corner gets the other colours' mean and its share (``BLENDED``), and each material
    becomes a copy that mixes it in."""
    colours = [_base_colour(m) for m in materials]
    trees = []
    for index in range(len(materials)):
        own = [f for f, m in zip(faces, face_mats) if m == index]
        trees.append(BVHTree.FromPolygons(points, own, all_triangles=False) if own else None)
    shares = []
    for vert in result.vertices:
        found = [t.find_nearest(vert.co, width)[3] if t is not None else None for t in trees]
        shares.append(blend_size.weights(found, width))
    picks = [p.material_index for p in result.polygons]
    loop_verts = [0] * len(result.loops)
    result.loops.foreach_get("vertex_index", loop_verts)
    values, cache = [], {}
    for poly, own in zip(result.polygons, picks):
        for loop in range(poly.loop_start, poly.loop_start + poly.loop_total):
            key = (loop_verts[loop], own)
            value = cache.get(key)
            if value is None:
                weights = shares[key[0]]
                value = cache[key] = (blend_size.other_colour(weights, colours, own) if sum(weights) > 0
                                      else (0.0, 0.0, 0.0, 0.0))
            values.extend(value)
    attribute = result.color_attributes.new(BLENDED, "FLOAT_COLOR", "CORNER")
    attribute.data.foreach_set("color", values)
    for slot, mat in enumerate(materials):
        result.materials[slot] = _blended_copy(mat)


def blend(parts, softness=0.5, scene=None):
    """Fuse the mesh ``parts`` into one smooth surface on the top part: join, voxel remesh, smooth; each face
    takes the material of the nearest part, and where two colours meet they fade into each other. Thin or flat
    parts (ears, tails, fins: ``blend_size.thin``) stay out, attached to the top part, and the step's output names
    them. The other parts are removed and their children move to the top one. ``softness`` 0-1: how far the
    shapes melt together. Returns the part that holds the result. Given to every step."""
    scene = scene if scene is not None else bpy.context.scene
    parts = list(dict.fromkeys(p for p in parts if p is not None))
    if len(parts) < 2 or any(p.type != "MESH" for p in parts):
        raise ValueError("blend() needs two or more mesh objects")
    keep = _top(parts)
    parts = [keep] + [p for p in parts if p is not keep]
    from .step_namespace import attach
    graph = _depsgraph(scene)
    apart = [p for p in parts[1:] if blend_size.thin(p.evaluated_get(graph).dimensions)]
    parts = [p for p in parts if p not in apart]
    for part in apart:
        if part.parent is not keep and part.parent not in parts:
            attach(part, keep)
    if apart:
        print(THIN_NOTE % (keep.name, ", ".join(p.name for p in apart)))
    if len(parts) < 2:
        return keep
    points, faces, face_mats, materials, sizes = _joined(parts, graph)
    if not faces:
        raise ValueError("blend(): the parts have no faces")
    extent = max(max(p[i] for p in points) - min(p[i] for p in points) for i in range(3))
    voxel, steps = blend_size.settings(sizes, extent, softness)

    joined = bpy.data.meshes.new(keep.name + " joined")
    joined.from_pydata([tuple(p) for p in points], [], faces)
    work = bpy.data.objects.new(keep.name + " joined", joined)
    scene.collection.objects.link(work)
    try:
        remesh = work.modifiers.new("Remesh", "REMESH")
        remesh.mode, remesh.voxel_size, remesh.adaptivity = "VOXEL", voxel, 0.0
        smooth = work.modifiers.new("Smooth", "LAPLACIANSMOOTH")
        smooth.iterations, smooth.lambda_factor, smooth.use_volume_preserve = steps, 0.5, True
        graph.update()
        result = bpy.data.meshes.new_from_object(work.evaluated_get(graph))
    finally:
        bpy.data.objects.remove(work)
        bpy.data.meshes.remove(joined)

    tree = BVHTree.FromPolygons(points, faces, all_triangles=False)
    for mat in materials:
        result.materials.append(mat)
    if materials:
        picks = []
        for poly in result.polygons:
            index = tree.find_nearest(poly.center)[2]
            picks.append(max(0, face_mats[index]) if index is not None else 0)
        result.polygons.foreach_set("material_index", picks)
    if len(materials) > 1:
        _soft_colours(result, points, faces, face_mats, materials, blend_size.edge_width(voxel, softness))
    result.polygons.foreach_set("use_smooth", [True] * len(result.polygons))

    world = keep.evaluated_get(graph).matrix_world.copy()
    result.transform(world.inverted())
    old, result.name = keep.data, keep.name
    keep.data = result
    keep.modifiers.clear()
    if old.users == 0:
        bpy.data.meshes.remove(old)
    removed = set(parts[1:])
    for part in parts[1:]:
        for child in list(part.children):
            if child not in removed:
                attach(child, keep)
        mesh = part.data
        bpy.data.objects.remove(part)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return keep
