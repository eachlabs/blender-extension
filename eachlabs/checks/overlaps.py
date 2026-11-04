"""Things standing on, in or through each other, for read_scene."""

import re

from .part_groups import _groups, _label, _overlap


OVERLAP_MAX = 8  # entries listed in read_scene's overlaps
STAND_HEIGHT = 1.0  # metres: only a thing this tall (a person, a car, a tree) is checked for where it stands
LIFTED = 0.5  # metres above the bottom of the thing below that count as standing on it; a kerb or a plinth is lower
ON_GAP = 0.15  # metres between a bottom and the top of the part below that count as resting on it
INSIDE_SHARE = 0.25  # of a thing's box inside one part of another thing that counts as being inside it
SOLID_MIN = 0.5  # metres: a part thinner than this (a wall, a panel) holds things in openings, not inside it



def _first_word(name):
    """The first word of a name, split at spaces, underscores and other marks: "House | roof" is "house"."""
    words = re.findall(r"[^\W_]+", name.lower())
    return words[0] if words else name.lower()



def _union(boxes):
    return ([min(b[0][i] for b in boxes) for i in range(3)], [max(b[1][i] for b in boxes) for i in range(3)])



def _volume(box):
    return max(0.0, box[1][0] - box[0][0]) * max(0.0, box[1][1] - box[0][1]) * max(0.0, box[1][2] - box[0][2])



def _shared(a, b):
    return _volume(([max(a[0][i], b[0][i]) for i in range(3)], [min(a[1][i], b[1][i]) for i in range(3)]))



FOOTPRINT_SHARE = 0.1  # of the smaller footprint two things may share before a new one overlaps an existing one



def _things(parts):
    """``(label, key, solid parts, box)`` per thing: a group of ``loose_parts`` or an object in none."""
    groups, how = _groups(parts)
    grouped = {id(p) for members in groups.values() for p in members}
    things = [(_label(key, how), key, [p for p in members if p.get("box") is not None])
              for key, members in groups.items()]
    things += [(p["name"], p["name"], [p]) for p in parts if id(p) not in grouped and p.get("box") is not None]
    return [(label, key, solid, _union([p["box"] for p in solid])) for label, key, solid in things if solid]



def _footprint_share(a, b):
    """The share of the smaller footprint (x and y) that two boxes have in common."""
    w = min(a[1][0], b[1][0]) - max(a[0][0], b[0][0])
    d = min(a[1][1], b[1][1]) - max(a[0][1], b[0][1])
    if w <= 0 or d <= 0:
        return 0.0
    area = min((a[1][0] - a[0][0]) * (a[1][1] - a[0][1]), (b[1][0] - b[0][0]) * (b[1][1] - b[0][1]))
    return w * d / area if area > 1e-9 else 0.0



GROUND_RATIO = 0.1  # a thing this low for its width both ways is ground or terrain



def _ground_like(box):
    w, d, h = (box[1][i] - box[0][i] for i in range(3))
    return h <= GROUND_RATIO * min(w, d)



def overlaps(parts, existing=None):
    """Things of the chat's own that stand on or inside another thing of its own, from bounding boxes. A thing is
    a group of ``loose_parts`` or an object in none; ``parts`` as there. Only things at least ``STAND_HEIGHT`` tall
    are checked, and things named one inside the other ("Car" and "Car_Tyre_1") are one thing. Every entry
    names the thing, the thing it is ``on`` or ``inside``, and that thing's part it touches.
    ``existing``: on a change, the names of the chat's objects from before it; a new thing whose footprint overlaps
    one that existed is listed as ``{"thing": new, "overlaps_existing": old}``."""
    things = _things(parts)

    def related(a, b):  # "House | roof" and "House | walls", "Car" and "Car_Tyre_1": parts of one thing
        return _first_word(a) == _first_word(b)

    found = []
    if existing:
        def age(solid):
            names = {p["name"] for p in solid}
            return "old" if names <= existing else "new" if not names & existing else "mixed"
        tall = [(label, key, box, age(solid)) for label, key, solid, box in things
                if box[1][2] - box[0][2] >= STAND_HEIGHT]
        for label, key, box, kind in tall:
            if kind != "new" or len(found) >= OVERLAP_MAX:
                continue
            for other_label, other_key, other_box, other_kind in tall:
                if other_kind == "old" and not related(key, other_key) and (
                        _footprint_share(box, other_box) > FOOTPRINT_SHARE):
                    found.append({"thing": label, "overlaps_existing": other_label,
                                  "size": [round(box[1][0] - box[0][0], 1), round(box[1][1] - box[0][1], 1)]})
                    break
    for label, key, _solid, box in things:
        low, high = box
        height = high[2] - low[2]
        if height < STAND_HEIGHT or len(found) >= OVERLAP_MAX or _ground_like(box):
            continue
        cx, cy = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2
        for other_label, other_key, other_solid, other_box in things:
            if related(key, other_key) or _ground_like(other_box) or not _overlap(box, other_box, ON_GAP):
                continue  # ground and terrain are stood on, not stood in
            # A part of the other thing over the middle too: the thing stands in an opening of it (a window
            # between a wall's sill and lintel, a person on a building's storey), not on top of it.
            closed = any(p["box"][0][0] <= cx <= p["box"][1][0] and p["box"][0][1] <= cy <= p["box"][1][1]
                         and p["box"][0][2] >= high[2] - ON_GAP for p in other_solid)
            entry = None
            for part in other_solid:
                plow, phigh = part["box"]
                over = plow[0] <= cx <= phigh[0] and plow[1] <= cy <= phigh[1]
                if (over and not closed and abs(low[2] - phigh[2]) <= ON_GAP and low[2] - other_box[0][2] >= LIFTED
                        and phigh[2] - other_box[0][2] >= LIFTED):
                    entry = {"thing": label, "on": other_label}
                elif (_volume(box) > 0 and min(phigh[i] - plow[i] for i in range(3)) >= SOLID_MIN
                      and _shared(box, part["box"]) >= INSIDE_SHARE * _volume(box)):
                    entry = {"thing": label, "inside": other_label}
                if entry:
                    if part["name"] != other_label:  # a single object is its own part
                        entry["part"] = part["name"]
                    break
            if entry:
                found.append(entry)
                break
    return found
