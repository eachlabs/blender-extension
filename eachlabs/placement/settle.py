"""Settling small props: each small loose thing of the chat's comes down onto what is under it. Main thread only.

A short rigid-body run would do the same, but it needs operators with an object context (rigidbody.object_add),
which race the chat's worker thread on Blender 4.2. Rays down from the footprint find the same resting height for
a prop that floats; tipping over is not modelled. Things that sink, and things with nothing under them at all, are
left to the sunk_into and nothing_below checks. A thing whose top touches something above it (a lamp on its rod
from the ceiling, a sign under a beam) hangs, and stays where it is.
"""

from mathutils import Vector

from ..things import registry

SMALL_M = 1.5  # metres: a prop is this long at most on its longest side; bigger things are placed, not settled
DROP_M = 2.0  # most it comes down; a prop higher than this above everything is meant to hang or fly
GAP_M = 0.01  # a gap this small is resting already
HANG_M = 0.05  # a thing whose top is this close under something hangs from it
_GEOMETRY = ("MESH", "CURVE", "SURFACE", "FONT", "META")
_SAMPLES = ((0.5, 0.5), (0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9))  # footprint points, as shares of its box


def _box(tree):
    corners = [o.matrix_world @ Vector(c) for o in tree if o.type in _GEOMETRY for c in o.bound_box]
    if not corners:
        return None
    return (Vector([min(c[i] for c in corners) for i in range(3)]),
            Vector([max(c[i] for c in corners) for i in range(3)]))


def _boxes(scene):
    """``[(object, low, high)]`` of every visible geometry object of the scene, in world space."""
    found = []
    for obj in scene.objects:
        if obj.type in _GEOMETRY and not obj.hide_render:
            box = _box([obj])
            if box is not None:
                found.append((obj, box[0], box[1]))
    return found


def _support(depsgraph, boxes, own, low, high):
    """The highest surface under the footprint, no lower than ``DROP_M`` under it; ``None`` if none.

    Each candidate (another object whose box lies under the footprint) is cast against on its own, from just above
    its top: a ray from inside the prop would pass its own bottom and miss a ground that touches it exactly."""
    best = None
    for fx, fy in _SAMPLES:
        x, y = low.x + (high.x - low.x) * fx, low.y + (high.y - low.y) * fy
        for obj, olow, ohigh in boxes:
            if obj.session_uid in own or not (olow.x <= x <= ohigh.x and olow.y <= y <= ohigh.y):
                continue
            if ohigh.z > low.z + GAP_M or ohigh.z < low.z - DROP_M:
                continue
            inverse = obj.matrix_world.inverted()
            start = inverse @ Vector((x, y, ohigh.z + GAP_M))
            toward = (inverse.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
            hit, where, _normal, _index = obj.ray_cast(start, toward, depsgraph=depsgraph)
            if hit:
                z = (obj.matrix_world @ where).z
                best = z if best is None else max(best, z)
    return best


def _hangs(depsgraph, boxes, own, low, high):
    """True when something not its own is right above the footprint, within ``HANG_M`` of its top."""
    for fx, fy in _SAMPLES:
        x, y = low.x + (high.x - low.x) * fx, low.y + (high.y - low.y) * fy
        for obj, olow, ohigh in boxes:
            if obj.session_uid in own or not (olow.x <= x <= ohigh.x and olow.y <= y <= ohigh.y):
                continue
            if olow.z > high.z + HANG_M or ohigh.z < high.z:
                continue
            inverse = obj.matrix_world.inverted()
            start = inverse @ Vector((x, y, high.z - GAP_M))
            toward = (inverse.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
            hit, where, _normal, _index = obj.ray_cast(start, toward, depsgraph=depsgraph)
            if hit and (obj.matrix_world @ where).z <= high.z + HANG_M:
                return True
    return False


def _units(root):
    """What settles as one piece. A thing's parts always move together, keeping where they stand to each other:
    a small thing settles whole; a wider group with no shape of its own (an empty) settles whole by its lowest
    point when its pieces are parts of it, or child thing by child thing when they are things of their own (two
    fish on a counter, each made of a body, fins and a tail)."""
    box = _box([root] + list(root.children_recursive))
    if box is None:
        return []
    if max(box[1] - box[0]) <= SMALL_M:
        return [root]
    if root.type in _GEOMETRY or not root.children:
        return []
    for child in root.children:
        piece = _box([child] + list(child.children_recursive))
        if piece is not None and max(piece[1] - piece[0]) > SMALL_M:
            return []  # a group of big things is placed, not settled
    if all(registry.is_root(child) for child in root.children):
        return list(root.children)
    return [root]


def settle(build):
    """Bring the chat's small loose props down onto what is under them; ``[{"thing", "dropped_m"}]`` for each that
    moved."""
    scene = build.scene
    for layer in scene.view_layers:
        layer.update()
    depsgraph = scene.view_layers[0].depsgraph
    boxes = _boxes(scene)
    moved = []
    for root in build._objects():
        in_area = root.parent is not None and root.parent.get("zone")
        if (root.parent is not None and not in_area) or root.get("ground") or root.get("zone") \
                or root.get("walkable") is False:
            continue
        for unit in _units(root):
            tree = [unit] + list(unit.children_recursive)
            box = _box(tree)
            if box is None:
                continue
            low, high = box
            own = {o.session_uid for o in tree}
            if _hangs(depsgraph, boxes, own, low, high):
                continue
            surface = _support(depsgraph, boxes, own, low, high)
            if surface is None or low.z - surface <= GAP_M:
                continue
            drop = low.z - surface
            matrix = unit.matrix_world.copy()
            matrix.translation.z -= drop
            unit.matrix_world = matrix
            moved.append({"thing": unit.name, "dropped_m": round(drop, 3)})
            shift = Vector((0.0, 0.0, drop))
            ids = {t.session_uid for t in tree}
            boxes = [(o, ol - shift, oh - shift) if o.session_uid in ids else (o, ol, oh)
                     for o, ol, oh in boxes]  # a prop that came down can carry the next one
    if moved:
        for layer in scene.view_layers:
            layer.update()
    return moved
