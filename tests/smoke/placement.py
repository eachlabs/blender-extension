"""Placing, settling and resting objects in Blender."""

import bpy
import mathutils

from eachlabs import chat_loop
from tests.smoke.common import BOX_CODE, _step, check


FOOTING_CODE = BOX_CODE + '''
box("Ground", (40, 20, 0.1), (20, 10, -0.1))
lake = box("Lake", (40, 30, 0.1), (20, 35, -0.3))
lake["walkable"] = False
box("Dock", (4, 20, 0.3), (20, 30, 1.2))
box("Campfire", (1, 1, 0.5), (20, 30, -0.2))
box("Camp chair", (0.6, 0.6, 0.9), (10, 5, 0))
'''

PARTS_CODE = BOX_CODE + '''
def part(root, name, size, at):
    obj = box(name, size, at)
    obj.parent = root
    obj.matrix_parent_inverse = root.matrix_basis.inverted()
    return obj
chair = bpy.data.objects.new("Chair", None)
scene.collection.objects.link(chair)
part(chair, "Chair_Seat", (1, 1, 0.2), (0, 0, 0.4))
part(chair, "Chair_Back", (1, 0.1, 1), (0, 0.45, 0.6))
part(chair, "Chair_Leg", (0.1, 0.1, 0.4), (0.4, -0.4, 0))
part(chair, "Chair_Wing", (0.1, 0.5, 0.6), (0.59, 0.2, 0.7))
for n, x in ((0, 0), (1, 10), (2, 20), (3, 30)):
    root = bpy.data.objects.new("Pine_%03d" % n, None)
    scene.collection.objects.link(root)
    big = 5 if n == 3 else 1
    part(root, "Pine_%03d_Trunk" % n, (0.4 * big, 0.4 * big, 3 * big), (x, 50, 0))
    if n == 0:
        for k in range(4):
            part(root, "Pine_000_Tier_%d" % k, (2 - 0.4 * k, 2 - 0.4 * k, 0.8), (x, 50, 1 + 0.6 * k))
'''


def test_fix_round():
    """Water and footing, the shadow budget, gaps between parts, the subject during a camera move, copies rebuilt
    from a detailed object, and what a change may detail."""
    import json

    from eachlabs import chat_run, scene_build

    scene = bpy.data.scenes.new("eachlabs_fix_round")
    build = scene_build.SceneBuild(scene, "fix-round-run")
    try:
        check("fix: the lake scene is built", _step(build, FOOTING_CODE).get("ok"))
        seen = build.read_scene()
        free = seen.get("free_space") or {}
        # The dock is ground too (people stand on it), but it lies over the lake, so no free area reaches past y 20.
        check("fix: free space leaves the water out",
              free.get("areas") and all(a["centre"][1] + a["size"][1] / 2 < 20.01 for a in free["areas"]),
              json.dumps(free))
        on_water = {e["thing"]: e["on"] for e in seen.get("on_not_walkable") or []}
        under = {e["thing"]: e["under"] for e in seen.get("under") or []}
        check("fix: read_scene says the campfire stands on the lake and under the dock",
              on_water.get("Campfire") == "Lake" and under.get("Campfire") == "Dock", json.dumps(seen)[:900])
        check("fix: the chair on the ground is not listed",
              "Camp chair" not in on_water and "Camp chair" not in under
              and "Camp chair" not in (seen.get("nothing_below") or []), json.dumps(seen)[:900])
        build.since = build.mark()
        check("fix: only what a run made is checked for footing", "on_not_walkable" not in build.read_scene())
        resting = ("def b(name, size, where):\n"
                   "    m = bpy.data.meshes.new(name)\n"
                   "    bm = bmesh.new()\n"
                   "    bmesh.ops.create_cube(bm, size=1.0)\n"
                   "    bmesh.ops.scale(bm, vec=size, verts=bm.verts)\n"
                   "    bm.to_mesh(m)\n"
                   "    bm.free()\n"
                   "    o = bpy.data.objects.new(name, m)\n"
                   "    scene.collection.objects.link(o)\n"
                   "    o.location = where\n"
                   "b('Reading table', (1.0, 1.0, 0.75), (40, 0, 0.375))\n"
                   "b('Open book', (0.3, 0.2, 0.04), (40, 0, 0.77))\n"
                   "b('Writing desk', (1.0, 0.6, 0.75), (44, 0, 0.375))\n"
                   "b('Wall shelf', (1.0, 0.3, 0.05), (44, 0, 1.6))\n")
        check("fix: the resting scene is built", _step(build, resting).get("ok"))
        under = {e["thing"]: e["under"] for e in build.read_scene().get("under") or []}
        check("fix: a book lying on a table does not put the table under it; a shelf over a desk still does",
              "Reading table" not in under and under.get("Writing desk") == "Wall shelf", str(under))

        lights = ("for i in range(15):\n"
                  "    data = bpy.data.lights.new('Bulb %d' % i, 'POINT')\n"
                  "    data.energy = 10 + i\n"
                  "    obj = bpy.data.objects.new('Bulb %d' % i, data)\n"
                  "    scene.collection.objects.link(obj)\n")
        _step(build, lights)
        noted = build.read_scene()
        check("fix: read_scene names the shadow budget", noted.get("shadow_lights") == 15
              and "EEVEE fits about 12" in noted.get("shadow_note", ""), json.dumps(noted.get("shadow_note")))
        trimmed = build.limit_shadows()
        check("fix: shadow-casting lights raise EEVEE's shadow pool to 1024 MB",
              not hasattr(scene.eevee, "shadow_pool_size") or scene.eevee.shadow_pool_size == "1024",
              str(getattr(scene.eevee, "shadow_pool_size", None)))
        check("fix: the weakest lights past the budget lose their shadow",
              sorted(trimmed) == ["Bulb 0", "Bulb 1", "Bulb 2"] and not bpy.data.objects["Bulb 0"].data.use_shadow
              and bpy.data.objects["Bulb 14"].data.use_shadow
              and set(build.read_scene().get("shadows_turned_off") or []) == set(trimmed), str(trimmed))

        _step(build, PARTS_CODE)
        gaps = build.part_gaps("Chair")
        check("fix: the wing 4 cm off the chair is found on the surfaces, the touching parts are not",
              len(gaps) == 1 and gaps[0]["parts"] == ["Chair_Wing"] and 0.03 <= gaps[0]["gap_m"] <= 0.05,
              json.dumps(gaps))

        mark = build.mark()
        _step(build, BOX_CODE + 'box("Bench", (2, 0.5, 0.5), (5, 5, 0))\n')
        bench = build.created_since(mark)
        roots = {c["name"] for c in chat_run._detail_roots(build, mark, ["Pine_001_Trunk"])}
        check("fix: a change details only what it made and the root it points at",
              len(bench) == 1 and roots == {bench[0], "Pine_001"}, str(sorted(roots)))
        before = build.mark()
        _step(build, BOX_CODE + 'box("Chair_Cushion", (0.8, 0.8, 0.1), (0, 0, 0.6))\n')
        chat_run._into(build, "Chair", before)
        cushion = scene.objects["Chair_Cushion"]
        check("fix: a new piece without a parent becomes part of the one target, where it stands",
              cushion.parent == scene.objects["Chair"]
              and tuple(round(v, 3) for v in cushion.matrix_world.translation) == (0.0, 0.0, 0.6))

        done = chat_run._detail_copies(build, ["Pine_000"])
        pine = scene.objects["Pine_001"]
        trunk = scene.objects.get("Pine_001_Trunk")
        tiers = sorted(o.name for o in pine.children_recursive if "Tier" in o.name)
        low = min((pine.matrix_world @ mathutils.Vector(c)).x for o in [pine] + list(pine.children_recursive)
                  if o.type == "MESH" for c in o.bound_box)
        check("fix: copies of a detailed object are rebuilt from it where they stood, sharing its meshes",
              done == {"rebuilt": 2, "skipped": 0} and len(tiers) == 4 and trunk is not None
              and trunk.data == scene.objects["Pine_000_Trunk"].data and build.owns(pine)
              and abs(low - (10 - 1 * 3 / 3.6)) < 0.01, "%s %s %s" % (done, tiers, round(low, 3)))
        check("fix: a copy of a very different size is left alone",
              len(scene.objects["Pine_003"].children) == 1, str([o.name for o in scene.objects["Pine_003"].children]))

        cam_code = BOX_CODE + '''
box("Cabin", (4, 4, 3), (0, 0, 0))
box("Tree", (2, 2, 6), (5, -5, 0))
aim = bpy.data.objects.new("Aim", None)
aim.location = (0, 0, 1.5)
scene.collection.objects.link(aim)
cam = bpy.data.objects.new("Orbit cam", bpy.data.cameras.new("Orbit cam"))
scene.collection.objects.link(cam)
c = cam.constraints.new("TRACK_TO")
c.target = aim
c.track_axis = "TRACK_NEGATIVE_Z"
c.up_axis = "UP_Y"
cam.location = (0, -20, 2)
cam.keyframe_insert("location", frame=1)
cam.location = (20, 0, 2)
cam.keyframe_insert("location", frame=49)
scene.camera = cam
scene.frame_start, scene.frame_end = 1, 49
'''
        _step(build, cam_code)
        view = build.camera_view()
        during = {p["frame"]: p.get("subject", {}) for p in view.get("during_move") or []}
        check("fix: camera_view follows the subject through the move and names what hides it",
              view.get("subject") == "Cabin" and sorted(during) == [13, 25, 37]
              and during[25].get("hidden_by") == "Tree" and view["frames"][0]["subject"]["in_frame"],
              json.dumps({"subject": view.get("subject"), "during": during})[:600])
        problems = chat_loop.view_problems(json.dumps(view))
        check("fix: the check stage is told the tree hides the cabin mid-move",
              any("Tree hides the subject Cabin" in p for p in problems), str(problems))
    finally:
        bpy.data.scenes.remove(scene)


RESTING_CODE = BOX_CODE + '''
def part(root, name, size, at):
    obj = box(name, size, at)
    obj.parent = root
    obj.matrix_parent_inverse = root.matrix_basis.inverted()
    return obj
chair = bpy.data.objects.new("Rest Armchair", None)
scene.collection.objects.link(chair)
part(chair, "Rest Armchair_Seat", (1, 1, 0.45), (0, 0, 0))
part(chair, "Rest Armchair_Cushion", (0.9, 0.9, 0.15), (0, 0, 0.45))
cat = bpy.data.objects.new("Rest Cat", None)
scene.collection.objects.link(cat)
part(cat, "Rest Cat_Body", (0.4, 0.3, 0.25), (0, 0, 0.42))
table = bpy.data.objects.new("Rest Table", None)
scene.collection.objects.link(table)
part(table, "Rest Table_Top", (1, 1, 0.05), (3, 0, 0.7))
part(table, "Rest Table_Leg", (0.1, 0.1, 0.7), (3, 0, 0))
vase = bpy.data.objects.new("Rest Vase", None)
scene.collection.objects.link(vase)
part(vase, "Rest Vase_Body", (0.2, 0.2, 0.3), (3, 0, 0.75))
shelf = bpy.data.objects.new("Rest Shelf", None)
scene.collection.objects.link(shelf)
part(shelf, "Rest Shelf_Board_0", (1, 0.3, 0.02), (6, 0, 0.38))
part(shelf, "Rest Shelf_Board_1", (1, 0.3, 0.02), (6, 0, 0.8))
book = bpy.data.objects.new("Rest Book", None)
scene.collection.objects.link(book)
part(book, "Rest Book_Block", (0.05, 0.2, 0.3), (6, 0, 0.4))
'''
HEALTH_CODE = '''
def mesh(name, build):
    m = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(m)
    bm.free()
    obj = bpy.data.objects.new(name, m)
    scene.collection.objects.link(obj)
    return obj
def tube(bm):
    bmesh.ops.create_cone(bm, cap_ends=False, segments=16, radius1=0.15, radius2=0.15, depth=1.0)
def capped(bm):
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.15, radius2=0.15, depth=1.0)
def holed(bm):
    bmesh.ops.create_cube(bm, size=1.0)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[0]], context="FACES_ONLY")
def turned(bm):
    bmesh.ops.create_cube(bm, size=1.0)
    bm.faces.ensure_lookup_table()
    bmesh.ops.reverse_faces(bm, faces=[bm.faces[0]])
def sheet(bm):
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=1.0)
mesh("Open post", tube).location = (10, 0, 0)
mesh("Capped post", capped).location = (12, 0, 0)
mesh("Box with a hole", holed).location = (14, 0, 0)
mesh("Box turned inside", turned).location = (16, 0, 0)
mesh("Sign sheet", sheet).location = (18, 0, 0)
'''
STANDOFF_CODE = BOX_CODE + '''
def part(root, name, size, at):
    obj = box(name, size, at)
    obj.parent = root
    obj.matrix_parent_inverse = root.matrix_basis.inverted()
    return obj
cabin = bpy.data.objects.new("Rest Cabin", None)
scene.collection.objects.link(cabin)
part(cabin, "Rest Cabin_Wall", (4, 0.3, 3), (30, 0, 0))
part(cabin, "Rest Cabin_Frame", (0.8, 0.05, 0.8), (30, -0.275, 1.1))
part(cabin, "Rest Cabin_Bracket", (0.1, 0.1, 0.05), (30.45, -0.2, 1.5))
part(cabin, "Rest Cabin_Plaque", (0.3, 0.02, 0.2), (31.5, -0.18, 2.0))
'''


SETTLE_CODE = '''
def box(name, size, where):
    m = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bm.to_mesh(m)
    bm.free()
    o = bpy.data.objects.new(name, m)
    scene.collection.objects.link(o)
    o.location = where
    return o

g = box("Settle ground", (20, 20, 0.2), (0, 0, -0.1))
g["ground"] = True
box("Settle floating crate", (0.5, 0.5, 0.5), (0, 0, 0.75))
box("Settle resting crate", (0.5, 0.5, 0.5), (2, 0, 0.25))
box("Settle table", (1.2, 0.8, 0.75), (-3, 0, 0.375))
box("Settle cup", (0.1, 0.1, 0.1), (-3, 0, 1.25))
box("Settle shed", (3, 3, 2.5), (5, 5, 2.0))
box("Settle counter", (3, 1, 0.9), (10, 0, 0.45))
fish = bpy.data.objects.new("Settle fish", None)
scene.collection.objects.link(fish)
for i, x in enumerate((9.0, 11.0)):
    box("Settle fish %d" % i, (0.6, 0.2, 0.1), (x, 0, 1.05)).parent = fish
box("Settle stall", (3, 1, 0.9), (20, 0, 0.45))
box("Settle lamp table", (1.0, 1.0, 0.75), (-8, 0, 0.375))
box("Settle ceiling", (4, 4, 0.2), (-8, 0, 3.0))
box("Settle hanging lamp", (0.4, 0.4, 1.2), (-8, 0, 2.3))
catch = bpy.data.objects.new("Settle catch", None)
scene.collection.objects.link(catch)
for i, x in enumerate((19.0, 21.0)):
    body = box("Settle whole fish %d" % i, (0.4, 0.15, 0.1), (x, 0, 1.05))
    attach(box("Settle whole fish %d tail" % i, (0.1, 0.1, 0.1), (x + 0.25, 0, 1.1)), body)
    attach(box("Settle whole fish %d fin" % i, (0.1, 0.02, 0.1), (x, 0, 1.15)), body)
    thing(body, "fish")
    attach(body, catch)
thing(catch, "catch of fish")
'''


def test_settle():
    """Small loose props come down onto what is under them; resting ones and big things stay put."""
    from eachlabs import scene_build
    from eachlabs.placement import settle

    scene = bpy.data.scenes.new("eachlabs_settle")
    build = scene_build.SceneBuild(scene, "settle-run")
    try:
        check("settle: the props are built", _step(build, SETTLE_CODE).get("ok"))
        moved = {e["thing"]: e["dropped_m"] for e in settle.settle(build)}
        objs = scene.objects
        check("settle: a floating crate comes down onto the ground, a cup onto its table",
              abs(moved.get("Settle floating crate", 0) - 0.5) < 0.02 and abs(moved.get("Settle cup", 0) - 0.45) < 0.02
              and abs(objs["Settle floating crate"].location.z - 0.25) < 0.02, str(moved))
        check("settle: a resting crate, the table and a big shed stay where they are",
              not {"Settle resting crate", "Settle table", "Settle shed", "Settle ground"} & set(moved)
              and abs(objs["Settle shed"].location.z - 2.0) < 1e-6, str(moved))
        check("settle: a group of parts wider than a prop settles whole onto its counter",
              abs(moved.get("Settle fish", 0) - 0.1) < 0.02
              and all(abs(objs["Settle fish %d" % i].matrix_world.translation.z - 0.95) < 0.02 for i in (0, 1)),
              str(moved))
        check("settle: a lamp whose top touches the ceiling hangs there, over its table",
              "Settle hanging lamp" not in moved and abs(objs["Settle hanging lamp"].location.z - 2.3) < 1e-6,
              str(moved))
        offsets = [(objs["Settle whole fish %d %s" % (i, p)].matrix_world.translation
                    - objs["Settle whole fish %d" % i].matrix_world.translation) for i in (0, 1) for p in ("tail", "fin")]
        check("settle: each fish of separate parts settles as one onto the stall, its parts keep their places",
              all(abs(moved.get("Settle whole fish %d" % i, 0) - 0.1) < 0.02 for i in (0, 1))
              and all(abs(objs["Settle whole fish %d" % i].matrix_world.translation.z - 0.95) < 0.02 for i in (0, 1))
              and all(abs(d.x - e.x) < 1e-4 and abs(d.z - e.z) < 1e-4 for d, e in zip(
                  offsets, [mathutils.Vector((0.25, 0, 0.05)), mathutils.Vector((0, 0, 0.1))] * 2)),
              "%s %s" % (moved, [tuple(round(v, 3) for v in o) for o in offsets]))
    finally:
        bpy.data.scenes.remove(scene)


def test_resting_and_mesh_health():
    """A thing sunk into what it rests on, a follow-up's new group kept apart, open and turned meshes, and an
    attached part standing off its wall."""
    import json

    from eachlabs import chat_run, scene_build

    scene = bpy.data.scenes.new("eachlabs_resting")
    build = scene_build.SceneBuild(scene, "resting-run")
    try:
        check("rest: the room is built", _step(build, RESTING_CODE).get("ok"))
        sunk = {e["thing"]: e for e in build.read_scene().get("sunk_into") or []}
        cat = sunk.get("Rest Cat") or {}
        check("rest: the cat sunk 18 cm into the armchair is listed with its depth",
              cat.get("into") == "Rest Armchair" and 0.16 <= cat.get("depth_m", 0) <= 0.2, json.dumps(sunk))
        check("rest: a vase on its table, a book on its shelf and the shelf around the book are not listed",
              not {"Rest Vase", "Rest Book", "Rest Table", "Rest Shelf"} & set(sunk), json.dumps(sunk))
        scene.objects["Rest Cat"].location.z += 0.18
        check("rest: a cat lifted onto the cushion is not listed",
              "Rest Cat" not in {e["thing"] for e in build.read_scene().get("sunk_into") or []})

        build.since = build.mark()
        mark = build.mark()
        added = ('grp = bpy.data.objects.new("Rest armchair | sleeping dog", None)\n'
                 'scene.collection.objects.link(grp)\n'
                 'grp.parent = bpy.data.objects["Rest Armchair"]\n'
                 'grp.location = (0.1, 0, 0.6)\n'
                 'm = bpy.data.meshes.new("Rest Dog body")\n'
                 'bm = bmesh.new()\n'
                 'bmesh.ops.create_cube(bm, size=0.3)\n'
                 'bm.to_mesh(m)\n'
                 'bm.free()\n'
                 'body = bpy.data.objects.new("Rest Dog body", m)\n'
                 'scene.collection.objects.link(body)\n'
                 'body.parent = grp\n'
                 'leg = bpy.data.objects.new("Rest Armchair new leg", bpy.data.meshes.new("leg"))\n'
                 'scene.collection.objects.link(leg)\n'
                 'leg.parent = bpy.data.objects["Rest Armchair"]\n')
        _step(build, added)
        dog = scene.objects["Rest armchair | sleeping dog"]
        before = dog.matrix_world.translation.copy()
        chat_run._apart(build, mark)
        check("rest: a follow-up's new group parented to an older object becomes its own root, where it stands",
              dog.parent is None and (dog.matrix_world.translation - before).length < 1e-6
              and scene.objects["Rest Dog body"].parent == dog)
        check("rest: a single new part of the older object stays its part",
              scene.objects["Rest Armchair new leg"].parent == scene.objects["Rest Armchair"])

        build.since = build.mark()
        _step(build, HEALTH_CODE)
        seen = build.read_scene()
        holes = {e["name"]: e for e in seen.get("open_holes") or []}
        flipped = {e["name"] for e in seen.get("flipped_normals") or []}
        check("rest: an uncapped tube and a box with a missing face are listed, with where",
              holes.get("Open post", {}).get("loops") == 2 and holes.get("Box with a hole", {}).get("loops") == 1
              and len(holes["Box with a hole"]["where"]) == 3, json.dumps(holes))
        check("rest: a capped tube, a closed box and a flat sheet are not listed",
              not {"Capped post", "Box turned inside", "Sign sheet"} & set(holes), json.dumps(holes))
        check("rest: a box with one face turned inside is listed under flipped_normals",
              flipped == {"Box turned inside"}, str(flipped))

        _step(build, STANDOFF_CODE)
        gaps = build.part_gaps("Rest Cabin")
        off = [g for g in gaps if g.get("stands_off") == "Rest Cabin_Wall"]
        check("rest: a window frame 10 cm in front of its wall is found though a bracket joins them",
              any("Rest Cabin_Frame" in g["parts"] and 0.09 <= g["gap_m"] <= 0.11 for g in off), json.dumps(gaps))
        check("rest: the widest gap comes first, so a cut list keeps what shows",
              gaps and "Rest Cabin_Frame" in gaps[0]["parts"]
              and any("Rest Cabin_Plaque" in g["parts"] for g in gaps[1:]), json.dumps(gaps))
    finally:
        bpy.data.scenes.remove(scene)


ZONES_CODE = BOX_CODE + """# Two villages and a camp laid out as zones
box("Zone ground", (200, 120, 0.05), (0, 0, -0.05))
def zone(name, at, size, apart=None, holds=None):
    z = bpy.data.objects.new(name, None)
    scene.collection.objects.link(z)
    z.location = at
    z["zone"] = True
    z["size"] = size
    if apart is not None:
        z["apart_m"] = apart
    if holds is not None:
        z["holds"] = holds
    return z
small = zone("Zone small village", (-60, 0, 0), [40, 40], 30, holds=1)
large = zone("Zone large village", (-30, 0, 0), [40, 40], 30, holds=12)
camp = zone("Zone camp", (60, 30, 0), [20, 20])
attach(box("Small house", (6, 6, 5), (-62, 2, 0)), small)
attach(box("Large house", (6, 6, 5), (-30, 0, 0)), large)
attach(box("Stray house", (6, 6, 5), (40, -40, 0)), large)
attach(box("Camp tent", (3, 3, 2), (60, 30, 0)), camp)
attach(box("Camp lookout", (2, 2, 4), (60, 75, 0)), camp)
# A hamlet built by coordinates, nothing placed in it by name, and a field with nothing at all
zone("Zone hamlet", (20, -40, 0), [16, 16], holds=3)
zone("Zone field", (70, -40, 0), [16, 16], holds=5)
for i in range(3):
    box("Hamlet hut %d" % i, (3, 3, 3), (15 + 5 * i, -40, 0))
"""


def test_zones():
    """The areas a layout states are checked: a thing outside its zone, zones that overlap and zones closer than
    the gap the model gave; a part off the ground's extent is listed under its thing."""
    import json

    from eachlabs import chat_loop, scene_build

    scene = bpy.data.scenes.new("eachlabs_zones")
    build = scene_build.SceneBuild(scene, "zones-run")
    try:
        check("zones: the scene is built", _step(build, ZONES_CODE).get("ok"))
        seen = build.read_scene()
        zones = {z["name"]: z for z in seen.get("zones") or []}
        large, small = zones.get("Zone large village", {}), zones.get("Zone small village", {})
        check("zones: a house outside its village's zone is listed", "Stray house" in (large.get("outside") or []),
              json.dumps(zones))
        check("zones: the two villages overlap and are listed as overlapping",
              "Zone large village" in (small.get("overlaps") or []), json.dumps(small))
        check("zones: the camp's lookout stands outside the camp zone and off the ground",
              "Camp lookout" in (zones.get("Zone camp", {}).get("outside") or [])
              and any("Camp lookout" in e.get("parts", []) for e in seen.get("outside_ground") or []),
              json.dumps([zones.get("Zone camp"), seen.get("outside_ground")]))
        check("zones: a village holding 2 of the 12 houses it should is underfilled, a full one is not",
              large.get("underfilled") == {"things": 2, "holds": 12} and "underfilled" not in small,
              json.dumps([large, small]))
        hamlet, field = zones.get("Zone hamlet", {}), zones.get("Zone field", {})
        check("zones: a hamlet built by coordinates is not underfilled, an empty field is",
              "underfilled" not in hamlet and field.get("underfilled") == {"things": 0, "holds": 5},
              json.dumps([hamlet, field]))
        problems = chat_loop.placement_problems(seen)
        check("zones: the placement problems carry the zones and the parts off the ground",
              {"zones", "outside_ground"} <= set(problems), json.dumps(sorted(problems)))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


PLACEMENT_CODE = """# Ground, a mountain and a lake, then areas, a camp and a forest placed by relations
import bmesh
def box(name, size, at=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0, 0, size[2] / 2), verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    ob.location = at
    return ob
box("Pl ground", (400, 400, 0.1), (0, 0, -0.1))
box("Pl mountain", (60, 60, 40))
lake = box("Pl lake", (40, 40, 0.05), (-120, 0, 0))
lake["walkable"] = False
zone("Forest", ring_m=60, around="Pl mountain")
zone("Camp", size=(24, 24), inside="Forest")
zone("Village", size=(50, 50), apart_m={"Camp": 60})
box("Pl fire ring", (1.2, 1.2, 0.3))
place("Pl fire ring", zone="Camp")
for i in range(4):
    box("Pl tent %d" % i, (2.5, 3, 2))
    place("Pl tent %d" % i, zone="Camp", around={"to": "Pl fire ring", "radius_m": 6})
for i in range(5):
    box("Pl bandit %d" % i, (0.6, 0.6, 1.8))
    place("Pl bandit %d" % i, zone="Camp", around="Pl fire ring")
for i in range(6):
    box("Pl house %d" % i, (6, 8, 5))
    place("Pl house %d" % i, zone="Village", gap_m=3)
box("Pl pine", (3, 3, 9))
scatter("Pl pine", zone="Forest", count=150)
"""


def test_placement():
    """Things placed by relations: areas laid out by size, rings and distances, tents and bandits around a fire
    inside their camp, houses apart in their village, a forest spread around a mountain clear of everything."""
    import json
    import math

    from eachlabs import scene_build
    from eachlabs.placement import scene_io

    scene = bpy.data.scenes.new("eachlabs_placement")
    build = scene_build.SceneBuild(scene, "placement-run")
    try:
        result = _step(build, PLACEMENT_CODE)
        report = result.get("placement") or {}
        check("placement: the step runs and places", result.get("ok") and report.get("placed", 0) >= 15,
              json.dumps(result)[:600])
        check("placement: nothing is left unplaced", not report.get("unplaced"), json.dumps(report)[:600])
        objs = scene.objects
        forest, camp, village = objs.get("Zone Forest"), objs.get("Zone Camp"), objs.get("Zone Village")
        check("placement: the three areas exist, the forest as a ring",
              forest is not None and camp is not None and village is not None and forest.get("ring") is not None,
              str([o.name for o in objs if o.get("zone")]))
        if forest is None or camp is None or village is None:
            return
        cx, cy = camp.matrix_world.translation[:2]
        r = math.hypot(cx, cy)
        inner, outer = forest["ring"]
        check("placement: the camp lies in the forest ring", inner <= r <= outer, "%.1f in %s" % (r, list(forest["ring"])))
        fire = objs["Pl fire ring"].matrix_world.translation
        tents = [scene_io.world_box(objs["Pl tent %d" % i]) for i in range(4)]
        half = camp["size"][0] / 2 + 0.5
        check("placement: every tent stands inside the camp, on the ground",
              all(abs((t[0][0] + t[1][0]) / 2 - cx) <= half and abs((t[0][1] + t[1][1]) / 2 - cy) <= half
                  and abs(t[0][2]) < 0.05 for t in tents), str(tents))
        bandits = [objs["Pl bandit %d" % i].matrix_world.translation for i in range(5)]
        dist = [math.hypot(b.x - fire.x, b.y - fire.y) for b in bandits]
        check("placement: the bandits sit in a ring around the fire", all(0.8 < d < 4.0 for d in dist), str(dist))
        vx, vy = village.matrix_world.translation[:2]
        gap = max(abs(vx - cx) - (village["size"][0] + camp["size"][0]) / 2,
                  abs(vy - cy) - (village["size"][1] + camp["size"][1]) / 2)
        check("placement: the village keeps 60 m from the camp", gap >= 59.5, "%.1f" % gap)
        houses = [scene_io.world_box(objs["Pl house %d" % i]) for i in range(6)]
        clash = any(a[0][0] < b[1][0] and b[0][0] < a[1][0] and a[0][1] < b[1][1] and b[0][1] < a[1][1]
                    for i, a in enumerate(houses) for b in houses[i + 1:])
        check("placement: no two houses overlap", not clash)
        pines = [o for o in objs if o.name.startswith("Pl pine")]
        mountain = scene_io.world_box(objs["Pl mountain"])
        in_mountain = [p.name for p in pines if mountain[0][0] < p.matrix_world.translation.x < mountain[1][0]
                       and mountain[0][1] < p.matrix_world.translation.y < mountain[1][1]]
        check("placement: the forest has many pines, none on the mountain", len(pines) >= 100 and not in_mountain,
              "%d pines, %d on it" % (len(pines), len(in_mountain)))
        lake = scene_io.world_box(objs["Pl lake"])
        wet = [p.name for p in pines if lake[0][0] < p.matrix_world.translation.x < lake[1][0]
               and lake[0][1] < p.matrix_world.translation.y < lake[1][1]]
        check("placement: no pine stands in the lake", not wet, str(wet[:5]))
        zones = {z["name"]: z for z in build.read_scene().get("zones") or []}
        check("placement: the camp inside the forest ring is not an overlap",
              "Zone Forest" not in (zones.get("Zone Camp", {}).get("overlaps") or []), json.dumps(zones)[:400])
        _step(build, 'g = bpy.data.objects["Pl ground"]\ng.scale = (8, 8, 1)')
        fit = [z.get("ground_fit") for z in build.read_scene().get("zones") or [] if z.get("ground_fit")]
        check("placement: a ground far larger than its areas is listed", bool(fit), json.dumps(fit))
        tent = objs["Pl tent 0"]
        from eachlabs.things import registry as thing_registry
        found = thing_registry.roots(build._objects())
        check("placement: a thing placed in an area joins it as a thing whose parent thing is the area",
              tent.parent is camp and thing_registry.is_root(tent)
              and thing_registry.parent_of(tent, found) == thing_registry.thing_of(camp),
              str((tent.parent, thing_registry.thing_of(tent), thing_registry.thing_of(camp))))
        # The request said the wood is around the mountain and the hamlet inside the wood; zone() left both out.
        for name in ("Zone Forest", "Zone Camp", "Zone Village"):  # clear room for the new areas
            bpy.data.objects.remove(objs[name])
        build.area_rules = [{"area": "wood", "around": "mountain"}, {"area": "hamlet", "inside": "wood"}]
        _step(build, 'zone("Pine wood", size=[90, 90])\nzone("Hamlet", size=[20, 20], near=["Pine wood", 0, 10])')
        wood, hamlet = objs.get("Zone Pine wood"), objs.get("Zone Hamlet")
        check("placement: the request's around and inside are honoured when zone() leaves them out",
              wood is not None and wood.get("ring") is not None and hamlet is not None
              and hamlet.get("inside") == "Pine wood", str([wood and dict(wood), hamlet and dict(hamlet)])[:300])
        stray = bpy.data.objects.new("Zone Stray wood", None)
        scene.collection.objects.link(stray)
        build.adopt(stray)
        stray["zone"], stray["size"], stray["stated_around"] = True, [40, 40], "Pl mountain"
        stray.location = (150, 150, 0)
        zones_seen = {z["name"]: z for z in build.read_scene().get("zones") or []}
        check("placement: an area not around what the request puts it around is listed",
              "way round" in (zones_seen.get("Zone Stray wood", {}).get("relation_unmet") or "")
              and not zones_seen.get("Zone Pine wood", {}).get("relation_unmet"), json.dumps(zones_seen)[:500])
        bad = _step(build, 'place("Pl tent 0", zone="Nowhere")')
        check("placement: an unknown area comes back with the rule",
              any("Nowhere" in u.get("rule", "") for u in (bad.get("placement") or {}).get("unplaced", [])),
              json.dumps(bad)[:300])
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)
