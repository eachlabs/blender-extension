"""Keeps a targeted edit to its targets. Main thread only.

When a prompt changes only some objects ("make this red"), every other object of the chat's own must stay as it
was. Before each step the guard records those objects: transform, parent, mesh, material slots, and the state of
their materials. After the step it puts back what changed, and the step's result says which objects were put back.
A material the step edited in place that the target also uses stays edited on the target; the other objects get
the material as it was.
"""

from array import array

import bpy

from .things import registry


def _material_state(mat):
    """Everything a step can set on a material's nodes, as plain values."""
    if mat is None:
        return None
    state = [tuple(round(c, 4) for c in mat.diffuse_color)]
    tree = mat.node_tree
    if tree is not None:
        state.append((len(tree.nodes), len(tree.links)))
        for node in tree.nodes:
            for socket in node.inputs:
                value = getattr(socket, "default_value", None)
                try:
                    value = tuple(round(v, 4) for v in value)
                except TypeError:
                    value = round(value, 4) if isinstance(value, float) else value
                if isinstance(value, (int, float, tuple, str, bool)):
                    state.append((node.name, socket.identifier, value))
    return tuple(state)


def _mesh_state(data):
    if not isinstance(data, bpy.types.Mesh):
        return None
    coords = array("f", [0.0]) * (len(data.vertices) * 3)
    data.vertices.foreach_get("co", coords)
    return (len(data.vertices), len(data.polygons), round(sum(coords[0::3]), 3), round(sum(coords[1::3]), 3),
            round(sum(coords[2::3]), 3))


class EditGuard:
    """``targets``: session_uid of every target object and its parts."""

    def __init__(self, build, targets):
        self.build = build
        self.targets = set(targets)
        self._objects = {}  # uid -> recorded state
        self._mesh_backup = {}  # mesh session_uid -> an unlinked copy of it as it was
        self._material_backup = {}  # material session_uid -> an unlinked copy of it as it was
        self._made = []  # every backup datablock, removed by ``close``

    def _guarded(self):
        return [o for o in self.build._objects() if o.session_uid not in self.targets]

    def _target_materials(self):
        uids = set()
        for obj in self.build.scene.objects:
            if obj.session_uid in self.targets:
                uids.update(s.material.session_uid for s in obj.material_slots if s.material is not None)
        return uids

    def begin(self):
        """Before a step: record the chat's objects that are not targets."""
        self._objects = {}
        for obj in self._guarded():
            data = obj.data
            slots = [s.material for s in obj.material_slots]
            self._objects[obj.session_uid] = {
                "obj": obj, "name": obj.name, "matrix": obj.matrix_basis.copy(), "parent": obj.parent,
                "parent_inverse": obj.matrix_parent_inverse.copy(), "data": data, "mesh": _mesh_state(data),
                "slots": slots, "materials": [_material_state(m) for m in slots]}
            if isinstance(data, bpy.types.Mesh) and data.session_uid not in self._mesh_backup:
                copy = data.copy()
                self._mesh_backup[data.session_uid] = copy
                self._made.append(copy)
            for mat in slots:
                if mat is not None and mat.session_uid not in self._material_backup:
                    copy = mat.copy()
                    copy.use_fake_user = False
                    self._material_backup[mat.session_uid] = copy
                    self._made.append(copy)

    def check(self):
        """After a step: put back every recorded object the step changed; the names of those objects."""
        alive = {o.session_uid for o in bpy.data.objects}
        target_materials = self._target_materials()
        materials = {m.session_uid for m in bpy.data.materials}
        restored = []
        for uid, saved in self._objects.items():
            if uid not in alive:
                restored.append(saved["name"] + " (deleted; it cannot be put back)")
                continue
            obj = saved["obj"]
            changed = False
            if obj.parent != saved["parent"] and (saved["parent"] is None or saved["parent"].session_uid in alive):
                obj.parent = saved["parent"]
                obj.matrix_parent_inverse = saved["parent_inverse"]
                changed = True
            if obj.matrix_basis != saved["matrix"]:
                obj.matrix_basis = saved["matrix"]
                changed = True
            data = saved["data"]
            if obj.data != data and data is not None:
                obj.data = data
                changed = True
            if isinstance(data, bpy.types.Mesh) and _mesh_state(data) != saved["mesh"]:
                backup = self._mesh_backup.get(data.session_uid)
                if backup is not None:
                    fresh = backup.copy()
                    self.build.tag(fresh)
                    obj.data = fresh
                    changed = True
            for index, mat in enumerate(saved["slots"]):
                if index >= len(obj.material_slots):
                    break
                slot = obj.material_slots[index]
                if slot.material != mat and (mat is None or mat.session_uid in materials):
                    slot.material = mat
                    changed = True
                if mat is None or _material_state(mat) == saved["materials"][index]:
                    continue
                backup = self._material_backup.get(mat.session_uid)
                if backup is None:
                    continue
                if mat.session_uid in target_materials:  # the target keeps the edit; this object gets the old one
                    fresh = backup.copy()
                    fresh.name = mat.name + " kept"
                    self.build.tag(fresh)
                    slot.material = fresh
                else:  # only objects that are not targets use it: it goes back as it was, under its name
                    name = mat.name
                    fresh = backup.copy()
                    self.build.tag(fresh)
                    mat.user_remap(fresh)
                    bpy.data.materials.remove(mat)
                    fresh.name = name
                changed = True
            if changed:
                restored.append(saved["name"])
        if restored:
            self.build.note_change()
        return restored

    def close(self):
        """Remove the backups; a backup the scene took over through a copy is never used directly."""
        for block in self._made:
            try:
                if isinstance(block, bpy.types.Mesh):
                    bpy.data.meshes.remove(block)
                else:
                    bpy.data.materials.remove(block)
            except (ReferenceError, RuntimeError):
                pass
        self._made, self._mesh_backup, self._material_backup, self._objects = [], {}, {}, {}


def _world_state(world):
    """The scene's world as plain values: which world, its colour and every input of its nodes."""
    if world is None:
        return None
    state = [world.session_uid, tuple(round(c, 4) for c in world.color)]
    tree = world.node_tree
    if tree is not None:
        state.append((len(tree.nodes), len(tree.links)))
        for node in tree.nodes:
            image = getattr(node, "image", None)
            if image is not None:
                state.append((node.name, "image", image.name))
            for socket in node.inputs:
                value = getattr(socket, "default_value", None)
                try:
                    value = tuple(round(v, 4) for v in value)
                except TypeError:
                    value = round(value, 4) if isinstance(value, float) else value
                if isinstance(value, (int, float, tuple, str, bool)):
                    state.append((node.name, socket.identifier, value))
    return tuple(state)


class WorldGuard:
    """Keeps the scene's world (sky, background light) as it was through a follow-up that is not about the light:
    a harbour edit that removed a lighthouse also turned its dawn sky into a dark desert backdrop."""

    PUT_BACK = "the world (sky and background light): the request is not about the light or the sky"

    def __init__(self, build):
        self.build = build
        self._world = None
        self._state = None
        self._backup = None

    def begin(self):
        scene = self.build.scene
        self._world, self._state = scene.world, _world_state(scene.world)
        self._backup = scene.world.copy() if scene.world is not None else None

    def check(self):
        """After a step: put the world back when the step changed it; a one-item list naming it, or ``[]``."""
        scene, backup, self._backup = self.build.scene, self._backup, None
        try:
            changed = _world_state(scene.world) != self._state
            if not changed:
                return []
            if scene.world != self._world and (self._world is None or self._world.name in bpy.data.worlds):
                scene.world = self._world
            if _world_state(scene.world) != self._state and backup is not None:
                world, name = scene.world, scene.world.name
                world.user_remap(backup)
                if world.users == 0:
                    bpy.data.worlds.remove(world)
                backup.name = name
                self.build.tag(backup)
                backup = None  # it is the scene's world now
            self.build.note_change()
            return [self.PUT_BACK]
        finally:
            if backup is not None:
                bpy.data.worlds.remove(backup)


def target_uids(build, names, children=True):
    """Main thread: session_uid of each named object and all its parts, and of every object of the things they
    belong to, with their child things unless ``children`` is False."""
    out = set()
    for name in names:
        obj = build.scene.objects.get(name)
        if obj is not None:
            out.update(o.session_uid for o in [obj] + list(obj.children_recursive))
    out.update(o.session_uid for o in registry.subtree_objects(build._objects(), names, children))
    return out

