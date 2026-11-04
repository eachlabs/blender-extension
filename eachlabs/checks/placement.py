"""Where the chat's things stand: free space, zones, empty groups, footing, sinking and things off the ground."""

from mathutils import Vector

from .. import scene_tools
from ..placement.settle import HANG_M
from ..things import registry
from ..scene.common import FLAT, GEOMETRY, RAY_REACH, _box, _cap, _r, extent, is_root, is_thing, walkable


STAND_ROOTS_MAX = 60  # newest root objects whose footing read_scene checks
STAND_LIST_MAX = 10  # entries per footing list in read_scene
NEW_GAPS_ROOTS = 15  # newest things of a run whose parts' gaps read_scene measures
ZONE_SLACK = 0.1  # share of a zone's size a thing's middle may stand past its edge
UNDERFILLED = 0.6  # share of the things an area should hold (zone(holds=)) below which it reads as sparse
GROUND_FIT_AREA = 4.0  # a ground this many times the areas' extent is far larger than the scene
GROUND_FIT_OFF = 0.25  # the areas' middle this share of the ground's size off its middle: in a corner
COVER_REACH = 6.0  # metres above a thing within which another of the chat's things counts as over it
REST_M = 0.03  # a thing whose bottom is this close to another's top rests on it (books on a table): not over it
# Metres a thing may sit into what holds it before it reads as sunk: a soft cushion's give and small modelling
# slop stay under it, a cat half inside a seat does not.
SINK_TOLERANCE = 0.03
SINK_HOLDER_MIN = 0.8  # metres: a thing sunk into something smaller than this is not listed
SINK_GRID = (0.25, 0.5, 0.75)  # points across a thing's footprint, each way, where its base is measured
SINK_SHARE = 0.3  # share of those points that must be sunk, so one corner over an edge does not count
# A thing whose base hangs this far over the surface under it everywhere floats (snow caps metres over their
# peaks); smaller things (a bird, a hanging sign) and things meant to hover are the model's to judge. A thing whose
# top touches something over it hangs from it (a lamp on its rod from the ceiling) and does not float.
FLOAT_GAP = 0.15
FLOAT_SIZE_MIN = 1.0  # metres: smaller things are not listed as floating


class PlacementChecks:
    def _free_space(self, mine):
        """``{"ground": [x0, y0, x1, y1], "areas": [...]}``: the extent of the chat's flat ground pieces and the
        biggest empty rectangles on it, from the footprints of everything else of its own; ``None`` without ground."""
        grounds, solids = [], []
        for obj in mine:
            if obj.type not in GEOMETRY or obj.hide_render:
                continue
            low, high = _box(obj)
            w, d, h = high[0] - low[0], high[1] - low[1], high[2] - low[2]
            if not walkable(obj):  # water: not ground, and nothing new goes on it
                solids.append((low[0], low[1], high[0], high[1]))
            elif h <= FLAT * max(w, d) and w * d >= 4.0:
                grounds.append((low[0], low[1], high[0], high[1]))
            else:
                solids.append((low[0], low[1], high[0], high[1]))
        if not grounds:
            return None
        ground = (min(g[0] for g in grounds), min(g[1] for g in grounds), max(g[2] for g in grounds),
                  max(g[3] for g in grounds))
        return {"ground": _r(ground, 1), "areas": scene_tools.free_areas(ground, solids)}

    def _zones(self, mine):
        """The areas the model laid out (an empty with ``zone`` set and a ``size`` = [width, depth] or a ``ring`` =
        [inner, outer] metres around it), each with what is wrong: things under it standing outside it, areas
        overlapping each other (an area inside another one does not count), and areas closer to another than the
        ``apart_m`` the model gave. A ground much larger than the areas, or with them in one corner, is listed as
        ``ground_fit`` on the first entry. ``None`` without zones."""
        from ..placement import geometry as geo
        from ..placement import scene_io

        zones = [(obj, scene_io.zone_area(obj)) for obj in mine if obj.get("zone")]
        zones = [(obj, area) for obj, area in zones if area is not None]
        if not zones:
            return None
        names = {obj: scene_io._zone_name(obj) for obj, _area in zones}
        out = []
        for obj, area in zones:
            if area.is_ring:
                entry = {"name": obj.name, "centre": _r(area.centre, 1), "ring_m": _r((area.inner, area.outer), 1)}
            else:
                entry = {"name": obj.name, "centre": _r(geo.box_centre(area.box), 1),
                         "size": _r(geo.box_size(area.box), 1)}
            w, d = geo.box_size(area.bounds)
            slack = ZONE_SLACK * max(w, d) if not area.is_ring else ZONE_SLACK * (area.outer - area.inner)
            outside = []
            for part in obj.children_recursive:
                if part.type not in GEOMETRY or part.hide_render or part.get("zone"):
                    continue
                low, high = _box(part)
                if not area.contains_point((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, slack):
                    thing = part
                    while thing.parent is not None and thing.parent is not obj:
                        thing = thing.parent  # the thing of the zone this part belongs to
                    outside.append(thing.name)
            if outside:
                entry["outside"] = _cap(sorted(set(outside)), STAND_LIST_MAX)
            apart = obj.get("apart_m")
            overlapping, close = [], []
            for other, oarea in zones:
                if other is obj or obj.get("inside") == names[other] or other.get("inside") == names[obj]:
                    continue
                if area.overlaps(oarea):
                    overlapping.append(other.name)
                    continue
                gap = geo.box_gap(area.bounds, oarea.bounds)
                if isinstance(apart, (int, float)) and gap < apart:
                    close.append({"zone": other.name, "gap_m": round(gap, 1), "apart_m": apart})
            if overlapping:
                entry["overlaps"] = overlapping
            if close:
                entry["too_close"] = close
            wrong = self._stated_relation(obj, area, zones, names)
            if wrong:
                entry["relation_unmet"] = wrong
            holds = obj.get("holds")
            if isinstance(holds, int) and holds > 0:
                count = self._things_in(obj, names[obj], mine)
                if count == 0:
                    count = self._parts_in(area, mine)
                if count < UNDERFILLED * holds:
                    entry["underfilled"] = {"things": count, "holds": holds}
            out.append(entry)
        fit = self._ground_fit(mine, [area for _obj, area in zones])
        if fit:
            out[0]["ground_fit"] = fit
        return out

    @staticmethod
    def _things_in(zone, name, mine):
        """The things standing in an area: its direct children with geometry, and the things whose parent thing
        is the area."""
        things = {o.session_uid for o in zone.children if not o.get("zone")
                  and (o.type in GEOMETRY or any(p.type in GEOMETRY for p in o.children_recursive))}
        area = registry.thing_of(zone)
        if area:
            roots = registry.roots(mine)
            things |= {r.session_uid for tid, r in roots.items()
                       if registry.parent_of(r, roots) == area and not r.get("zone")}
        return len(things)

    @staticmethod
    def _parts_in(area, mine):
        """For an area nothing was placed in by name: the parts with geometry standing in it. A thing has at least
        one part, so a count under ``holds`` here is under it in things too, and an area built by coordinates is not
        reported as empty."""
        count = 0
        for o in mine:
            if o.type not in GEOMETRY or o.hide_render or o.get("zone"):
                continue
            low, high = _box(o)
            count += area.contains_point((low[0] + high[0]) / 2, (low[1] + high[1]) / 2)
        return count

    def _stated_relation(self, obj, area, zones, names):
        """What the area fails of the relation the request states for it (around a thing, inside an area)."""
        import bpy

        from ..placement import area_rules, scene_io

        stated = {k[len("stated_"):]: obj[k] for k in obj.keys() if k in ("stated_around", "stated_inside")}
        if not stated:
            return None
        target_box = parent = None
        if stated.get("around"):
            target = bpy.data.objects.get(stated["around"])
            box = scene_io.world_box(target) if target is not None else None
            if box is not None:
                target_box = scene_io.flat(box)
            else:  # an area named as the target
                ring_of = next((a for o, a in zones if names[o] == stated["around"]), None)
                target_box = ring_of.bounds if ring_of is not None else None
        if stated.get("inside"):
            parent = next((a for o, a in zones if names[o] == stated["inside"]), None)
        return area_rules.unmet(area, stated, target_box, parent)

    def _ground_fit(self, mine, areas):
        """What is wrong with the ground's size against the areas laid out on it, or ``None``."""
        from ..placement import geometry as geo
        from ..placement import scene_io

        ground = scene_io.ground(None, mine)
        if ground is None:
            return None
        used = geo.union(a.bounds for a in areas)
        gw, gd = geo.box_size(ground.box)
        uw, ud = geo.box_size(used)
        gx, gy = geo.box_centre(ground.box)
        ux, uy = geo.box_centre(used)
        off = max(abs(ux - gx) / max(gw, 1.0), abs(uy - gy) / max(gd, 1.0))
        if gw * gd > GROUND_FIT_AREA * max(uw * ud, 1.0) or off > GROUND_FIT_OFF:
            return {"ground_m": _r((gw, gd), 0), "areas_m": _r((uw, ud), 0), "areas_centre": _r((ux, uy), 0),
                    "ground_centre": _r((gx, gy), 0)}
        return None

    def _empty_groups(self, mine):
        """Root empties of the chat's with no geometry under them, which a request may name but which hold
        nothing: their parts were built as other objects. Zones, aim points and holders of lights or cameras are
        not listed."""
        aimed = {c.target.session_uid for o in self.scene.objects for c in getattr(o, "constraints", ())
                 if getattr(c, "target", None) is not None}
        out = []
        for obj in mine:
            if obj.type != "EMPTY" or obj.parent is not None or obj.get("zone") or obj.session_uid in aimed:
                continue
            under = list(obj.children_recursive)
            if any(o.type in GEOMETRY or o.type in ("LIGHT", "CAMERA") for o in under):
                continue
            out.append(obj.name)
        return _cap(out, STAND_LIST_MAX)

    def _new_gaps(self, mine):
        """Parts that almost touch the rest of their thing but float off it, for the things this run made:
        ``[{"thing", "parts", "gap_m"}]``."""
        made = set(self.created_since(self.since))
        roots = [o for o in mine if o.name in made and is_thing(o) and o.children][-NEW_GAPS_ROOTS:]
        out = []
        for root in roots:
            try:
                found = self.part_gaps(root.name)
            except (RuntimeError, ReferenceError):
                continue
            out.extend(dict(entry, thing=root.name) for entry in found[:2])
            if len(out) >= STAND_LIST_MAX:
                break
        return out[:STAND_LIST_MAX]

    def _outside_ground(self, mine, ground):
        """Parts of this run's things whose middle lies off the ground's extent: ``[{"thing", "parts", "count"}]``."""
        if ground is None:
            return []
        x0, y0, x1, y1 = ground
        made = set(self.created_since(self.since))
        own = {o.session_uid for o in mine}
        found = {}
        for obj in mine:
            if obj.name not in made or obj.type not in GEOMETRY or obj.hide_render or not walkable(obj):
                continue
            low, high = _box(obj)
            cx, cy = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                continue
            if high[2] - low[2] <= FLAT * max(high[0] - low[0], high[1] - low[1]):
                continue  # a piece of ground itself
            root = obj
            while not is_root(root) and root.parent.session_uid in own:
                root = root.parent
            found.setdefault(self._label(root), []).append(obj.name)
        return _cap([{"thing": thing, "parts": _cap(parts, 4), "count": len(parts)}
                     for thing, parts in found.items()], STAND_LIST_MAX)

    def _footing(self, scene):
        """``{"on_not_walkable": [...], "nothing_below": [...], "under": [...], "sunk_into": [...]}`` for the root
        objects this run made (the newest ``STAND_ROOTS_MAX``): what each stands on, from a ray down through its
        middle, what of the chat's hangs right over it, from a ray up, and what it sinks into, from its base across
        its footprint. Only problems are listed; the model decides which are meant (a boat on water, a bench under
        a tree, a rock set into the ground)."""
        names = set(self.created_since(self.since))
        roots = [o for o in self._objects() if o.name in names and is_thing(o) and o.type not in ("LIGHT", "CAMERA")]
        roots = roots[-STAND_ROOTS_MAX:]
        if not roots:
            return {}
        depsgraph = self._depsgraph(scene)
        on_water, floating, under, sunk, hovering = [], [], [], [], []
        for root in roots:
            tree = [root] + list(root.children_recursive)
            boxes = [_box(o) for o in tree if o.type in GEOMETRY and not o.hide_render]
            if not boxes or not walkable(root):
                continue
            low = [min(b[0][i] for b in boxes) for i in range(3)]
            high = [max(b[1][i] for b in boxes) for i in range(3)]
            if high[2] - low[2] <= FLAT * max(high[0] - low[0], high[1] - low[1]):
                continue  # ground and roads lie on things; they are not checked
            own = {o.session_uid for o in tree}
            x, y = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2
            start = Vector((x, y, low[2] + min(0.5, (high[2] - low[2]) / 2)))
            below = self._first_other(scene, depsgraph, start, Vector((0, 0, -1)), own, RAY_REACH)
            if below is None:
                floating.append(root.name)
            elif not walkable(below[0]):
                on_water.append({"thing": root.name, "on": self._label(below[0])})
            over = self._first_other(scene, depsgraph, Vector((x, y, high[2] + 0.01)), Vector((0, 0, 1)), own,
                                     COVER_REACH)
            if (over is not None and self._mine(over[0]) and _box(over[0])[0][2] > high[2] + REST_M
                    and self._root_label(over[0]) not in self._labels_below(scene, depsgraph, start, own)
                    and not self._hangs(scene, depsgraph, self._root_of(over[0]))):
                under.append({"thing": root.name, "under": self._root_label(over[0]), "gap_m": round(over[1], 2)})
            if (below is not None and max(high[i] - low[i] for i in range(3)) >= FLOAT_SIZE_MIN
                    and not self._hangs(scene, depsgraph, root)):
                gap = self._float_gap(scene, depsgraph, own, low, high)
                if gap is not None:
                    hovering.append({"thing": root.name, "over": self._root_label(gap[0]), "gap_m": round(gap[1], 2)})
            into = self._sunk(scene, depsgraph, own, low, high)
            holder = extent(into[0]) if into is not None else None
            if holder is not None and max(holder["size"]) < SINK_HOLDER_MIN:
                into = None  # small pieces in a heap (flame tongues, stones of a pile) overlap on purpose
            if into is not None:
                sunk.append({"thing": root.name, "into": self._root_label(into[0]), "depth_m": round(into[1], 2)})
        out = {}
        if sunk:
            out["sunk_into"] = _cap(sunk, STAND_LIST_MAX)
        if on_water:
            out["on_not_walkable"] = _cap(on_water, STAND_LIST_MAX)
        if floating:
            out["nothing_below"] = _cap(floating, STAND_LIST_MAX)
        if under:
            out["under"] = _cap(under, STAND_LIST_MAX)
        if hovering:
            out["floats_above"] = _cap(hovering, STAND_LIST_MAX)
        return out

    def _root_of(self, obj):
        while obj.parent is not None and self._mine(obj.parent) and not obj.parent.get("zone"):
            obj = obj.parent
        return obj

    def _hangs(self, scene, depsgraph, root):
        """True when something not ``root``'s own lies within ``HANG_M`` over its top: it hangs from it (a lamp on
        its rod from the ceiling), so what is under it was not put under it, and it does not float."""
        tree = [root] + list(root.children_recursive)
        boxes = [_box(o) for o in tree if o.type in GEOMETRY and not o.hide_render]
        if not boxes:
            return False
        low = [min(b[0][i] for b in boxes) for i in range(3)]
        high = [max(b[1][i] for b in boxes) for i in range(3)]
        own = {o.session_uid for o in tree}
        for fx in SINK_GRID:
            for fy in SINK_GRID:
                start = Vector((low[0] + fx * (high[0] - low[0]), low[1] + fy * (high[1] - low[1]), high[2] - 0.01))
                if self._first_other(scene, depsgraph, start, Vector((0, 0, 1)), own, HANG_M + 0.01) is not None:
                    return True
        return False

    def _labels_below(self, scene, depsgraph, start, own):
        """The things of every surface straight under ``start``, not ``own``'s: a thing with one of them over it
        too stands inside it (a room's ceiling over its floor, a bookshelf's top over its boards), not under it."""
        found, origin, travelled, down = set(), start.copy(), 0.0, Vector((0, 0, -1))
        for _ in range(64):
            hit, location, _normal, _index, obj, _matrix = scene.ray_cast(depsgraph, origin, down,
                                                                          distance=RAY_REACH - travelled)
            if not hit or obj is None:
                break
            travelled += (location - origin).length + 1e-3
            origin = location + down * 1e-3
            if obj.original.session_uid not in own:
                found.add(self._root_label(obj.original))
        return found

    def _float_gap(self, scene, depsgraph, own, low, high):
        """``(object, gap)`` when a thing's base hangs over the surface under it at every measured point of its
        footprint, the smallest gap being more than ``FLOAT_GAP``; else ``None``. Measured straight down from its
        own base, so a cap over a sloped peak counts by its lowest corner."""
        gaps = []
        down = Vector((0, 0, -1))
        for fx in SINK_GRID:
            for fy in SINK_GRID:
                origin = Vector((low[0] + fx * (high[0] - low[0]), low[1] + fy * (high[1] - low[1]), high[2] + 0.01))
                base, travelled = None, 0.0
                for _ in range(64):  # the thing's lowest surface here, then the first other surface under it
                    hit, location, _normal, _index, obj, _matrix = scene.ray_cast(
                        depsgraph, origin, down, distance=RAY_REACH - travelled)
                    if not hit or obj is None:
                        break
                    travelled += (location - origin).length + 1e-4
                    origin = location + down * 1e-4
                    if obj.original.session_uid in own:
                        base = location.z
                    elif base is not None and obj.original.type in GEOMETRY:
                        # Again on that object alone, from just above the base: a surface level with the base (a
                        # crate on the ground) is hidden from the scene ray by the base's own face.
                        top = self._surface_under(obj.original, depsgraph,
                                                  Vector((location.x, location.y, base + 0.01)))
                        surface = top if top is not None else location.z
                        # A surface level with the thing's lowest point is what it stands on; the scene ray may
                        # meet it before the thing's own base face when the two lie in one plane.
                        gap = 0.0 if surface >= low[2] - FLOAT_GAP else base - surface
                        gaps.append((obj.original, max(0.0, gap)))
                        break
        if len(gaps) < 2:
            return None
        nearest = min(gaps, key=lambda item: item[1])
        return nearest if nearest[1] > FLOAT_GAP else None

    @staticmethod
    def _surface_under(obj, depsgraph, point):
        """The height of ``obj``'s first surface straight below ``point`` (world space), or ``None``."""
        world = obj.matrix_world
        inverse = world.inverted()
        direction = (inverse.to_3x3() @ Vector((0, 0, -1))).normalized()
        try:
            hit, location, _normal, _index = obj.ray_cast(inverse @ point, direction, depsgraph=depsgraph)
        except (RuntimeError, TypeError):
            return None
        return (world @ location).z if hit else None

    def _sunk(self, scene, depsgraph, own, low, high):
        """``(object, depth)`` when a thing's base lies inside another object, else ``None``. At each point of its
        footprint, a ray up from below finds the thing's own base there, and a ray down from the thing's top finds
        the highest upward surface of another object above that base; the deepest of those counts."""
        measured, deep = 0, []
        for fx in SINK_GRID:
            for fy in SINK_GRID:
                x, y = low[0] + fx * (high[0] - low[0]), low[1] + fy * (high[1] - low[1])
                origin = Vector((x, y, low[2] - 0.01))
                base = self._ray(scene, depsgraph, origin, Vector((0, 0, 1)), high[2] - low[2] + 0.02,
                                 lambda obj, normal: obj.session_uid in own)
                if base is None:
                    continue
                measured += 1
                bottom = origin.z + base[1]
                start = Vector((x, y, high[2] + 0.001))
                hit = self._ray(scene, depsgraph, start, Vector((0, 0, -1)), start.z - bottom,
                                lambda obj, normal: obj.session_uid not in own and obj.type in GEOMETRY
                                and normal.z > 0.3)
                if hit is None or not walkable(hit[0]):
                    continue
                depth = start.z - hit[1] - bottom
                if depth <= SINK_TOLERANCE:
                    continue
                # A part of the thing between that surface and its base means the other object stands in it (a
                # book between a shelf's boards), not the thing in the other object.
                surface = Vector((x, y, start.z - hit[1] - 0.001))
                if self._ray(scene, depsgraph, surface, Vector((0, 0, -1)), depth - 0.01,
                             lambda obj, normal: obj.session_uid in own) is None:
                    deep.append((hit[0], depth))
        if not deep or len(deep) < max(2, SINK_SHARE * measured):
            return None
        return max(deep, key=lambda item: item[1])
