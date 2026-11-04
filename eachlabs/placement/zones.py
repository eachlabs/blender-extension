"""Lay out the areas of a scene (villages, a forest, a camp) from what the model says about them.

An area is a box (``size``) or a ring around a thing (``ring_m`` with ``around``). Hard rules: inside the ground,
inside its parent area, not over another area or a big thing, at least ``apart_m`` from what it must stay apart
from. Soft rules: ``near``, and a slight pull toward the middle of the ground so the scene does not sit in a
corner."""

import math
import random
from collections import Counter

from . import geometry as geo

CANDIDATES = 120
CENTRE_PULL = 0.02  # weight of the distance from the ground's middle, against near's metres


def _box(entry):
    """A box from ``boxes``: a plain box, or ``(box, "reference")`` for a thing given only so areas can name it."""
    return entry[0] if isinstance(entry[1], str) else entry


def solve(requests, areas, boxes, domain, seed=0):
    """``({zone name: geometry.Area}, [{"zone", "rule"}])``. ``areas``: areas laid out before (kept unless asked
    for again); ``boxes``: things that stand already, by name; ``domain``: the ground's Area or ``None``."""
    rng = random.Random(seed)
    done = dict(areas)
    for req in requests:
        done.pop(req["zone"], None)
    out, unplaced = {}, []
    for req in _order(requests):
        area, why = _place(req, done, boxes, domain, rng)
        if area is None:
            unplaced.append({"zone": req["zone"], "rule": why})
            continue
        done[req["zone"]] = area
        out[req["zone"]] = area
    return out, unplaced


def _order(requests):
    names = {r["zone"] for r in requests}
    depth = {}

    def level(req, seen=()):
        parent = req.get("inside")
        if parent in names and parent not in seen:
            return 1 + level(next(r for r in requests if r["zone"] == parent), seen + (req["zone"],))
        return 0

    referred = Counter()
    for req in requests:
        depth[req["zone"]] = level(req)
        for key in ("near",):
            if req.get(key) and req[key][0] in names:
                referred[req[key][0]] += 1
        for key in (req.get("apart") or {}):
            if key in names:
                referred[key] += 1

    def size(req):
        if req.get("size"):
            return req["size"][0] * req["size"][1]
        return (req.get("ring_m") or 0) ** 2 * 10
    return sorted(requests, key=lambda r: (depth[r["zone"]], -referred[r["zone"]], -size(r)))


def _related(name, req, done):
    """Areas this one may overlap: its parent and its own children."""
    out = {req.get("inside")}
    for other_name, other in done.items():
        if getattr(other, "parent", None) == name:
            out.add(other_name)
    return out


def _place(req, done, boxes, domain, rng):
    name = req["zone"]
    parent = None
    if req.get("inside"):
        parent = done.get(req["inside"])
        if parent is None:
            return None, "no area named %s to lie inside" % req["inside"]
    if req.get("ring_m"):
        to = req["around"]
        target = _box(boxes[to]) if to in boxes else (done[to].bounds if to in done else None)
        if target is None:
            return None, "no thing or area named %s to ring" % to
        cx, cy = geo.box_centre(target)
        w, d = geo.box_size(target)
        inner = math.hypot(w, d) / 2 + req.get("gap_m", 2.0)
        area = geo.Area(name, centre=(cx, cy), inner=inner, outer=inner + req["ring_m"])
        area.parent, area.apart = req.get("inside"), req.get("apart") or {}
        return area, None
    w, d = req["size"]
    near = req.get("near")
    centre_to = None
    if near:
        centre_to = _box(boxes[near[0]]) if near[0] in boxes else (done[near[0]].bounds if near[0] in done else None)
        if centre_to is None:
            return None, "no thing or area named %s to lie near" % near[0]
    if req.get("around"):  # a box beside a thing: around without ring_m
        centre_to = centre_to or (_box(boxes[req["around"]]) if req["around"] in boxes else None)
    middle = geo.box_centre(domain.bounds) if domain is not None else (0.0, 0.0)
    best, fails = None, Counter()
    for _ in range(CANDIDATES):
        if parent is not None:
            x, y = parent.sample(rng)
        elif centre_to is not None:
            cx, cy = geo.box_centre(centre_to)
            reach = math.hypot(*geo.box_size(centre_to)) / 2 + math.hypot(w, d) / 2
            low = near[1] if near else 0.0
            high = near[2] if near and near[2] is not None else low + max(w, d)
            a = rng.uniform(0, 2 * math.pi)
            r = reach + rng.uniform(low, high)
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        elif domain is not None:
            x, y = domain.sample(rng)
        else:
            x, y = rng.uniform(-200, 200), rng.uniform(-200, 200)
        box = geo.box_around(x, y, w / 2, d / 2)
        why = _hard(name, req, box, parent, done, boxes, domain)
        if why:
            fails[why] += 1
            continue
        score = CENTRE_PULL * geo.distance((x, y), middle)
        if near and centre_to is not None:
            gap = max(0.0, geo.box_gap(box, centre_to))
            score += max(0.0, near[1] - gap) + (max(0.0, gap - near[2]) if near[2] is not None else 0.0)
        if best is None or score < best[0]:
            best = (score, box)
    if best is None:
        return None, fails.most_common(1)[0][0] if fails else "no room"
    area = geo.Area(name, box=best[1])
    area.parent, area.apart = req.get("inside"), req.get("apart") or {}
    return area, None


def _hard(name, req, box, parent, done, boxes, domain):
    if domain is not None and not domain.contains_box(box):
        return "no room for %s on the ground: make the ground larger or the area smaller" % name
    if parent is not None and not parent.contains_box(box):
        return "no room for %s inside %s" % (name, req["inside"])
    related = _related(name, req, done)
    for other_name, other in done.items():
        if other_name not in related and other.overlaps_box(box):
            return "%s would overlap %s" % (name, other_name)
    for thing, tbox in boxes.items():
        if isinstance(tbox[1], str):  # a whole thing's box, given only so areas can name it
            continue
        owner = thing.split("#")[0]
        if owner == req.get("around") or (req.get("near") and owner == req["near"][0]):
            continue
        if geo.boxes_overlap(box, tbox):
            return "%s would cover %s" % (name, owner)
    for other_name, metres in (req.get("apart") or {}).items():
        targets = [n for n in done if n not in related] if other_name == "*" else [other_name]
        for target in targets:
            other = done.get(target)
            obox = other.bounds if other is not None else (_box(boxes[target]) if target in boxes else None)
            if obox is not None and geo.box_gap(box, obox) < metres:
                return "%s must be %g m from %s" % (name, metres, target)
    for other_name, other in done.items():  # apart works both ways: an area laid out earlier may name this one
        wants = getattr(other, "apart", {}) or {}
        metres = wants.get(name, wants.get("*") if other_name not in related else None)
        if metres is not None and geo.box_gap(box, other.bounds) < metres:
            return "%s must be %g m from %s" % (name, metres, other_name)
    return None
