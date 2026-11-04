"""Run what a step asked for with zone(), place() and scatter(), on Blender's main thread after the step's code:
lay out the areas, place the things, spread the copies, and say what could not be done."""

import bpy

from ..scene.common import _update
from ..scene.step_namespace import attach, copy_thing
from . import geometry as geo
from . import area_rules, relations, scatter, scene_io, solver, zones
from .grid import Grid

BIG_THING_M2 = 25.0  # things this large (a mountain, a lake) keep areas off them
REPORT_MAX = 12


def run(scene, requests, may_move, rules=()):
    """Carry out ``requests`` (``[(kind, relation)]``) in ``scene``. ``may_move(obj)``: whether the chat may move
    this object (its own, or made by this step). ``rules``: how the request relates its places
    (``area_rules.parse``), filled into zone() requests that leave the relation out. Returns a short report for the
    step's result, or ``None``."""
    if not requests:
        return None
    _update(scene)
    report = {"unplaced": []}
    zone_reqs = [r for kind, r in requests if kind == "zone"]
    place_reqs = [r for kind, r in requests if kind == "place"]
    scatter_reqs = [r for kind, r in requests if kind == "scatter"]
    domain = scene_io.ground(scene, list(scene.objects))  # the person's ground counts too
    things = scene_io.things(scene)
    if zone_reqs:
        report["zones"] = _zones(scene, zone_reqs, things, domain, report["unplaced"], rules)
        _update(scene)
        things = scene_io.things(scene)
    areas = {}
    for obj in scene_io.zone_objects(scene):
        area = scene_io.zone_area(obj)
        if area is not None:
            areas[area.name] = area
            areas[obj.name] = area
    moving = {}
    for rel in place_reqs:
        found = things.get(rel["thing"])
        if found is None:
            guess = relations.closest(rel["thing"], things)
            report["unplaced"].append({"thing": rel["thing"], "rule": "no thing named %s%s" % (
                rel["thing"], "; did you mean %s?" % guess if guess else "")})
        elif not may_move(found[0]):
            report["unplaced"].append({"thing": rel["thing"], "rule": "not one of the chat's things"})
        else:
            moving[rel["thing"]] = (found[0], rel)
    if moving:
        grown = []
        report["placed"] = _things(scene, moving, things, areas, domain, report["unplaced"], grown)
        if grown:
            report["zones_grown"] = grown
    if scatter_reqs:
        _update(scene)
        report["scattered"] = _scatter(scene, scatter_reqs, scene_io.things(scene), areas, domain, may_move,
                                       report["unplaced"])
    _update(scene)
    report["unplaced"] = report["unplaced"][:REPORT_MAX]
    return {k: v for k, v in report.items() if v}


def _zones(scene, reqs, things, domain, unplaced, rules=()):
    zone_empties = {scene_io._zone_name(o): o for o in scene_io.zone_objects(scene)}
    names = set(zone_empties) | {r["zone"] for r in reqs}
    stated = {}
    if rules:
        honoured = []
        for req in reqs:
            req, said = area_rules.honour(req, rules, list(things), names)
            honoured.append(req)
            stated[req["zone"]] = said
        reqs = honoured
    existing = {}
    for name, obj in zone_empties.items():
        area = scene_io.zone_area(obj)
        if area is not None:
            existing[name] = area
    inside_zone = {o.name for z in zone_empties.values() for o in z.children_recursive}
    big = {name: scene_io.flat(box) for name, (obj, box) in things.items()}  # what an area may ring or lie near
    for name, box in scene_io.obstacles(scene):
        if name not in inside_zone and _area(box) >= BIG_THING_M2:
            big["%s#%d" % (name, len(big))] = box  # one entry per large part: a mountain, a lake, a hall
    for name in [n for n in big if "#" not in n]:  # a whole thing's box only names it; its parts block areas
        big[name] = (big[name], "reference")
    laid, failed = zones.solve(reqs, existing, big, domain)
    unplaced.extend(failed)
    probe = scene_io.Ground(scene, scene.view_layers[0].depsgraph)
    out = {}
    by_name = {r["zone"]: r for r in reqs}
    for name, area in laid.items():
        obj = zone_empties.get(name) or scene.objects.get(name) or scene.objects.get("Zone " + name)
        if obj is None:
            obj = bpy.data.objects.new("Zone " + name, None)
            obj.empty_display_type = "PLAIN_AXES"
            scene.collection.objects.link(obj)
        cx, cy = area.centre if area.is_ring else geo.box_centre(area.box)
        hit = probe.hit(cx, cy)
        z = hit[0] if hit else 0.0
        world = obj.matrix_world.copy()
        world.translation = (cx, cy, z)
        obj.matrix_world = world  # what stands in the area moves with it
        obj["zone"] = True
        req = by_name[name]
        if area.is_ring:
            obj["ring"] = [round(area.inner, 2), round(area.outer, 2)]
            if "size" in obj:
                del obj["size"]
            out[name] = {"ring_m": [round(area.inner, 1), round(area.outer, 1)], "centre": [round(cx, 1), round(cy, 1)]}
        else:
            w, d = geo.box_size(area.box)
            obj["size"] = [round(w, 2), round(d, 2)]
            out[name] = {"centre": [round(cx, 1), round(cy, 1)], "size": [round(w, 1), round(d, 1)]}
        apart = [m for k, m in (req.get("apart") or {}).items()]
        if apart:
            obj["apart_m"] = max(apart)
        if req.get("inside"):
            obj["inside"] = req["inside"]
        if req.get("holds"):
            obj["holds"] = req["holds"]
        for key, value in (stated.get(name) or {}).items():  # what the request states, for the zone check
            obj["stated_" + key] = value
    return out


def _area(box):
    w, d = geo.box_size(box)
    return w * d


def _things(scene, moving, things, areas, domain, unplaced, grown=None):
    world = solver.World(areas=areas, domain=domain)
    for name, (obj, box) in things.items():
        if name not in moving:
            world.boxes[name] = scene_io.flat(box)
    for name, box in scene_io.obstacles(scene, skip=set(moving)):
        world.grid.add(box, name)
    items, feet = [], {}
    for name, (obj, rel) in moving.items():
        foot = scene_io.footprint(obj)
        if foot is None:
            unplaced.append({"thing": name, "rule": "it has no shape yet: build it, then place it"})
            continue
        size, offset, base = foot
        feet[name] = (obj, size, offset, base)
        items.append(solver.Item(name, size, offset, rel))
        _grow_zone(scene, areas, rel.get("zone"), size, name, grown)
    kept = {name: obj.matrix_world.copy() for name, (obj, _s, _o, _b) in feet.items()}
    for obj, _s, _o, _b in feet.values():  # out of every ray while the spots are picked
        scene_io.sink(obj)
    placed = {}
    try:
        _update(scene)
        probe = scene_io.Ground(scene, scene.view_layers[0].depsgraph)
        world.valid = lambda name, x, y, on: probe.check(x, y, on)
        placed, failed = solver.solve(items, world)
        unplaced.extend(failed)
        for name, (obj, size, offset, base) in feet.items():
            if name in placed:
                x, y, turn = placed[name]
                box = geo.turned_box(x, y, size, offset, turn)
                obj.matrix_world = kept[name]
                scene_io.move(obj, x, y, scene_io.rest_height(probe, box, base), turn)
                _join_zone(scene, obj, moving[name][1].get("zone"))
    finally:
        for name, (obj, _s, _o, _b) in feet.items():
            if name not in placed:  # back where the model built it
                obj.matrix_world = kept[name]
    return len(placed)


def _grow_zone(scene, areas, zone, size, thing, grown):
    """A zone too small for the thing placed in it grows to fit, on its empty too, and the report says so; seen
    when a bandit camp's tents were larger than the camp's area and stayed where they were built."""
    area = areas.get(zone) if zone else None
    bigger = geo.grown_for(area, size) if area is not None else None
    if bigger is None:
        return
    for key, value in list(areas.items()):
        if value is area:
            areas[key] = bigger
    for obj in scene_io.zone_objects(scene):
        if scene_io.zone_area(obj) is not None and scene_io.zone_area(obj).name == area.name:
            if bigger.is_ring:
                obj["ring"] = [round(bigger.inner, 2), round(bigger.outer, 2)]
            else:
                obj["size"] = [round(bigger.box[2] - bigger.box[0], 2), round(bigger.box[3] - bigger.box[1], 2)]
    if grown is not None:
        size_now = geo.box_size(bigger.bounds)
        grown.append({"zone": area.name, "for": thing, "size": [round(size_now[0], 1), round(size_now[1], 1)]})


def _join_zone(scene, obj, zone):
    """Put a thing placed in an area under that area's empty, where it stands, so moving the area moves it and
    the area becomes its parent thing."""
    if not zone:
        return
    holder = scene.objects.get("Zone " + zone) or scene.objects.get(zone)
    if holder is None or not holder.get("zone") or holder is obj:
        return
    if obj.parent is not holder:
        attach(obj, holder)  # from the objects' own matrices: no scene update needed


def _scatter(scene, reqs, things, areas, domain, may_move, unplaced):
    out = {}
    probe = scene_io.Ground(scene, scene.view_layers[0].depsgraph)
    for req in reqs:
        found = things.get(req["scatter"])
        area = areas.get(req["zone"])
        if found is None or area is None:
            what = req["scatter"] if found is None else req["zone"]
            unplaced.append({"thing": req["scatter"], "rule": "no %s named %s" % (
                "thing" if found is None else "area", what)})
            continue
        source = found[0]
        if not may_move(source):
            unplaced.append({"thing": req["scatter"], "rule": "not one of the chat's things"})
            continue
        foot = scene_io.footprint(source)
        if foot is None:
            continue
        size, _offset, base = foot
        grid = Grid()
        for name, box in scene_io.obstacles(scene, skip={source.name}):
            grid.add(box, name)
        radius = max(size) / 2
        spots = scatter.spots(area, req["count"], radius, grid, req["gap_m"], req["size"], req["turn"], req["seed"],
                              valid=lambda x, y: probe.check(x, y, "ground"))
        holder = scene.objects.get("Zone " + req["zone"]) or scene.objects.get(req["zone"])
        made = 0
        for i, (x, y, turn, scale) in enumerate(spots):
            hit = probe.hit(x, y)
            z = (hit[0] if hit else 0.0) - base * scale
            if i == 0:  # the original is the first of them
                scene_io.move(source, x, y, z, turn)
                continue
            copy = copy_thing(source, (x, y, z), turn, scale, scene)
            if holder is not None and holder.get("zone"):
                attach(copy, holder)
            made += 1
        out[req["scatter"]] = made + (1 if spots else 0)
        if len(spots) < req["count"]:
            unplaced.append({"thing": req["scatter"], "rule": "room for %d of %d in %s" % (
                len(spots), req["count"], req["zone"])})
    return out
