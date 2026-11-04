"""Pick a spot and a turn for each thing so its relations hold.

Hard rules filter candidate spots (inside its area, on its surface, never through another thing, far enough from
what it must stay apart from); soft rules score the rest (near, around, in a row); the best spot that also passes
``valid`` (the Blender side's check of what is under it) wins. A thing with no spot is reported with the rule
that failed. Ideas from Holodeck (hard filters before soft scores, anchors first) and Infinigen (a hard rule
narrows where candidates are drawn); no code from either."""

import math
import random
from collections import Counter
from dataclasses import dataclass, field

from . import geometry as geo
from .grid import Grid
from .relations import ON_GROUND

CANDIDATES = 40  # spots tried per thing
RETRY_CANDIDATES = 300  # spots tried again, with half the gap, for a thing that found none
VALID_TRIES = 6  # best-scoring spots checked against what is under them
NEAR_SPAN_M = 10.0  # how far past its target a thing may stand when ``near`` gives no max
ZONE_SLACK_M = 0.3
ZONE_SLACK_SHARE = 0.03  # of an area's size: a thing as large as its area (a wall around a village) still fits


@dataclass
class Item:
    name: str
    size: tuple  # footprint width and depth, metres, in the thing's own axes
    offset: tuple = (0.0, 0.0)  # footprint centre from the thing's origin, in its own axes
    rel: dict = field(default_factory=dict)  # from relations.thing


@dataclass
class World:
    """What already stands and where things may go."""

    areas: dict = field(default_factory=dict)  # zone name -> geometry.Area
    boxes: dict = field(default_factory=dict)  # thing name -> footprint box (other things, and those placed now)
    grid: Grid = field(default_factory=Grid)  # every footprint, tagged with its thing's name
    domain: object = None  # geometry.Area of the ground, or None
    valid: object = None  # (name, x, y, on) -> True, or the reason the spot cannot hold the thing


def _centre_of(world, name):
    if name in world.boxes:
        return geo.box_centre(world.boxes[name])
    if name in world.areas:
        area = world.areas[name]
        return area.centre if area.is_ring else geo.box_centre(area.box)
    return None


def _radius(box):
    w, d = geo.box_size(box)
    return math.hypot(w, d) / 2


def _targets(item):
    out = []
    for key in ("near", "around", "facing", "against"):
        value = item.rel.get(key)
        to = value[0] if isinstance(value, tuple) else (value.get("to") if isinstance(value, dict) else value)
        if isinstance(to, str):
            out.append(to)
    return out


def _order(items):
    """Things others refer to first, then larger before smaller."""
    named = Counter()
    names = {i.name for i in items}
    for item in items:
        for key in ("near", "around", "facing", "against"):
            value = item.rel.get(key)
            to = value[0] if isinstance(value, tuple) else (value.get("to") if isinstance(value, dict) else value)
            if to in names:
                named[to] += 1
    return sorted(items, key=lambda i: (-named[i.name], -(i.size[0] * i.size[1])))


def solve(items, world, seed=0):
    """``({name: (x, y, turn)}, [{"thing", "rule"}])``. ``world.boxes`` and ``world.grid`` grow with each placed
    thing, so later things keep clear of earlier ones."""
    rng = random.Random(seed)
    referred = {to for item in items for to in _targets(item)}
    placed, unplaced = {}, []
    groups = Counter()
    slots = Counter()
    for item in items:
        key = _group_key(item)
        if key:
            groups[key] += 1
    for item in _order(items):
        key = _group_key(item)
        slot = slots[key]
        if key:
            slots[key] += 1
        anchor = item.name in referred
        spot, reason = _place_one(item, world, rng, CANDIDATES, item.rel.get("gap_m", 0.5), (slot, groups[key]),
                                  anchor)
        if spot is None:
            spot, retry = _place_one(item, world, rng, RETRY_CANDIDATES, item.rel.get("gap_m", 0.5) / 2,
                                     (slot, groups[key]), anchor)
            reason = retry if spot is None else reason
        if spot is None:
            unplaced.append({"thing": item.name, "rule": reason})
            continue
        x, y, turn = spot
        box = geo.turned_box(x, y, item.size, item.offset, turn)
        world.boxes[item.name] = box
        world.grid.add(box, item.name)
        placed[item.name] = spot
    return placed, unplaced


def _group_key(item):
    if item.rel.get("around"):  # one ring per target and radius: tents at 6 m and people at the fire are two rings
        return ("around", item.rel["around"]["to"], item.rel["around"]["radius_m"])
    if item.rel.get("row"):
        row = item.rel["row"]
        return ("row", str(row["from"]), str(row["to"]))
    return None


def _point(world, value):
    if isinstance(value, str):
        return _centre_of(world, value)
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        return None


def _place_one(item, world, rng, tries, gap, slot, anchor=False):
    rel = item.rel
    area = None
    if rel.get("zone"):
        area = world.areas.get(rel["zone"])
        if area is None:
            return None, "no area named %s" % rel["zone"]
    surface = None
    if rel.get("on") not in (None, ON_GROUND):
        surface = world.boxes.get(rel["on"])
        if surface is None:
            return None, "no thing named %s to stand on" % rel["on"]
    draw, turn_of, score = _shape(item, world, area, surface, slot, anchor)
    if draw is None:
        return None, turn_of  # turn_of holds the reason here
    ignore = {item.name, rel.get("on")}
    fails = Counter()
    good = []
    for _ in range(tries):
        x, y = draw(rng)
        turn = turn_of(x, y, rng)
        box = geo.turned_box(x, y, item.size, item.offset, turn)
        why = _hard(item, world, area, surface, box, gap, ignore)
        if why:
            fails[why] += 1
            continue
        good.append((score(x, y), x, y, turn))
    if not good:
        return None, fails.most_common(1)[0][0] if fails else "no spot"
    good.sort(key=lambda g: g[0])
    for _score, x, y, turn in good[:VALID_TRIES]:
        verdict = world.valid(item.name, x, y, rel.get("on")) if world.valid else True
        if verdict is True:
            return (x, y, turn), None
        fails[verdict] += 1
    return None, fails.most_common(1)[0][0]


def _shape(item, world, area, surface, slot, anchor=False):
    """``(draw(rng) -> (x, y), turn(x, y, rng), score(x, y))`` for this thing's relations."""
    rel = item.rel
    reach = math.hypot(*item.size) / 2
    facing = _point(world, rel["facing"]) if rel.get("facing") else None
    if rel.get("facing") and facing is None:
        return None, "no thing named %s to face" % rel["facing"], None

    def free_turn(x, y, rng):
        if facing is not None:
            return geo.facing_turn(x, y, facing[0], facing[1])
        return rng.choice(geo.TURNS)

    def flat(x, y):
        return 0.0

    base = surface or (area.bounds if area else (world.domain.bounds if world.domain else (-50, -50, 50, 50)))

    first = [True]

    def in_base(rng):
        if area is not None and surface is None:
            if first[0]:  # the middle first: a thing nearly as large as its area fits only there
                first[0] = False
                return area.centre if area.is_ring else geo.box_centre(area.box)
            return area.sample(rng)
        return rng.uniform(base[0], base[2]), rng.uniform(base[1], base[3])

    if rel.get("around"):
        to = rel["around"]["to"]
        centre = _centre_of(world, to)
        if centre is None:
            return None, "no thing named %s to stand around" % to, None
        target = world.boxes.get(to)
        radius = rel["around"]["radius_m"] or ((_radius(target) if target else 0.0) + reach + rel.get("gap_m", 0.5))
        k, n = slot
        phase = 2 * math.pi * k / max(n, 1)

        def draw(rng):
            a = phase + rng.uniform(-0.25, 0.25) * (2 * math.pi / max(n, 1))
            r = radius * rng.uniform(0.9, 1.15)
            return centre[0] + r * math.cos(a), centre[1] + r * math.sin(a)

        def turn(x, y, rng):
            if facing is not None:
                return geo.facing_turn(x, y, facing[0], facing[1])
            return geo.facing_turn(x, y, centre[0], centre[1])

        def score(x, y):
            return abs(geo.distance((x, y), centre) - radius)
        return draw, turn, score
    if rel.get("row"):
        start, end = _point(world, rel["row"]["from"]), _point(world, rel["row"]["to"])
        if start is None or end is None:
            return None, "row ends must be [x, y] or names of things", None
        k, n = slot
        t = (k + 0.5) / max(n, 1)
        tx, ty = start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t
        along = math.atan2(end[1] - start[1], end[0] - start[0])

        def draw(rng):
            return tx + rng.gauss(0, 0.3), ty + rng.gauss(0, 0.3)

        def turn(x, y, rng):
            return geo.facing_turn(x, y, facing[0], facing[1]) if facing else along

        return draw, turn, lambda x, y: geo.distance((x, y), (tx, ty))
    if rel.get("against"):
        target = world.boxes.get(rel["against"])
        if target is None:
            return None, "no thing named %s to stand against" % rel["against"], None
        half = item.size[1] / 2 + 0.02

        def draw(rng):
            side = rng.randrange(4)
            if side in (0, 1):
                x = rng.uniform(target[0], target[2])
                y = target[1] - half if side == 0 else target[3] + half
            else:
                y = rng.uniform(target[1], target[3])
                x = target[0] - half if side == 2 else target[2] + half
            return x, y

        centre = geo.box_centre(target)

        def turn(x, y, rng):  # back to the target: the front faces away from it
            return geo.facing_turn(x, y, 2 * x - centre[0], 2 * y - centre[1])

        return draw, turn, flat
    if rel.get("near"):
        to, low, high = rel["near"]
        centre = _centre_of(world, to)
        if centre is None:
            return None, "no thing or area named %s to stand near" % to, None
        target = world.boxes.get(to)
        inner = (_radius(target) if target else 0.0) + reach + low
        outer = (_radius(target) if target else 0.0) + reach + (high if high is not None else low + NEAR_SPAN_M)

        def draw(rng):
            if area is not None and rng.random() < 0.5:
                return area.sample(rng)
            a = rng.uniform(0, 2 * math.pi)
            r = math.sqrt(rng.uniform(inner ** 2, max(outer, inner + 0.1) ** 2))
            return centre[0] + r * math.cos(a), centre[1] + r * math.sin(a)

        def score(x, y):
            d = geo.distance((x, y), centre)
            return max(0.0, inner - d) + max(0.0, d - outer)
        return draw, free_turn, score
    if anchor and area is not None:  # what others stand around goes toward its area's middle, leaving them room
        middle = area.centre if area.is_ring else geo.box_centre(area.box)
        return in_base, free_turn, lambda x, y: geo.distance((x, y), middle)
    return in_base, free_turn, flat


def _hard(item, world, area, surface, box, gap, ignore):
    rel = item.rel
    if area is not None and not area.contains_box(box, max(ZONE_SLACK_M, ZONE_SLACK_SHARE * max(
            geo.box_size(area.bounds)))):
        return "no free spot inside %s" % area.name
    if surface is not None and not geo.box_inside(geo.box_around(*geo.box_centre(box), 0, 0), surface):
        return "no room on %s" % rel["on"]
    if surface is None and world.domain is not None and not world.domain.contains_box(box, ZONE_SLACK_M):
        return "no free spot on the ground"
    if world.grid.hit(box, gap, ignore=ignore):
        return "every spot passes through another thing"
    for name, metres in (rel.get("apart") or {}).items():
        other = world.boxes.get(name)
        if other is not None and geo.box_gap(box, other) < metres:
            return "no spot %g m from %s" % (metres, name)
        zone = world.areas.get(name)
        if zone is not None and zone.overlaps_box(geo.box_around(*geo.box_centre(box), metres, metres)):
            return "no spot %g m from %s" % (metres, name)
    return None
