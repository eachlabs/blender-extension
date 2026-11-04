"""The Blender side of placement: footprints of the scene's things, the ground and the areas, what lies under a
spot, and moving or copying a thing to where the solver put it."""

from mathutils import Matrix, Vector

from ..scene.common import FLAT, GEOMETRY, is_root, walkable
from . import geometry as geo

OBSTACLE_MIN_H = 0.3  # metres: flatter things (paths, rugs, ground) are stood on, not walked around
RAY_FROM = 2000.0
GROUND_MIN_M2 = 100.0
TERRAIN_RISE = 0.15  # a wide part rising less than this share of its width is ground to stand on
SUNK = -10000.0  # where things wait, out of every ray, while the solver picks their spots


def parts(obj):
    return [o for o in [obj] + list(obj.children_recursive) if o.type in GEOMETRY and not o.hide_render]


def world_box(obj):
    """``(low, high)`` in world space of ``obj`` and everything under it, or ``None`` without geometry."""
    lows, highs = [], []
    for part in parts(obj):
        corners = [part.matrix_world @ Vector(c) for c in part.bound_box]
        lows.append([min(c[i] for c in corners) for i in range(3)])
        highs.append([max(c[i] for c in corners) for i in range(3)])
    if not lows:
        return None
    return ([min(v[i] for v in lows) for i in range(3)], [max(v[i] for v in highs) for i in range(3)])


def footprint(obj):
    """``(size, offset, base)`` of a thing in its own turn: width and depth, the footprint's centre from its
    origin, and how far its lowest point lies below the origin. ``None`` without geometry."""
    yaw = obj.matrix_world.to_euler().z
    origin = obj.matrix_world.translation
    undo = Matrix.Rotation(-yaw, 4, "Z") @ Matrix.Translation(-origin)
    xs, ys, zs = [], [], []
    for part in parts(obj):
        for c in part.bound_box:
            p = undo @ (part.matrix_world @ Vector(c))
            xs.append(p.x)
            ys.append(p.y)
            zs.append(p.z)
    if not xs:
        return None
    size = (max(xs) - min(xs), max(ys) - min(ys))
    offset = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
    return size, offset, min(zs)


def ground(scene, mine):
    """The chat's ground as a box: an object marked ``ground``, else its widest flat walkable thing."""
    best = None
    for obj in mine:
        if obj.type not in GEOMETRY or obj.hide_render or not walkable(obj):
            continue
        box = world_box(obj)
        if box is None:
            continue
        low, high = box
        w, d, h = high[0] - low[0], high[1] - low[1], high[2] - low[2]
        if obj.get("ground"):
            return geo.Area("ground", box=(low[0], low[1], high[0], high[1]))
        if w * d >= GROUND_MIN_M2 and h <= FLAT * max(w, d) * 4 and (best is None or w * d > best[0]):
            best = (w * d, (low[0], low[1], high[0], high[1]))
    return geo.Area("ground", box=best[1]) if best else None


def zone_objects(scene):
    return [o for o in scene.objects if o.get("zone")]


def zone_area(obj):
    """The area a zone empty marks, or ``None`` when it has no size."""
    x, y = obj.matrix_world.translation.x, obj.matrix_world.translation.y
    ring = obj.get("ring")
    if ring is not None:
        try:
            return geo.Area(_zone_name(obj), centre=(x, y), inner=float(ring[0]), outer=float(ring[1]))
        except (TypeError, ValueError, IndexError, KeyError):
            return None
    size = obj.get("size")
    try:
        w, d = float(size[0]), float(size[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return geo.Area(_zone_name(obj), box=geo.box_around(x, y, w / 2, d / 2))


def _zone_name(obj):
    return obj.name[5:] if obj.name.startswith("Zone ") else obj.name


def things(scene):
    """``{name: world box}`` of every thing of its own in the scene (zones excluded), with its object."""
    out = {}
    for obj in scene.objects:
        if not is_root(obj) or obj.get("zone"):
            continue
        box = world_box(obj)
        if box is not None:
            out[obj.name] = (obj, box)
    return out


def top_of(obj):
    """The thing an object belongs to: its top parent, stopping under an area's zone."""
    while obj.parent is not None and not obj.parent.get("zone"):
        obj = obj.parent
    return obj


def obstacles(scene, skip=()):
    """``[(thing name, 2D box)]`` for every part that things must keep clear of, one box per part, so a group
    whose parts spread over the ground does not block all of it. Parts of things named in ``skip`` are left out."""
    out = []
    for part in scene.objects:
        if part.type not in GEOMETRY or part.hide_render:
            continue
        top = top_of(part)
        if top.name in skip or top.get("zone"):
            continue
        corners = [part.matrix_world @ Vector(c) for c in part.bound_box]
        low = [min(c[i] for c in corners) for i in range(3)]
        high = [max(c[i] for c in corners) for i in range(3)]
        if is_obstacle(part, (low, high)):
            out.append((top.name, (low[0], low[1], high[0], high[1])))
    return out


def is_obstacle(obj, box):
    """True for a part things walk around; false for what they stand on: flat things and wide, gently rising
    ground (terrain), unless it is marked not walkable (water)."""
    low, high = box
    if not walkable(obj):
        return True
    w, d, h = high[0] - low[0], high[1] - low[1], high[2] - low[2]
    if obj.get("ground") or (w * d >= GROUND_MIN_M2 and h <= TERRAIN_RISE * max(w, d)):
        return False
    return h >= OBSTACLE_MIN_H


def flat(box):
    low, high = box
    return (low[0], low[1], high[0], high[1])


class Ground:
    """What lies under a spot, by a ray straight down."""

    def __init__(self, scene, depsgraph):
        self.scene, self.depsgraph = scene, depsgraph

    def hit(self, x, y):
        """``(z, top object)`` of the first surface under ``(x, y)``, or ``None``."""
        found, loc, _n, _i, obj, _m = self.scene.ray_cast(self.depsgraph, Vector((x, y, RAY_FROM)),
                                                          Vector((0, 0, -1)), distance=RAY_FROM * 2)
        if not found or loc.z < SUNK / 2:
            return None
        top = obj
        while top.parent is not None and not top.parent.get("zone"):
            top = top.parent
        return loc.z, obj, top

    def check(self, x, y, on):
        """True when a thing may stand at ``(x, y)`` on ``on`` (``"ground"`` or a thing's name), else why not."""
        hit = self.hit(x, y)
        if hit is None:
            return "nothing under the spot"
        _z, obj, top = hit
        if on in (None, "ground"):
            return True if walkable(obj) else "it would stand on %s, which nothing stands on" % top.name
        return True if top.name == on else "%s is not under the spot" % on


def move(obj, x, y, z, turn):
    """Turn ``obj`` by ``turn`` about its origin and put its origin at ``(x, y, z)``, keeping everything under it."""
    world = obj.matrix_world.copy()
    origin = world.translation.copy()
    obj.matrix_world = Matrix.Translation((x, y, z)) @ Matrix.Rotation(turn, 4, "Z") @ Matrix.Translation(-origin) @ world


def sink(obj):
    obj.matrix_world = Matrix.Translation((0, 0, SUNK - obj.matrix_world.translation.z)) @ obj.matrix_world


def rest_height(ground_probe, box, base):
    """The origin's height that rests a thing's lowest point on the highest surface under its footprint."""
    cx, cy = geo.box_centre(box)
    inset_x, inset_y = (box[2] - box[0]) * 0.3, (box[3] - box[1]) * 0.3
    heights = []
    for x, y in ((cx, cy), (cx - inset_x, cy - inset_y), (cx + inset_x, cy - inset_y), (cx - inset_x, cy + inset_y),
                 (cx + inset_x, cy + inset_y)):
        hit = ground_probe.hit(x, y)
        if hit is not None:
            heights.append(hit[0])
    return (max(heights) if heights else 0.0) - base
