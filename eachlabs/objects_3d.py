"""Bring a generated 3D model into the chat's scene with ``bpy.data`` only. Main thread only.

The GLB is read by ``glb`` and becomes one mesh, scaled to the size the model asked for, with its base on the
ground (z = 0 of the mesh is its lowest point, x and y are centred). Every placement is an object that shares that
mesh (a linked duplicate). A tint multiplies the texture by the object's colour, so copies can differ in colour
while they share one material.
"""

import math
import os

import bpy

from mathutils import Vector

from . import glb
from .scene_build import GENERATED, PLACEHOLDER

TINT_NODE = "eachlabs tint"


def _texture_image(build, model, index, base_path, colour):
    """The Blender image of ``model.textures[index]``: written next to the GLB, loaded and packed into the file."""
    texture = model.textures[index] if index is not None and index < len(model.textures) else None
    if texture is None or not texture.data:
        return None
    ext = ".jpg" if texture.mime == "image/jpeg" else ".png"
    path = "%s_tex%d%s" % (base_path, index, ext)
    if not os.path.isfile(path) or os.path.getsize(path) != len(texture.data):
        with open(path, "wb") as out:
            out.write(texture.data)
    image = bpy.data.images.load(path, check_existing=False)
    image.name = "eachlabs_%s_%d" % (os.path.basename(base_path), index)
    if not colour:
        try:
            image.colorspace_settings.name = "Non-Color"
        except TypeError:  # a colour management setup without it
            pass
    image.pack()
    build.tag(image)
    return image


def _socket(sockets, kind, name=None):
    return next((s for s in sockets if s.type == kind and (name is None or s.name == name)), None)


def _material(build, model, mat, label, base_path):
    material = bpy.data.materials.new("eachlabs_%s" % label)
    build.tag(material)
    if material.node_tree is None:
        material.use_nodes = True
    tree = material.node_tree
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return material
    bsdf.inputs["Metallic"].default_value = max(0.0, min(1.0, mat.metallic))
    bsdf.inputs["Roughness"].default_value = max(0.0, min(1.0, mat.roughness))
    material.diffuse_color = tuple(mat.base_color[:4])
    base = _texture_image(build, model, mat.base_texture, base_path, True)
    colour = None
    if base is not None:
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = base
        node.location = (-700, 300)
        colour = node.outputs["Color"]
    else:
        bsdf.inputs["Base Color"].default_value = tuple(mat.base_color[:4])
    if colour is not None:  # base colour times the object's colour: a tint per copy, white by default
        info = tree.nodes.new("ShaderNodeObjectInfo")
        info.location = (-700, 0)
        mix = tree.nodes.new("ShaderNodeMix")
        mix.name = mix.label = TINT_NODE
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.location = (-350, 250)
        mix.inputs[0].default_value = 1.0
        a, b = [s for s in mix.inputs if s.type == "RGBA"][:2]
        tree.links.new(colour, a)
        tree.links.new(info.outputs["Color"], b)
        tree.links.new(_socket(mix.outputs, "RGBA"), bsdf.inputs["Base Color"])
    mr = _texture_image(build, model, mat.mr_texture, base_path, False)
    if mr is not None:  # glTF: roughness in green, metallic in blue
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = mr
        node.location = (-700, -300)
        split = tree.nodes.new("ShaderNodeSeparateColor")
        split.location = (-350, -300)
        tree.links.new(node.outputs["Color"], split.inputs[0])
        tree.links.new(split.outputs[1], bsdf.inputs["Roughness"])
        tree.links.new(split.outputs[2], bsdf.inputs["Metallic"])
    normal = _texture_image(build, model, mat.normal_texture, base_path, False)
    if normal is not None:
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = normal
        node.location = (-700, -600)
        bump = tree.nodes.new("ShaderNodeNormalMap")
        bump.location = (-350, -600)
        tree.links.new(node.outputs["Color"], bump.inputs["Color"])
        tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return material


def build_mesh(build, path, label, size_m, measure=""):
    """A mesh from the GLB at ``path``, ``size_m`` along ``measure`` (height, length, or else its longest side), its
    base at z = 0 and centred in x and y. Returns ``(mesh, (width, depth, height))``."""
    with open(path, "rb") as handle:
        model = glb.read(handle.read())
    low, high = model.bounds
    scale = glb.scale_for((low, high), size_m, measure)
    cx, cy, base = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2, glb.base_height(model)
    verts, faces, uvs, material_of = [], [], [], []
    slots = {}  # glTF material index -> mesh slot
    for part in model.parts:
        offset = len(verts)
        p = part.positions
        verts.extend(((p[i] - cx) * scale, (p[i + 1] - cy) * scale, (p[i + 2] - base) * scale)
                     for i in range(0, len(p), 3))
        t = part.triangles
        faces.extend((t[i] + offset, t[i + 1] + offset, t[i + 2] + offset) for i in range(0, len(t), 3))
        if part.material is not None and part.material not in slots:
            slots[part.material] = len(slots)
        material_of.extend([slots.get(part.material, 0)] * (len(t) // 3))
        if part.uvs is not None:
            uv = part.uvs
            uvs.extend(x for v in t for x in (uv[2 * v], uv[2 * v + 1]))
        else:
            uvs.extend([0.0] * (2 * len(t)))
    mesh = bpy.data.meshes.new("eachlabs_%s" % label)
    build.tag(mesh)
    mesh.from_pydata(verts, [], faces)
    layer = mesh.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", uvs)
    mesh.polygons.foreach_set("material_index", material_of)
    mesh.polygons.foreach_set("use_smooth", [True] * len(faces))
    base_path = os.path.splitext(path)[0]
    for index in sorted(slots, key=slots.get):
        mesh.materials.append(_material(build, model, model.materials[index], label, base_path))
    if not slots:
        mesh.materials.append(_material(build, model, glb.Material(name=label), label, base_path))
    mesh.update()
    size = tuple((high[i] - low[i]) * scale for i in range(3))
    return mesh, size


SQUARE = 1.15  # a footprint closer to square than this has no long side to line the model up with


def spot(root):
    """Where a placeholder stands: ``location`` (the middle of its footprint, z at its lowest point), ``rotation``
    (its turn about the vertical axis, radians), ``footprint`` (x and y extents in its own turned frame) and
    ``size`` (its longest side). The placeholder is the object and everything parented under it."""
    rz = root.matrix_world.to_euler().z
    origin = root.matrix_world.translation
    cos, sin = math.cos(-rz), math.sin(-rz)
    points = []
    for obj in [root] + list(root.children_recursive):
        if obj.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT"):
            continue
        for corner in obj.bound_box:
            p = obj.matrix_world @ Vector(corner)
            dx, dy = p.x - origin.x, p.y - origin.y
            points.append((dx * cos - dy * sin, dx * sin + dy * cos, p.z))
    if not points:
        return {"location": [origin.x, origin.y, origin.z], "rotation": rz, "footprint": (0.0, 0.0), "size": 0.0}
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    cx, cy = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2
    back = math.cos(rz), math.sin(rz)
    extents = [high[i] - low[i] for i in range(3)]
    return {"location": [origin.x + cx * back[0] - cy * back[1], origin.y + cx * back[1] + cy * back[0], low[2]],
            "rotation": rz, "footprint": (extents[0], extents[1]), "size": max(extents)}


def _lined_up(model_size, footprint):
    """A quarter turn when the model's long side and the placeholder's long side run along different axes."""
    mx, my = model_size[0], model_size[1]
    fx, fy = footprint
    if min(mx, my) <= 0 or min(fx, fy) <= 0:
        return 0.0
    if max(mx, my) / min(mx, my) < SQUARE or max(fx, fy) / min(fx, fy) < SQUARE:
        return 0.0
    return 0.0 if (mx > my) == (fx > fy) else math.pi / 2


def place(build, mesh, label, spots, job_id, model_size, tints=()):
    """One object per spot, all sharing ``mesh`` (built ``model_size`` big for the first spot); returns their names.
    Each copy is scaled to its spot's size, turned like it and lined up with its long side; ``tints``: an
    optional [r, g, b] per copy that multiplies the colours."""
    names = []
    many = len(spots) > 1
    base = max(model_size) or 1.0
    for i, where in enumerate(spots):
        obj = bpy.data.objects.new("%s %d" % (label, i + 1) if many else label, mesh)
        obj.location = tuple(float(v) for v in where["location"])
        obj.rotation_euler = (0.0, 0.0, where["rotation"] + _lined_up(model_size, where["footprint"]))
        factor = where["size"] / base if where.get("size") else 1.0
        obj.scale = (factor, factor, factor)
        tint = tints[i] if i < len(tints) else None
        if tint:
            obj.color = (float(tint[0]), float(tint[1]), float(tint[2]), 1.0)
        build.adopt(obj)  # links it into the chat's collection
        obj[GENERATED] = job_id
        names.append(obj.name)
    build.note_change()
    return names


REST_FROM = 0.5  # metres above a model's base the downward ray starts: under a roof or a tree crown above it
REST_MOST = 3.0  # metres a model is moved at most to rest on what is below it


def rest_on_ground(build, names, job_id):
    """Set each placed copy on the surface under the middle of its footprint: a ray down from just above its base,
    passing through the model's own copies. Returns the height change of each copy (0 when nothing was found)."""
    scene = build.scene
    for layer in scene.view_layers:
        layer.update()
    depsgraph = scene.view_layers[0].depsgraph
    down = Vector((0.0, 0.0, -1.0))
    moved = []
    for name in names:
        obj = scene.objects.get(name)
        if obj is None:
            moved.append(0.0)
            continue
        start = obj.matrix_world.translation + Vector((0.0, 0.0, REST_FROM))
        shift = 0.0
        for _ in range(16):
            hit, where, _normal, _index, other, _matrix = scene.ray_cast(depsgraph, start, down,
                                                                         distance=REST_FROM + REST_MOST)
            if not hit:
                break
            if other is not None and other.original.get(GENERATED) == job_id:  # the model itself or a copy
                start = where + down * 0.001
                continue
            change = where.z - obj.location.z
            if abs(change) <= REST_MOST:
                obj.location.z += change
                shift = change
            break
        moved.append(round(shift, 4))
    return moved


def placeholders(build, job_id):
    """The chat's objects that stand in for a job's 3D model, roots first, then every part: the tagged objects,
    what a later stage parented under them, and the chat's loose objects named after a root that stand inside it
    ("Church_Door" in "Church"). Only the tagged ones carry ``PLACEHOLDER``."""
    allowed = getattr(build, "allowed", set())  # the person's objects they pointed at to upgrade

    def ok(obj):
        return (build.owns(obj) or obj.session_uid in allowed) and not obj.get(GENERATED)

    tagged = [o for o in build.scene.objects if o.get(PLACEHOLDER) == job_id and ok(o)]
    ids = {o.session_uid for o in tagged}
    roots = [o for o in tagged if o.parent is None or o.parent.session_uid not in ids]
    parts = list(tagged)

    def add(obj):
        for part in [obj] + list(obj.children_recursive):
            if part.session_uid not in ids and ok(part) and not part.get(PLACEHOLDER):
                ids.add(part.session_uid)
                parts.append(part)

    for root in roots:
        add(root)
    for root in roots:
        low, high = _bounds([root] + list(root.children_recursive))
        if low is None:
            continue
        margin = 0.1 * max(high[i] - low[i] for i in range(3))
        for obj in build.scene.objects:
            if obj.parent is not None or obj.session_uid in ids or not ok(obj) or obj.get(PLACEHOLDER):
                continue
            rest = obj.name[len(root.name):]
            if not obj.name.startswith(root.name) or rest[:1] not in ("_", " ") or rest[1:].strip(".").isdigit():
                continue  # not named after it, or another copy ("Church 2")
            box_low, box_high = _bounds([obj] + list(obj.children_recursive))
            if box_low is not None and all(low[i] - margin <= (box_low[i] + box_high[i]) / 2 <= high[i] + margin
                                           for i in range(3)):
                add(obj)
    return roots, parts


def _bounds(objects):
    """World ``(low, high)`` corners around the geometry of ``objects``, or ``(None, None)``."""
    points = [obj.matrix_world @ Vector(corner) for obj in objects
              if obj.type in ("MESH", "CURVE", "SURFACE", "META", "FONT") for corner in obj.bound_box]
    if not points:
        return None, None
    return ([min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)])


def remove(objects):
    for obj in objects:
        try:
            bpy.data.objects.remove(obj)
        except ReferenceError:  # already gone with its parent
            pass
