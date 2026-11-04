"""How the request relates its places ("a forest around the mountain", "a village in the forest"), read once by the
plan call and then honoured: zone() requests get the stated relation when they leave it out, and the zone check
reports an area that does not meet it."""

import math

from . import geometry as geo

DEFAULT_RING_M = 60.0  # band width for a ring the request states but zone() gave no size for
RING_COVER_MIN = 0.75  # share of the directions around its target an area must cover to count as around it
_SKIP = frozenset(("the", "a", "an", "of", "zone", "area"))


def words(name):
    out = set()
    for word in str(name).lower().replace("_", " ").replace("-", " ").split():
        word = word.rstrip(".,")
        if word in _SKIP or word.isdigit():
            continue
        out.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return out


def parse(entries):
    """``[{"area", "around"?, "inside"?}]`` from the plan's ``areas`` list, keeping well-formed entries only."""
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("area"), str):
            continue
        rule = {"area": entry["area"].strip()}
        for key in ("around", "inside"):
            if isinstance(entry.get(key), str) and entry[key].strip():
                rule[key] = entry[key].strip()
        if len(rule) > 1:
            out.append(rule)
    return out


def best(name, names):
    """The name in ``names`` that means the same place or thing as ``name`` (see ``same_place``), the closest
    first; ``None`` when none does."""
    target = words(name)
    scored = [(len(target & words(n)), -len(words(n)), n) for n in names if same_place(name, n)]
    return max(scored)[2] if scored else None


def same_place(a, b):
    """True when one name's words all appear in the other's: "bandit camp" and "Bandit camp area", not "small
    village" and "larger village"."""
    wa, wb = words(a), words(b)
    return bool(wa and wb) and (wa <= wb or wb <= wa)


def rule_for(rules, zone_name):
    hits = [r for r in rules if same_place(r["area"], zone_name)]
    return max(hits, key=lambda r: len(words(r["area"]) & words(zone_name))) if hits else None


def honour(req, rules, thing_names, zone_names):
    """``req`` (a relations.area dict) with the request's stated relation filled in where zone() left it out.
    Returns ``(req, stated)``; ``stated`` holds what the request states, for the zone check."""
    rule = rule_for(rules, req["zone"])
    if rule is None:
        return req, {}
    stated = {}
    req = dict(req)
    if rule.get("inside"):
        parent = best(rule["inside"], [z for z in zone_names if z != req["zone"]])
        if parent:
            stated["inside"] = parent
            req["inside"] = req.get("inside") or parent
    if rule.get("around"):
        target = best(rule["around"], list(thing_names) + [z for z in zone_names if z != req["zone"]])
        if target:
            stated["around"] = target
            if not req.get("ring_m"):
                size = req.get("size")
                req["ring_m"] = max(size) / 2 if size else DEFAULT_RING_M
                req["size"] = None
            req["around"] = target
    return req, stated


def ring_cover(area, target_box, samples=36):
    """Share of the directions around ``target_box``'s middle along which ``area`` covers the land just outside it."""
    cx, cy = geo.box_centre(target_box)
    w, d = geo.box_size(target_box)
    reach = math.hypot(w, d) / 2
    hit = 0
    for i in range(samples):
        a = 2 * math.pi * i / samples
        found = False
        for step in range(1, 9):  # look outward from the target's edge, up to its size again
            r = reach * (1 + step / 8)
            if area.contains_point(cx + r * math.cos(a), cy + r * math.sin(a)):
                found = True
                break
        hit += found
    return hit / samples


def unmet(area, stated, target_box=None, parent=None):
    """What the stated relation an area fails, in words, or ``None``."""
    if stated.get("around") and target_box is not None:
        cover = ring_cover(area, target_box)
        if cover < RING_COVER_MIN:
            return "the request puts it around %s, but it covers %d%% of the way round" % (
                stated["around"], round(cover * 100))
    if stated.get("inside") and parent is not None and not parent.contains_box(area.bounds if not area.is_ring
                                                                               else area.bounds, 1.0):
        return "the request puts it inside %s, but it lies outside it" % stated["inside"]
    return None
