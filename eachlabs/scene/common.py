"""Constants and small helpers the scene build and its checks share: geometry kinds, rounding, bounds."""

from mathutils import Vector


GEOMETRY = ("MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME")
FLAT = 0.05  # an object this flat against its footprint is ground, not something to frame
RAY_REACH = 200.0  # metres a camera_view ray looks
GENERATED = "eachlabs_3d"  # object property: the generation job a generated 3D object came from (objects_3d)
WALKABLE = "walkable"  # object property the model sets to False on water and other surfaces nothing stands on


def _r(values, digits=2):
    return [round(float(v), digits) for v in values]


def _cap(items, limit):
    items = list(items)
    if len(items) <= limit:
        return items
    return items[:limit] + ["+%d more" % (len(items) - limit)]


def _update(scene):
    """Bring dimensions and bounding boxes up to date with edits that have not been evaluated yet."""
    for layer in scene.view_layers:
        layer.update()


def is_root(obj):
    """A thing of its own: an object with no parent, or one standing directly in an area's zone."""
    return obj.parent is None or bool(obj.parent.get("zone"))


def is_thing(obj):
    """A thing the checks measure on its own: a root that is not itself an area's zone (zones hold things)."""
    return is_root(obj) and not obj.get("zone")


def walkable(obj):
    """False for an object the model marked ``obj["walkable"] = False`` (water, a hole), or a part of one."""
    while obj is not None:
        if obj.get(WALKABLE) in (False, 0):
            return False
        obj = obj.parent
    return True


def _alive(idblock):
    try:
        idblock.name
    except ReferenceError:
        return False
    return True


def _box(obj):
    """``(low, high)`` of the object's bounding box in world space."""
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return ([min(c[i] for c in corners) for i in range(3)], [max(c[i] for c in corners) for i in range(3)])


def extent(obj):
    """``{"centre", "size"}`` in world space of the geometry of ``obj`` and everything under it, where the thing
    really is: code often builds at world coordinates under an empty at the origin, or with every origin at 0.
    ``None`` when there is no geometry (an empty, a light)."""
    boxes = [_box(o) for o in [obj] + list(obj.children_recursive) if o.type in GEOMETRY]
    if not boxes:
        return None
    low = [min(b[0][i] for b in boxes) for i in range(3)]
    high = [max(b[1][i] for b in boxes) for i in range(3)]
    return {"centre": _r([(a + b) / 2 for a, b in zip(low, high)], 1), "size": _r([b - a for a, b in zip(low, high)], 1)}


def _world_bounds(obj):
    """``[low, high]`` in world space when the geometry is not around the object's origin, else ``None``.
    Code that writes vertices in world coordinates leaves every origin at 0, so the location alone says nothing."""
    low, high = _box(obj)
    centre = [(a + b) / 2 for a, b in zip(low, high)]
    size = max(high[i] - low[i] for i in range(3))
    if (Vector(centre) - obj.matrix_world.translation).length <= max(0.1, 0.05 * size):
        return None
    return [_r(low, 1), _r(high, 1)]
