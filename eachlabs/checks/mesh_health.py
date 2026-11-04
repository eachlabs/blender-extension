"""Holes and flipped faces in the chat's solid meshes, and closing small flat open ends."""

from mathutils import Vector

from ..scene.common import _cap, _r, _update


# Mesh health: open edges (holes, uncapped tubes) and faces turned the wrong way, measured on the meshes with their
# modifiers. A flat sheet (a plane, a sign) is meant to be open and is not checked: its thinnest side is at most
# SHEET_SHARE of its longest, or under SHEET_THICK metres. An opening smaller than HOLE_MIN metres does not show.
HEALTH_MAX = 400  # newest meshes of a run checked per read_scene
HEALTH_VERTS_MAX = 60000  # a mesh with more vertices is not checked (the check stays fast)
SHEET_SHARE = 0.02
SHEET_THICK = 0.01
HOLE_MIN = 0.04
HOLES_MAX = 12  # entries in open_holes and flipped_normals


class MeshHealth:
    def mesh_health(self, objects, depsgraph=None):
        """``(open_holes, flipped_normals)`` for ``objects``: meshes with open edges, as ``{"name", "edges",
        "loops", "where"}`` (``where``: the centre of the largest opening), and meshes with faces turned against
        their neighbours, as ``{"name", "faces"}``. Each mesh shared by copies is measured once."""
        import bmesh

        if depsgraph is None:  # read_scene passes its own, already brought up to date
            _update(self.scene)
            depsgraph = self._depsgraph(self.scene)
        holes, flipped, seen = [], [], set()
        for obj in objects:
            if obj.type not in ("MESH", "CURVE") or obj.hide_render or obj.data is None:
                continue
            key = (obj.data.session_uid, tuple((m.type, m.show_render) for m in obj.modifiers))
            if key in seen:
                continue
            seen.add(key)
            ev = obj.evaluated_get(depsgraph)
            try:
                mesh = ev.to_mesh()
            except RuntimeError:
                continue
            bm = None
            try:
                if mesh is None or not mesh.polygons or len(mesh.vertices) > HEALTH_VERTS_MAX:
                    continue
                bm = bmesh.new()
                bm.from_mesh(mesh)
            finally:
                ev.to_mesh_clear()
            try:
                world = ev.matrix_world
                points = [world @ v.co for v in bm.verts]
                span = [max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)]
                if min(span) <= max(SHEET_THICK, SHEET_SHARE * max(span)):
                    continue  # a flat sheet is open on purpose
                loops = []
                todo = {e.index: e for e in bm.edges if e.is_boundary}
                while todo:
                    _index, edge = todo.popitem()
                    stack, verts, count = [edge], set(), 0
                    while stack:
                        cur = stack.pop()
                        count += 1
                        for v in cur.verts:
                            verts.add(v.index)
                            for other in v.link_edges:
                                if other.index in todo:
                                    stack.append(todo.pop(other.index))
                    co = [points[i] for i in verts]
                    size = max(max(c[i] for c in co) - min(c[i] for c in co) for i in range(3))
                    if size >= HOLE_MIN:
                        centre = sum(co, Vector()) / len(co)
                        loops.append((size, count, centre))
                if loops:
                    biggest = max(loops, key=lambda item: item[0])
                    holes.append({"name": obj.name, "edges": sum(n for _s, n, _c in loops), "loops": len(loops),
                                  "where": _r(biggest[2])})
                turned = sum(1 for e in bm.edges if e.is_manifold
                             and e.link_loops[0].vert == e.link_loops[1].vert)
                if turned:
                    flipped.append({"name": obj.name, "faces": turned})
            finally:
                bm.free()
        return _cap(holes, HOLES_MAX), _cap(flipped, HOLES_MAX)
