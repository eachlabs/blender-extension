"""read_scene: the scene as the model sees it, with every check's findings, and the names Code check is told."""

import bpy

from .. import scene_tools, solids, textures
from ..things import after_step as things_after
from ..checks.lights import SHADOWS_NOTE, SHADOW_LIGHTS_MAX
from ..checks.mesh_health import HEALTH_MAX
from ..checks import colours, duplicates, emission, looks, piercing, text_facing, through_glass
from ..checks.placement import STAND_LIST_MAX
from . import camera_view, common, generated


OBJECTS_MAX = 60  # entries per list in read_scene
PIERCE_ROOTS = 15  # newest things of a run whose thin parts are checked for passing through their own parts
CONTEXT_NAMES_MAX = 2000  # object names Code check is told are the chat's; a street has 200-600
NO_MATERIAL_MAX = 30  # names read_scene lists under no_material


class SceneReport:
    def _label(self, obj):
        return obj.name if self._visible(obj) else "(not yours)"

    def _colour_off(self, mine):
        """The things whose colour is not the one the request asked for (``colours.off_colours``)."""
        asked = getattr(self, "asked_colours", None)
        if not asked:
            return []
        from .. import plan3d

        return colours.off_colours([o for o in mine if common.is_thing(o)], asked, plan3d.name_words)

    def _root_label(self, obj):
        while obj.parent is not None and self._mine(obj.parent) and not obj.parent.get("zone"):
            obj = obj.parent
        return self._label(obj)

    def chat_context(self):
        """What Code check is told about ownership: this run's collection and the names of its objects."""
        self.scene
        # Structured entries, so a name the model chose (quotes, newlines) cannot read as a second entry, and each
        # with its kind, so the chat's material "Chair" does not make the person's object "Chair" the chat's.
        owned = [{"kind": "object", "name": o.name} for o in self._objects()]
        for kind, blocks in (("material", bpy.data.materials), ("world", bpy.data.worlds),
                             ("node group", bpy.data.node_groups), ("action", bpy.data.actions),
                             ("mesh", bpy.data.meshes), ("curve", bpy.data.curves), ("light", bpy.data.lights),
                             ("camera", bpy.data.cameras)):
            owned.extend({"kind": kind, "name": b.name} for b in blocks if self._mine(b))
        return {"collection": self.collection_name or "", "objects": owned[:CONTEXT_NAMES_MAX]}

    def read_scene(self):
        scene = self.scene
        common._update(scene)
        mine = self._objects()
        everything = {o.session_uid for o in mine}
        if self.focus:  # a targeted edit sees only its targets, also the person's objects they selected
            mine = [o for o in scene.objects if o.session_uid in self.focus
                    and (o.session_uid in everything or o.session_uid in self.allowed)]
            everything |= {o.session_uid for o in mine}
        objects, lights = [], []
        for obj in mine:
            if obj.type == "LIGHT":
                lights.append({"name": obj.name, "type": obj.data.type, "location": common._r(obj.matrix_world.translation),
                               "energy": round(obj.data.energy, 1), "color": common._r(obj.data.color)})
                continue
            entry = {"name": obj.name, "type": obj.type, "location": common._r(obj.matrix_world.translation)}
            if obj.type != "CAMERA":
                entry["dimensions"] = common._r(obj.dimensions)
                bounds = common._world_bounds(obj)
                if bounds is not None:
                    entry["bounds"] = bounds
            if obj.parent is None and obj.children:  # a thing of many parts: where all of it is
                where = common.extent(obj)
                if where is not None:
                    entry["extent"] = where
            slots = [s.material for s in obj.material_slots if s.material is not None]
            materials = [m.name if self._mine(m) else "(not yours)" for m in slots]
            if materials:
                entry["materials"] = common._cap(materials, 6)
            if obj.modifiers:
                entry["modifiers"] = common._cap([m.type for m in obj.modifiers], 6)
            if obj.parent is not None:
                entry["parent"] = obj.parent.name if self._visible(obj.parent) else "(not yours)"
            if obj.hide_render or obj.hide_viewport:
                entry["hidden"] = True
            if obj.get(common.GENERATED):
                entry["generated"] = True
            if obj.get(generated.PLACEHOLDER):
                entry["placeholder"] = True
            objects.append(entry)
        own = {o.session_uid for o in mine}
        parts = [{"name": o.name, "parent": o.parent.name if o.parent is not None and self._visible(o.parent) else None,
                  "box": common._box(o) if o.type in common.GEOMETRY and not o.hide_render else None}
                 for o in mine if o.type != "CAMERA"]
        loose = scene_tools.loose_parts(parts)
        overlaps = scene_tools.overlaps(parts, self.existing)  # parts holds the chat's own objects only
        free = self._free_space(mine) if not self.focus else None
        bare = common._cap([o.name for o in mine if o.type in ("MESH", "CURVE", "SURFACE", "META", "FONT")
                     and not o.get(common.GENERATED) and not any(s.material for s in o.material_slots)], NO_MATERIAL_MAX)
        for entry in overlaps:
            if "overlaps_existing" in entry and free is not None and not scene_tools.fits(free["areas"], entry["size"]):
                entry["note"] = "no free area fits %g x %g m; extend the ground" % tuple(entry["size"])
        footing = self._footing(scene) if not self.focus else {}
        made = set(self.created_since(self.since))
        checked = mine if self.focus else [o for o in mine if o.name in made]
        holes, flipped = self.mesh_health(checked[-HEALTH_MAX:])
        depsgraph = self._depsgraph(scene)
        made_uids = {o.session_uid for o in checked}
        crossing = solids.crossings(mine, depsgraph, made_uids, label=self._root_label)
        hidden = solids.hidden_parts(mine, depsgraph, made_uids)
        zones = self._zones(mine) if not self.focus else None
        off_ground = self._outside_ground(mine, free["ground"] if free else None) if not self.focus else []
        texture_scale = textures.scale_problems(mine, self._mine)
        mixed_looks = looks.mixed_looks(mine, self._mine) if not self.focus else None
        backwards = text_facing.mirrored_text(mine, scene.camera)
        harsh = emission.harsh_emitters(mine, self._mine)
        colour_off = self._colour_off(mine) if not self.focus else []
        windows = through_glass.views(mine, self._mine, scene, depsgraph, self._root_label) if not self.focus else []
        empty = self._empty_groups(mine) if not self.focus else []
        gaps = self._new_gaps(mine) if not self.focus else []
        made = set(self.created_since(self.since))
        new_roots = [o for o in mine if o.name in made and common.is_thing(o) and o.children][-PIERCE_ROOTS:]
        pierced = piercing.pierces(new_roots, solids.Meshes(depsgraph))
        doubled = duplicates.report(duplicates.measure(mine)) if not self.focus else []
        shadows = [o for o in mine if o.type == "LIGHT" and getattr(o.data, "use_shadow", False)]
        shadow_info = {}
        if len(shadows) > SHADOW_LIGHTS_MAX:
            shadow_info["shadow_lights"] = len(shadows)
            shadow_info["shadow_note"] = SHADOWS_NOTE % (len(shadows), SHADOW_LIGHTS_MAX)
        if self.shadows_off:
            shadow_info["shadows_turned_off"] = common._cap(self.shadows_off, STAND_LIST_MAX)
        if self.closed_ends:
            shadow_info["ends_closed"] = common._cap(self.closed_ends, STAND_LIST_MAX)
        if getattr(self, "replaced_parts", None):
            shadow_info["replaced_parts"] = common._cap(self.replaced_parts, STAND_LIST_MAX)
        if getattr(self, "textures_rescaled", None):
            shadow_info["textures_rescaled"] = common._cap(self.textures_rescaled, STAND_LIST_MAX)
        return {
            "objects": common._cap(camera_view._grouped(objects), OBJECTS_MAX),
            "lights": common._cap(camera_view._grouped(lights), OBJECTS_MAX),
            "world": self._world(scene),
            "camera": self._camera(scene),
            "frame_range": [scene.frame_start, scene.frame_end],
            "fps": round(scene.render.fps / scene.render.fps_base, 3),
            "engine": scene.render.engine,
            "other_objects": sum(1 for o in scene.objects if o.session_uid not in everything),
            **({"not_target": len(everything - own)} if self.focus else {}),
            **({"loose_parts": loose} if loose else {}),
            **({"overlaps": overlaps} if overlaps else {}),
            **({"crossing": crossing} if crossing else {}),
            **({"hidden_parts": hidden} if hidden else {}),
            **({"zones": zones} if zones else {}),
            **({"outside_ground": off_ground} if off_ground else {}),
            **({"texture_scale": texture_scale} if texture_scale else {}),
            **({"looks": mixed_looks} if mixed_looks else {}),
            **({"mirrored_text": backwards} if backwards else {}),
            **({"harsh_emission": harsh} if harsh else {}),
            **({"colour_off": colour_off} if colour_off else {}),
            **({"through_glass": windows} if windows else {}),
            **({"empty_groups": empty} if empty else {}),
            **({"gaps": gaps} if gaps else {}),
            **({"pierces": pierced} if pierced else {}),
            **({"duplicates": doubled} if doubled else {}),
            **({"free_space": free} if free is not None else {}),
            **footing,
            **({"open_holes": holes} if holes else {}),
            **({"flipped_normals": flipped} if flipped else {}),
            **shadow_info,
            **({"no_material": bare} if bare else {}),
            **things_after.report(mine),
            **({"generated_3d": self._generated_entries()} if self.generated else {}),
            **({"textures": [dict(t) for t in self.textures.values()]} if self.textures else {}),
        }

    def _world(self, scene):
        world = scene.world
        if world is None:
            return None
        info = {"yours": self._mine(world), "color": common._r(world.color)}
        if info["yours"]:
            info["name"] = world.name
        tree = world.node_tree
        if tree is not None:
            background = next((n for n in tree.nodes if n.type == "BACKGROUND"), None)
            if background is not None:
                info["color"] = common._r(background.inputs["Color"].default_value[:3])
                info["strength"] = round(background.inputs["Strength"].default_value, 2)
            kinds = sorted({n.type for n in tree.nodes} - {"BACKGROUND", "OUTPUT_WORLD"})
            if kinds:
                info["nodes"] = common._cap(kinds, 8)
            sky = next((n for n in tree.nodes if n.type == "TEX_SKY"), None)
            if sky is not None:
                info["sky_type"] = sky.sky_type
        return info
