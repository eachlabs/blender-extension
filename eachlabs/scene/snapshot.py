"""What a step may change, measured before and after it: data counts, materials, the world, the camera, broken meshes."""

import bpy
import math


OTHERS_MAX = 5000  # the person's objects compared before and after; a larger scene is sampled
DATA_KINDS = ("objects", "meshes", "materials", "lights", "cameras", "curves", "node_groups", "images", "worlds",
              "collections")



def _r(values, digits=2):
    return [round(float(v), digits) for v in values]



def _data_snapshot():
    """``{kind: {session_uid}}``; uids, not references, because the step may remove the datablocks."""
    return {kind: {block.session_uid for block in getattr(bpy.data, kind)} for kind in DATA_KINDS}



def _mesh_counts():
    """``{session_uid: (vertices, edges, corners, faces)}`` of every mesh: about 2 ms on a 2,500-object scene."""
    return {m.session_uid: (len(m.vertices), len(m.edges), len(m.loops), len(m.polygons)) for m in bpy.data.meshes}



def _repair_meshes(build, counts):
    """Run ``Mesh.validate`` on the meshes a step made, the build's own and any whose sizes changed; returns the
    names of those it repaired. Raw mesh writes the filter allows (``from_pydata`` with an index out of range,
    ``polygons.add`` without corners) corrupt Blender's memory on the next evaluation, so this runs before
    anything asks Blender to evaluate."""
    repaired = []
    for mesh in bpy.data.meshes:
        before = counts.get(mesh.session_uid)
        if before is not None and not build.owns(mesh) and before == (
                len(mesh.vertices), len(mesh.edges), len(mesh.loops), len(mesh.polygons)):
            continue
        if mesh.validate(verbose=False, clean_customdata=False):
            repaired.append(mesh.name)
    return repaired



def _material_state(mat, cache):
    """A material's base colour and node link count, so an edit in place shows as a change."""
    if mat is None:
        return None
    uid = mat.session_uid
    if uid not in cache:
        color, links = tuple(mat.diffuse_color), 0
        tree = mat.node_tree
        if tree is not None:
            links = len(tree.links)
            bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf is not None:
                color = tuple(bsdf.inputs["Base Color"].default_value)
        cache[uid] = (uid, tuple(round(c, 4) for c in color), links)
    return cache[uid]



def _object_state(obj, cache):
    data = obj.data
    return (tuple(round(v, 4) for row in obj.matrix_basis for v in row),
            obj.parent.session_uid if obj.parent is not None else None,
            data.session_uid if data is not None else None,
            len(data.vertices) if isinstance(data, bpy.types.Mesh) else None,
            round(sum(sum(corner) for corner in obj.bound_box), 3),  # coarse: catches moved vertices
            tuple(_material_state(slot.material, cache) for slot in obj.material_slots),
            obj.hide_viewport, obj.hide_render, obj.hide_select)



def _update(scene):
    """Bring bounding boxes up to date with edits that have not been evaluated yet."""
    for layer in scene.view_layers:
        layer.update()



def _others_snapshot(scene, build):
    """``({session_uid: state}, sampled)`` for the scene's objects the build does not own, at most
    ``OTHERS_MAX`` of them."""
    allowed = getattr(build, "allowed", set())  # the person pointed at these on purpose
    others = sorted((o for o in scene.objects if not build.owns(o) and o.session_uid not in allowed),
                    key=lambda o: o.session_uid)
    step = max(1, math.ceil(len(others) / OTHERS_MAX))
    cache = {}
    return {o.session_uid: _object_state(o, cache) for o in others[::step]}, step > 1



def _world_state(scene, build):
    """The scene's world as the model may see it: its name only when the build made it."""
    world = scene.world
    if world is None:
        return None
    state = {"yours": build.owns(world), "color": _r(world.color)}
    if state["yours"]:
        state["name"] = world.name
    tree = world.node_tree
    background = next((n for n in tree.nodes if n.type == "BACKGROUND"), None) if tree is not None else None
    if background is not None:
        state["color"] = _r(background.inputs["Color"].default_value[:3])
        state["strength"] = round(background.inputs["Strength"].default_value, 2)
    return state



def _camera_state(scene, build):
    cam = scene.camera
    state = {"frame_range": [scene.frame_start, scene.frame_end]}
    if cam is not None:
        state["camera"] = {"yours": build.owns(cam), "location": _r(cam.location)}
        if state["camera"]["yours"]:
            state["camera"]["name"] = cam.name
        if cam.type == "CAMERA":
            state["camera"]["lens"] = round(cam.data.lens, 1)
    return state



def fingerprint(build):
    """What a run's steps can change, to compare at its start and its end: every datablock id, the state of each
    object, light and world the build owns, and the scene's camera and frame range. Equal means nothing changed."""
    scene = build.scene
    _update(scene)
    cache = {}
    owned = sorted((o for o in scene.objects if build.owns(o)), key=lambda o: o.session_uid)
    lights = [(o.data.energy, tuple(o.data.color)) for o in owned if o.type == "LIGHT"]
    return (tuple(tuple(sorted(uids)) for uids in _data_snapshot().values()),
            tuple(_object_state(o, cache) for o in owned), tuple(lights),
            repr(_world_state(scene, build)), repr(_camera_state(scene, build)))
