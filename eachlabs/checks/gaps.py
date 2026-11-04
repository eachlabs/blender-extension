"""Gaps between an object's parts, and small parts that stand off the surface behind them."""

from mathutils import Vector

from ..scene.common import _cap, _update


STANDOFF_SIZE = 2.0  # a part counts as attached to a surface of a part at least this many times its size
GAP_TOUCH = 0.01  # metres between two parts' surfaces that still count as touching
GAP_REPORT = 0.3  # metres: a part farther than this from the rest is apart on purpose or listed by loose_parts
GAP_PARTS_MAX = 400  # parts an object may have for its gaps to be measured
GAP_SAMPLES = 64  # vertices of a part measured against its neighbours
GAPS_MAX = 8


def _standoffs(parts):
    """Small parts that stand off a larger part of the same object: along the part's thinnest side, the larger part
    lies just behind it and nothing in front (a window frame 10 cm in front of its wall). ``parts`` as in
    ``part_gaps``. Parts that stand off one surface by about the same gap are one entry."""
    found = {}
    for i, a in enumerate(parts):
        dims = a["high"] - a["low"]
        axis = min(range(3), key=lambda k: dims[k])
        size = max(dims)
        centre = (a["low"] + a["high"]) / 2
        half = dims[axis] / 2
        reach = half + GAP_REPORT
        hits = []
        for sign in (1.0, -1.0):
            direction = Vector((0.0, 0.0, 0.0))
            direction[axis] = sign
            best = None
            for j, b in enumerate(parts):
                if j == i or any(not b["low"][k] <= centre[k] <= b["high"][k] for k in range(3) if k != axis):
                    continue
                near = (b["low"][axis] - centre[axis]) if sign > 0 else (centre[axis] - b["high"][axis])
                if near > reach:
                    continue
                location, _normal, _index, distance = b["bvh"].ray_cast(centre, direction, reach)
                if location is not None and (best is None or distance < best[0]):
                    best = (distance, j)
            hits.append(best)
        for near, far in ((hits[0], hits[1]), (hits[1], hits[0])):
            if near is None or far is not None:
                continue
            gap = near[0] - half
            surface = parts[near[1]]
            if GAP_TOUCH < gap < GAP_REPORT and max(surface["high"] - surface["low"]) >= STANDOFF_SIZE * size:
                key = (surface["name"], round(gap / 0.02))
                entry = found.setdefault(key, {"parts": [], "gap_m": round(gap, 3), "stands_off": surface["name"]})
                entry["parts"].append(a["name"])
    out = list(found.values())
    for entry in out:
        entry["parts"] = _cap(entry["parts"], 4)
    return out


class PartGaps:
    def part_gaps(self, name):
        """Parts of the object ``name`` that almost touch the rest of it but do not: ``[{"parts", "gap_m"}]``,
        measured on the surfaces (with modifiers), not the boxes. Pieces farther than ``GAP_REPORT`` are left to
        loose_parts."""
        from mathutils.bvhtree import BVHTree

        scene = self.scene
        root = scene.objects.get(name)
        if root is None or not self._mine(root):
            return []
        tree = [o for o in [root] + list(root.children_recursive)
                if o.type in ("MESH", "CURVE", "SURFACE", "FONT", "META") and not o.hide_render]
        if len(tree) < 2 or len(tree) > GAP_PARTS_MAX:
            return []
        _update(scene)  # the close-up removes its camera just before this: read a current evaluated scene
        depsgraph = self._depsgraph(scene)
        parts = []
        for obj in tree:
            ev = obj.evaluated_get(depsgraph)
            try:
                mesh = ev.to_mesh()
            except RuntimeError:
                continue
            try:
                if mesh is None or not mesh.polygons:
                    continue
                world = ev.matrix_world
                verts = [world @ v.co for v in mesh.vertices]
                polys = [tuple(p.vertices) for p in mesh.polygons]
            finally:
                ev.to_mesh_clear()
            step = max(1, len(verts) // GAP_SAMPLES)
            low = Vector([min(v[i] for v in verts) for i in range(3)])
            high = Vector([max(v[i] for v in verts) for i in range(3)])
            parts.append({"name": obj.name, "bvh": BVHTree.FromPolygons(verts, polys), "samples": verts[::step],
                          "low": low, "high": high})
        count = len(parts)
        if count < 2:
            return []
        piece = list(range(count))

        def find(i):
            while piece[i] != i:
                piece[i] = piece[piece[i]]
                i = piece[i]
            return i

        nearest = {}  # (i, j) -> surface distance, for pairs whose boxes are within GAP_REPORT

        def distance(a, b):
            best = None
            for small, big in ((a, b), (b, a)):
                for v in small["samples"]:
                    found = big["bvh"].find_nearest(v, GAP_REPORT)
                    if found[0] is not None and (best is None or found[3] < best):
                        best = found[3]
                        if best <= GAP_TOUCH:
                            return best
            return best

        for i in range(count):
            a = parts[i]
            for j in range(i + 1, count):
                b = parts[j]
                if any(a["low"][k] - GAP_REPORT > b["high"][k] or b["low"][k] - GAP_REPORT > a["high"][k]
                       for k in range(3)):
                    continue
                if a["bvh"].overlap(b["bvh"]):
                    piece[find(i)] = find(j)
                    continue
                d = distance(a, b)
                if d is None:
                    continue
                if d <= GAP_TOUCH:
                    piece[find(i)] = find(j)
                else:
                    nearest[(i, j)] = d
        groups = {}
        for i in range(count):
            groups.setdefault(find(i), []).append(i)
        out = []
        if len(groups) >= 2:
            main = max(groups.values(), key=len)
            for members in groups.values():
                if members is main:
                    continue
                inside = set(members)
                gaps = [d for (i, j), d in nearest.items() if (i in inside) != (j in inside)]
                if not gaps:
                    continue  # farther than GAP_REPORT from everything: loose_parts lists it
                names = [parts[i]["name"] for i in members]
                out.append({"parts": _cap(names, 4), "gap_m": round(min(gaps), 3)})
        # The widest gaps first: they show in a render, and the list is cut at GAPS_MAX.
        return sorted(out + _standoffs(parts), key=lambda g: -g["gap_m"])[:GAPS_MAX]
