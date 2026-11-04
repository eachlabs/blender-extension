"""Two copies of the same part in one place: the same shape and size, overlapping or nearly so (two clock faces on
one tower, a moved part laid over the one already there). Copies meant to repeat (a row of windows, a forest of
shared trees) stand apart by more than their own size and do not count, nor do three or more set at one steady step
(books side by side on a shelf). Pure: works on plain numbers."""

DUP_SIZE = 0.05  # share by which two parts' sides may differ and still be the same size
DUP_NEAR = 0.25  # share of a part's size on each axis its centre may lie from the other's: the same place
DUP_SLACK_M = 0.05  # metres of that leeway at least, across a thin part (a dial laid a few cm over another)
DUPLICATES_MAX = 8
ROW_SLACK = 0.1  # share of the step between two copies a third may lie off it and still continue their row
FLAT = 0.15  # a part this thin across, as a share of its next side, is flat (a dial, a sign, a panel)
STACK_OVERLAP = 0.25  # share of the smaller face two flat parts must cover of each other to stand one on the other
STACK_GAP_M = 1.0  # most metres between two stacked faces, front to back
SAME_SIZE = 0.35  # share by which two stacked faces' sides may differ for one to be the other's newer version
STOP = {"the", "and", "with", "of", "for", "left", "right", "front", "back", "north", "south", "east", "west",
        "top", "bottom", "part", "mesh", "new", "old", "main"}


def _key(entry):
    sides = sorted(entry["size"])
    return entry["vertices"], tuple(round(s, 2) for s in sides)


def _same_size(a, b):
    for x, y in zip(sorted(a), sorted(b)):
        if abs(x - y) > DUP_SIZE * max(x, y, 1e-6):
            return False
    return True


def _in_row(a, b, group):
    """True when a third copy of ``group`` lies one more step of ``a`` to ``b`` past either of them: the copies repeat
    in a row, set side by side on purpose."""
    step = [b["centre"][k] - a["centre"][k] for k in range(3)]
    length = sum(v * v for v in step) ** 0.5
    if length < 1e-3:
        return False
    for c in group:
        if c is a or c is b:
            continue
        for end, sign in ((b, 1), (a, -1)):
            off = sum((c["centre"][k] - end["centre"][k] - sign * step[k]) ** 2 for k in range(3)) ** 0.5
            if off <= ROW_SLACK * length:
                return True
    return False


def duplicates(parts):
    """``parts``: ``[{"name", "thing", "vertices", "size": [x, y, z], "centre": [x, y, z]}]``. Returns
    ``[{"thing", "part", "copy", "copy_of", "apart_m"}]``, one entry per extra copy, at most ``DUPLICATES_MAX``."""
    buckets = {}
    for entry in parts:
        if entry["vertices"] > 0 and max(entry["size"]) > 0:
            buckets.setdefault(_key(entry), []).append(entry)
    found = []
    for group in buckets.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda e: e["name"])
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if not _same_size(a["size"], b["size"]):
                    continue
                apart = sum((a["centre"][k] - b["centre"][k]) ** 2 for k in range(3)) ** 0.5
                # the same place on every axis: logs stacked in a wall or floorboards side by side are one size
                # apart on one axis and do not count
                if all(abs(a["centre"][k] - b["centre"][k]) <= max(DUP_NEAR * a["size"][k], DUP_SLACK_M)
                       for k in range(3)) and not _in_row(a, b, group):
                    found.append({"thing": b["thing"], "part": b["name"], "copy": b["name"], "copy_of": a["name"],
                                  "apart_m": round(apart, 3)})
                    if len(found) >= DUPLICATES_MAX:
                        return found
    return found


def role_words(name, thing):
    """The words of a part's name that say what it is: its thing's name and side words left out, digits dropped."""
    own = name[len(thing):] if name.lower().startswith(thing.lower()) else name
    cleaned = "".join(c.lower() if c.isalpha() else " " for c in own)
    return {w for w in cleaned.split() if len(w) >= 3 and w not in STOP}


def _flat_axis(size):
    order = sorted(range(3), key=lambda i: size[i])
    thin, mid = size[order[0]], size[order[1]]
    return order[0] if mid > 0 and thin <= FLAT * mid else None


def stacked(parts):
    """Flat parts with the same job laid over each other: facing the same way, their faces covering at least
    ``STACK_OVERLAP`` of the smaller one, at most ``STACK_GAP_M`` apart front to back, and sharing a word of what they
    are (two clock dials, two signs). Returns ``[(older, newer)]`` by ``order``, each a ``parts`` entry."""
    flats = []
    for entry in parts:
        axis = _flat_axis(entry["size"])
        words = role_words(entry["name"], entry["thing"])
        if axis is not None and words:
            flats.append((entry, axis, words))
    pairs = []
    for i, (a, axis_a, words_a) in enumerate(flats):
        for b, axis_b, words_b in flats[i + 1:]:
            shared = words_a & words_b
            if axis_a != axis_b or len(shared) < min(2, len(words_a), len(words_b)):
                continue  # a window's glass and its frame share only "window": they are not two versions
            if abs(a["centre"][axis_a] - b["centre"][axis_a]) > STACK_GAP_M:
                continue
            area_a = area_b = covered = 1.0
            for k in range(3):
                if k == axis_a:
                    continue
                lo = max(a["centre"][k] - a["size"][k] / 2, b["centre"][k] - b["size"][k] / 2)
                hi = min(a["centre"][k] + a["size"][k] / 2, b["centre"][k] + b["size"][k] / 2)
                covered *= max(0.0, hi - lo)
                area_a *= a["size"][k]
                area_b *= b["size"][k]
            if covered >= STACK_OVERLAP * min(area_a, area_b) > 0:
                older, newer = sorted((a, b), key=lambda e: e.get("order", 0))
                pairs.append((older, newer))
    return pairs


def similar_faces(a, b):
    """True when two stacked flat parts are about the same size across their faces: one can replace the other."""
    axis = _flat_axis(a["size"])
    return all(abs(a["size"][k] - b["size"][k]) <= SAME_SIZE * max(a["size"][k], b["size"][k])
               for k in range(3) if k != axis)


def report(parts):
    """What read_scene lists as ``duplicates``: same-shape copies in one place, and flat parts of two different
    things that do the same job laid over each other (a clock moved onto a tower that already has a dial). Within one
    thing the add-on removes the older of two stacked parts itself (see ``scene/replaced.py``)."""
    found = duplicates(parts)
    for older, newer in stacked(parts):
        if older["thing"] != newer["thing"] and len(found) < DUPLICATES_MAX:
            shared = sorted(role_words(older["name"], older["thing"]) & role_words(newer["name"], newer["thing"]))
            found.append({"thing": newer["thing"], "part": newer["name"], "copy": newer["name"],
                          "copy_of": older["name"], "same_job": " ".join(shared)})
    return found


def measure(objects):
    """The plain numbers ``duplicates`` needs, for the mesh objects among ``objects`` (Blender objects; their
    world-space bounds and vertex counts). ``thing`` is the outermost parent's name."""
    from mathutils import Vector

    parts = []
    for obj in objects:
        if obj.type != "MESH" or obj.data is None or obj.hide_render:
            continue
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        low = [min(c[i] for c in corners) for i in range(3)]
        high = [max(c[i] for c in corners) for i in range(3)]
        root = obj
        while root.parent is not None:
            root = root.parent
        parts.append({"name": obj.name, "thing": root.name, "vertices": len(obj.data.vertices), "order": obj.session_uid,
                      "size": [high[i] - low[i] for i in range(3)],
                      "centre": [(high[i] + low[i]) / 2 for i in range(3)]})
    return parts
