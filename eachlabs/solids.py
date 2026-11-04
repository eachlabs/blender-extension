"""Geometry checks on the chat's solid meshes, measured from their real surfaces, never from names or kinds.

- ``crossings``: two separate things whose surfaces pass through each other (a fence through a house).
- ``hidden_parts``: a small part that lies mostly inside a bigger part of the same thing (a clock sunk into a roof).
- ``close_small_ends``: fills small, flat open ends of solid meshes (a tube end, a post top), which the model
  often leaves; larger or irregular openings stay reported to it as ``open_holes``.

Main thread only; every evaluated mesh is freed before the function returns.
"""

import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

PARTS_MAX = 900  # newest mesh parts measured per call (the check stays fast in a big scene)
VERTS_MAX = 60000  # a mesh with more vertices is not measured
PAIRS_MAX = 600  # pairs of parts whose surfaces are tested against each other
CROSS_Z_MIN = 0.1  # metres two parts must share in height to count; a house on the ground shares none
CROSS_MAX = 8
CROSS_LEN = 0.75  # metres the two must overlap along the ground; walls meeting at a corner share less
CROSS_SIZE = 0.8  # metres: smaller parts (stones, tufts, twigs) crossing each other are not listed
GROUND_RATIO = 0.1  # a part this low for its width is ground or terrain
HIDDEN_SIZE = 3.0  # the bigger part is at least this many times the small part's size
HIDDEN_SHARE = 0.9  # share of the small part's points inside the bigger part for it to count as hidden
HIDDEN_SAMPLES = 48  # points of a small part tested
HIDDEN_MAX = 8
FLAT_END = 0.08  # an open end counts as flat when its points lie within this share of its size from its plane
END_SHARE = 0.35  # an open end is small when it is at most this share of the object's size
ENDS_MAX = 400  # open ends filled per call


def _r(values, digits=2):
    return [round(float(v), digits) for v in values]


class Meshes:
    """World-space vertices, faces and surface trees of evaluated meshes, built once per object."""

    def __init__(self, depsgraph):
        self.depsgraph = depsgraph
        self._data = {}

    def get(self, obj):
        """``(points, faces, tree)`` in world space, or ``None`` for an object with no usable mesh."""
        key = obj.session_uid
        if key in self._data:
            return self._data[key]
        found = None
        if obj.type == "MESH" and not obj.hide_render and obj.data is not None:
            ev = obj.evaluated_get(self.depsgraph)
            try:
                mesh = ev.to_mesh()
            except RuntimeError:
                mesh = None
            try:
                if mesh is not None and mesh.polygons and len(mesh.vertices) <= VERTS_MAX:
                    world = ev.matrix_world
                    points = [world @ v.co for v in mesh.vertices]
                    faces = [tuple(p.vertices) for p in mesh.polygons]
                    found = (points, faces, BVHTree.FromPolygons(points, faces, all_triangles=False))
            finally:
                if mesh is not None:
                    ev.to_mesh_clear()
        self._data[key] = found
        return found


def _box(points):
    return ([min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)])


def _bbox(obj, depsgraph):
    """World-space box of the evaluated object, from its bounding box: cheap, no mesh is read."""
    ev = obj.evaluated_get(depsgraph)
    return _box([ev.matrix_world @ Vector(c) for c in ev.bound_box])


def _same_shape_key(small, big):
    """Copies of one thing (shared meshes, same offset between the two parts) are measured once."""
    rel = small.matrix_world.inverted() @ big.matrix_world
    return (small.data.session_uid, big.data.session_uid, tuple(round(v, 3) for row in rel for v in row))


def _share(a, b):
    """How far two boxes overlap along each axis (negative when apart)."""
    return [min(a[1][i], b[1][i]) - max(a[0][i], b[0][i]) for i in range(3)]


def _top(obj, by_uid):
    """The thing ``obj`` belongs to: its top parent, stopping under an area's zone, which holds many things."""
    while obj.parent is not None and obj.parent.session_uid in by_uid:
        if obj.parent.get("zone") and not obj.name.startswith(obj.parent.name):
            break  # a thing of the area; pieces named after the zone ("Zone Mountain_Rock") are the area's own
        obj = obj.parent
    return obj


def _ground_like(box):
    """Wide and low for its size: ground or terrain, which things stand on and sink into on purpose."""
    w, d, h = (box[1][i] - box[0][i] for i in range(3))
    return h <= GROUND_RATIO * min(w, d)  # wide both ways: a long, thin wall is no ground


def crossings(objects, depsgraph, new=None, label=None):
    """Separate things of ``objects`` whose surfaces pass through each other: ``[{"thing", "crosses", "where"}]``.
    A thing is a root object with everything under it. ``new``: session_uids made in this run; only pairs with
    at least one new part are listed. ``label(obj)``: how a root is named in the list."""
    by_uid = {o.session_uid: o for o in objects}
    # A root named after another one ("Forest cottage 4 window frames" after "Forest cottage 4") is a part of it
    # built on its own: the two are one thing.
    names = {o.name: o for o in objects}

    def owner(root):
        name = root.name
        for cut in range(len(name) - 1, 0, -1):
            if name[cut] in " _" and name[:cut] in names and names[name[:cut]] is not root:
                return names[name[:cut]]
        return root

    meshes = Meshes(depsgraph)
    parts = [o for o in objects if o.type == "MESH" and not o.hide_render][-PARTS_MAX:]
    boxes = []
    for obj in parts:
        if obj.data is None or not getattr(obj.data, "polygons", None):
            continue
        box = _bbox(obj, depsgraph)
        if box[1][2] - box[0][2] < CROSS_Z_MIN or _ground_like(box):
            continue  # ground, terrain, a road, a rug: things stand on it and into it, they do not cross it
        if max(box[1][i] - box[0][i] for i in range(3)) < CROSS_SIZE:
            continue
        boxes.append((obj, _top(owner(_top(obj, by_uid)), by_uid), box))
    shapes = {}

    def shape(root):
        """The meshes a thing is made of: two things with the same are copies of one."""
        if root.session_uid not in shapes:
            shapes[root.session_uid] = frozenset(o.data.session_uid for o in [root] + list(root.children_recursive)
                                                 if o.type == "MESH" and o.data is not None)
        return shapes[root.session_uid]

    found, seen, tested = [], set(), 0
    boxes.sort(key=lambda item: item[2][0][0])
    for i, (a, ra, abox) in enumerate(boxes):
        for b, rb, bbox in boxes[i + 1:]:
            if bbox[0][0] > abox[1][0]:
                break  # sorted by their low x: nothing further along overlaps
            if ra is rb or shape(ra) == shape(rb):
                continue  # copies of one thing (the trees of a forest) may touch each other
            pair = tuple(sorted((ra.session_uid, rb.session_uid)))
            if pair in seen or (new is not None and a.session_uid not in new and b.session_uid not in new):
                continue
            share = _share(abox, bbox)
            if min(share) <= 0 or share[2] < CROSS_Z_MIN or max(share[0], share[1]) < CROSS_LEN:
                continue
            tested += 1
            if tested > PAIRS_MAX:
                break
            da, db = meshes.get(a), meshes.get(b)
            if da is not None and db is not None and da[2].overlap(db[2]):
                seen.add(pair)
                centre = [(max(abox[0][k], bbox[0][k]) + min(abox[1][k], bbox[1][k])) / 2 for k in range(3)]
                name = label or (lambda o: o.name)
                found.append({"thing": name(ra), "crosses": name(rb), "where": _r(centre, 1)})
                if len(found) >= CROSS_MAX:
                    return found
        if tested > PAIRS_MAX:
            break
    return found


def _inside(tree, point):
    """True when ``point`` lies inside the closed surface ``tree``: the nearest face looks away from it."""
    hit = tree.find_nearest(point)
    if hit[0] is None:
        return False
    location, normal = hit[0], hit[1]
    return (location - point).dot(normal) > 0


def _closed(faces):
    edges = {}
    for face in faces:
        for k in range(len(face)):
            edge = tuple(sorted((face[k], face[(k + 1) % len(face)])))
            edges[edge] = edges.get(edge, 0) + 1
    return bool(edges) and all(count == 2 for count in edges.values())


def hidden_parts(objects, depsgraph, new=None):
    """Small parts that lie mostly inside a bigger, closed part of the same thing: ``[{"part", "inside",
    "share"}]``. A part set into a surface with its front showing (a window in its opening) has most of its points
    outside and is not listed. ``new``: session_uids made in this run; only new small parts are listed."""
    by_uid = {o.session_uid: o for o in objects}
    meshes = Meshes(depsgraph)
    groups = {}
    for obj in [o for o in objects if o.type == "MESH" and not o.hide_render][-PARTS_MAX:]:
        top = _top(obj, by_uid)
        if top is not obj or obj.children:
            groups.setdefault(top.session_uid, []).append(obj)
    found, measured = [], {}
    for members in groups.values():
        sized = []
        for obj in members:
            if obj.data is not None and getattr(obj.data, "polygons", None):
                box = _bbox(obj, depsgraph)
                sized.append((max(box[1][i] - box[0][i] for i in range(3)), obj, box))
        for size, small, box in sized:
            if new is not None and small.session_uid not in new:
                continue
            for big_size, big, big_box in sized:
                if big is small or big_size < HIDDEN_SIZE * size or min(_share(box, big_box)) <= 0:
                    continue
                key = _same_shape_key(small, big)
                if key not in measured:
                    data, big_data = meshes.get(small), meshes.get(big)
                    if data is None or big_data is None or not _closed(big_data[1]):
                        measured[key] = 0.0  # the inside of an open surface is not defined
                    else:
                        points = data[0]
                        sample = points[::max(1, len(points) // HIDDEN_SAMPLES)][:HIDDEN_SAMPLES]
                        measured[key] = sum(1 for p in sample if _inside(big_data[2], p)) / len(sample)
                if measured[key] >= HIDDEN_SHARE:
                    found.append({"part": small.name, "inside": big.name, "share": round(measured[key], 2)})
                    break
            if len(found) >= HIDDEN_MAX:
                return found
    return found


def close_small_ends(objects):
    """Fill the small, flat open ends of solid meshes (``objects``' own mesh data): returns the names of the
    objects changed. Sheets (open along their whole outline) and large or bent openings are left alone."""
    changed, done, filled = [], set(), 0
    for obj in objects:
        if obj.type != "MESH" or obj.data is None or obj.data.session_uid in done or obj.library is not None:
            continue
        done.add(obj.data.session_uid)
        mesh = obj.data
        if not mesh.polygons or len(mesh.vertices) > VERTS_MAX:
            continue
        if any(m.type == "SOLIDIFY" for m in obj.modifiers):
            continue  # a shell given thickness is open on purpose (a lamp shade, an awning)
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            co = [v.co for v in bm.verts]
            span = [max(c[i] for c in co) - min(c[i] for c in co) for i in range(3)]
            size = max(span)
            if size <= 0 or min(span) <= 0.02 * size:
                continue  # a flat sheet is open on purpose
            boundary = [e for e in bm.edges if e.is_boundary]
            if not boundary:
                continue
            loops, todo = [], {e.index: e for e in boundary}
            while todo:
                _i, edge = todo.popitem()
                stack, edges = [edge], [edge]
                while stack:
                    cur = stack.pop()
                    for v in cur.verts:
                        for other in v.link_edges:
                            if other.index in todo:
                                nxt = todo.pop(other.index)
                                stack.append(nxt)
                                edges.append(nxt)
                loops.append(edges)
            to_fill = []
            for edges in loops:
                verts = list({v for e in edges for v in e.verts})
                if len(verts) < 3 or len(edges) != len(verts):
                    continue  # not a simple ring
                pts = [v.co for v in verts]
                ring = max(max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3))
                if ring > END_SHARE * size or ring <= 0:
                    continue
                centre = sum(pts, Vector()) / len(pts)
                normal = Vector()
                for k in range(len(pts)):  # Newell's normal of the ring
                    normal += (pts[k] - centre).cross(pts[(k + 1) % len(pts)] - centre)
                if normal.length == 0:
                    continue
                normal.normalize()
                if max(abs((p - centre).dot(normal)) for p in pts) > FLAT_END * ring:
                    continue  # a bent opening: the model decides
                # An end lies at the far side of the object: nothing of it is beyond the opening, and nothing beside
                # it in the same plane. A window cut through a wall has the wall around it in that plane.
                eps = 0.01 * size
                radius = max((p - centre).length for p in pts)
                side = [(c - centre).dot(normal) for c in co]
                if min(side) < -eps and max(side) > eps:
                    continue
                if any(abs(s) <= eps and (c - centre).length > 1.5 * radius for s, c in zip(side, co)):
                    continue
                to_fill.append(edges)
                if filled + len(to_fill) >= ENDS_MAX:
                    break
            if not to_fill:
                continue
            for edges in to_fill:
                bmesh.ops.holes_fill(bm, edges=edges, sides=0)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(mesh)
            mesh.update()
            filled += len(to_fill)
            changed.append(obj.name)
        finally:
            bm.free()
        if filled >= ENDS_MAX:
            break
    return changed
