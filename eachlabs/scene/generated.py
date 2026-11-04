"""Generated 3D models and the world: keeping their looks when a step changes them."""

import bpy

from . import common


PLACEHOLDER = "eachlabs_placeholder"  # object property: the job whose 3D model replaces this code version
GENERATED_KEPT_NOTE = ("Your step changed the materials or modifiers of %d generated 3D object%s; that was put back: "
                       "generated models keep their own textures.")


class GeneratedLooks:
    def _generated(self):
        return [o for o in self._objects() if o.get(common.GENERATED)]

    def _generated_looks(self):
        """What a step must not change on a generated 3D object: its material slots and its modifiers."""
        looks = {}
        for obj in self._generated():
            slots = [(s.link, s.material.session_uid if s.material is not None else None) for s in obj.material_slots]
            data = list(obj.data.materials) if obj.type == "MESH" else []
            looks[obj.session_uid] = (slots, data, [m.name for m in obj.modifiers])
        return looks

    def _keep_generated_looks(self, looks):
        """Put back the materials and remove the modifiers a step gave a generated object; returns how many objects
        it put back. A generated model keeps the textures it came with."""
        kept = 0
        for obj in self._generated():
            before = looks.get(obj.session_uid)
            if before is None:
                continue
            slots, data, modifiers = before
            data = [m for m in data if m is None or common._alive(m)]  # a material the step removed is left out
            changed = False
            for mod in [m for m in obj.modifiers if m.name not in modifiers]:
                obj.modifiers.remove(mod)
                changed = True
            if obj.type == "MESH" and list(obj.data.materials) != data:
                obj.data.materials.clear()
                for mat in data:
                    obj.data.materials.append(mat)
                changed = True
            now = [(s.link, s.material.session_uid if s.material is not None else None) for s in obj.material_slots]
            if now != slots:
                for slot, (link, _uid) in zip(obj.material_slots, slots):
                    slot.link = link
                    if link == "OBJECT":
                        slot.material = None
                changed = True
            kept += changed
        return kept

    def _generated_entries(self):
        out = []
        for job_id, entry in self.generated.items():
            item = {"job_id": job_id, "description": entry.get("description"), "status": entry.get("status"),
                    "copies": entry.get("copies")}
            if entry.get("status") == "ready":
                names = [o.name for o in self._generated() if o.get(common.GENERATED) == job_id]
                item["names"] = common._cap(names, 12)
            if entry.get("status") == "pending" and entry.get("placeholders"):
                item["code_versions"] = common._cap(entry["placeholders"], 12)
            if entry.get("status") == "failed":
                item["stays_in_code"] = common._cap(entry.get("placeholders") or [], 12)
            out.append(item)
        return out

    def _scene_world(self):
        try:
            world = self.scene.world
        except RuntimeError:
            return None
        return world.session_uid if world is not None else None

    def _keep_world(self, uid):
        """A world the step replaced that nothing uses any more gets a fake user, so saving keeps it."""
        if uid is None or self._scene_world() == uid:
            return
        old = next((w for w in bpy.data.worlds if w.session_uid == uid), None)
        if old is not None and not self._mine(old) and old.users == 0 and not old.use_fake_user:
            old.use_fake_user = True
