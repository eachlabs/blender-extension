"""Thin parts that pass right through another part of the same thing and stick out of it into the air: a pole poking
out through a roof, a beam through a wall. A part that only ends at a surface (a rafter under its roof), two thin
members that cross (a window's bars, a fence's rails), a part whose ends both meet other parts (a canopy pole through
its counter, up to the canopy) and a post reaching down to the ground do not count."""

PIERCE_MIN_LEN = 1.5  # metres: shorter parts are not poles or beams
PIERCE_THIN = 6.0  # a part this many times longer than it is thick is thin
PIERCE_END = 0.15  # share of a part's length at each end where meeting a surface is just ending at it
PIERCE_OUT = 0.3  # metres a part must reach past the surface on both sides to count
PIERCE_TOUCH = 0.1  # metres: an end this close to another part's box meets that part
PIERCE_PARTS_MAX = 300  # parts a thing may have for this to be measured
PIERCE_SAMPLES = 200
PIERCES_MAX = 8


def _axis(points):
    """``(a, b, thickness)``: the two ends of a part's longest line and its thickness across it."""
    step = max(1, len(points) // PIERCE_SAMPLES)
    sample = points[::step]
    centre = sum(sample, sample[0] * 0) / len(sample)
    a = max(sample, key=lambda p: (p - centre).length)
    b = max(sample, key=lambda p: (p - a).length)
    line = b - a
    if line.length == 0:
        return a, b, 0.0
    unit = line.normalized()
    thick = max(((p - a) - unit * (p - a).dot(unit)).length for p in sample)
    return a, b, thick * 2


def _thin(axis):
    a, b, thick = axis
    length = (b - a).length
    return length >= PIERCE_MIN_LEN and thick * PIERCE_THIN <= length


def _box(points):
    return ([min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)])


def _free_end(point, boxes):
    """True when ``point`` (an end of a part) touches none of ``boxes`` and lies above the lowest of them: it sticks
    out into the air. An end below them reaches down to the ground, like a post or a leg."""
    if not boxes or point[2] < min(low[2] for low, _high in boxes):
        return False
    return not any(all(low[i] - PIERCE_TOUCH <= point[i] <= high[i] + PIERCE_TOUCH for i in range(3))
                   for low, high in boxes)


def pierces(roots, meshes):
    """``[{"thing", "part", "through", "where"}]`` for the given roots; ``meshes`` is a ``solids.Meshes``."""
    out = []
    for root in roots:
        parts = [o for o in [root] + list(root.children_recursive) if o.type == "MESH" and not o.hide_render]
        if len(parts) < 2 or len(parts) > PIERCE_PARTS_MAX:
            continue
        data = {p.session_uid: meshes.get(p) for p in parts}
        axes = {uid: _axis(got[0]) for uid, got in data.items() if got is not None and len(got[0]) >= 2}
        thin = {uid for uid, axis in axes.items() if _thin(axis)}
        boxes = {uid: _box(got[0]) for uid, got in data.items() if got is not None and uid not in thin}
        for part in parts:
            uid = part.session_uid
            if uid not in thin:
                continue
            a, b, _thick = axes[uid]
            if not (_free_end(a, list(boxes.values())) or _free_end(b, list(boxes.values()))):
                continue  # both ends meet other parts, or the part reaches down to the ground
            hit = _through(part, parts, data, thin, a, b, (b - a).length)
            if hit is not None:
                other, where = hit
                out.append({"thing": root.name, "part": part.name, "through": other,
                            "where": [round(v, 1) for v in where]})
                if len(out) >= PIERCES_MAX:
                    return out
    return out


def _through(part, parts, data, thin, a, b, length):
    direction = (b - a).normalized()
    for other in parts:
        if other is part or other.session_uid in thin:
            continue  # two thin members crossing are a joint (a window's bars), not a part poking through
        got = data[other.session_uid]
        if got is None:
            continue
        tree = got[2]
        start, left = a.copy(), length
        while left > 0:
            loc, _normal, _index, dist = tree.ray_cast(start, direction, left)
            if loc is None:
                break
            t = (loc - a).length / length
            if PIERCE_END <= t <= 1 - PIERCE_END and min(t, 1 - t) * length >= PIERCE_OUT:
                return other.name, loc
            start = loc + direction * 1e-3
            left -= dist + 1e-3
    return None
