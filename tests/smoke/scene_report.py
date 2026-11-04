"""What read_scene and camera_view report about a built scene."""

import bpy

from tests.smoke.common import BOX_CODE, _step, check


ROW_CODE = """# A row of posts with vertices in world coordinates, and a printed list
def post(name, x):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x += x
        v.co.y += 20
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
for i in range(8):
    post("Post_%02d" % i, i * 3.0)
post("Kiosk", -10.0)
for i in range(7):
    data = bpy.data.lights.new("Glow_%02d" % i, "POINT")
    data.energy = 200.0 if i < 4 else 400.0
    lamp = bpy.data.objects.new("Glow_%02d" % i, data)
    lamp.location = (i * 3.0, 20, 4)
    scene.collection.objects.link(lamp)
print("HEAD" + "x" * 3000)
"""


def test_read_scene_groups():
    """A large scene fits in read_scene: objects of one kind are one entry, and world bounds show where geometry
    is when every origin is 0. A long print keeps its start."""
    import json

    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_groups")
    build = scene_build.SceneBuild(scene, "groups")
    result = _step(build, ROW_CODE)
    seen = build.execute("read_scene", {})["objects"]
    posts = [o for o in seen if o.get("name_pattern") == "Post_#"]
    kiosk = next((o for o in seen if o.get("name") == "Kiosk"), {})
    check("read_scene: eight posts are one entry with the first and last name and the space they fill",
          len(seen) == 2 and len(posts) == 1 and posts[0]["count"] == 8
          and posts[0]["names"] == ["Post_00", "Post_07"]
          and posts[0]["spread"] == [[-0.5, 19.5, -0.5], [21.5, 20.5, 0.5]], json.dumps(seen)[:400])
    check("read_scene: an object whose vertices sit away from its origin lists its world bounds",
          kiosk.get("location") == [0.0, 0.0, 0.0] and kiosk.get("bounds") == [[-10.5, 19.5, -0.5], [-9.5, 20.5, 0.5]],
          json.dumps(kiosk))
    lights = build.execute("read_scene", {})["lights"]
    check("read_scene: lights of one name but a different power are separate entries",
          sorted((l.get("count"), l.get("energy")) for l in lights) == [(3, 400.0), (4, 200.0)], json.dumps(lights)[:300])
    output = result.get("output", "")
    check("code runner: a long print keeps its start and says how much was cut",
          output.startswith("HEAD") and "more characters cut" in output and len(output) < 2200, output[-120:])

    _step(build, FIGURES_CODE)
    theirs = []  # the person's own figure, built outside the chat, with a part far from the rest
    for name, z in (("Person_Z_Head", 1.6), ("Person_Z_Body", 1.0), ("Person_Z_Hand", 9.0)):
        obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        obj.location = (0, -30, z)
        scene.collection.objects.link(obj)
        theirs.append(obj)
    seen = build.execute("read_scene", {})
    loose = seen.get("loose_parts") or []
    check("read_scene: a figure whose parts were parented without keeping their place is listed with them",
          [g["parts_of"] for g in loose] == ["FigA and its children"] and loose[0]["parts"] == 3
          and loose[0]["pieces"] == 2 and loose[0]["apart"] == ["FigA_PartC"], json.dumps(loose))
    check("read_scene: loose_parts never names the person's objects", "Person_Z" not in json.dumps(seen),
          json.dumps(loose))
    _step(build, OVERLAP_CODE)
    mine = bpy.data.objects.new("Person_Y", bpy.data.meshes.new("Person_Y"))  # the person's, on the same roof
    mine.location = (80, 80, 3.9)
    scene.collection.objects.link(mine)
    theirs.append(mine)
    seen = build.execute("read_scene", {})
    check("read_scene: a thing of the chat's standing on another one's roof is listed in overlaps",
          seen.get("overlaps") == [{"thing": "Walker", "on": "Kiosk_Block"}], json.dumps(seen.get("overlaps")))
    check("read_scene: overlaps never names the person's objects", "Person_Y" not in json.dumps(seen),
          json.dumps(seen.get("overlaps")))
    for obj in theirs:
        bpy.data.objects.remove(obj, do_unlink=True)
    for obj in [o for o in bpy.data.objects if o.get(scene_build.RUN) == "groups"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    coll = bpy.data.collections.get(build.collection_name or "")
    if coll is not None:
        bpy.data.collections.remove(coll)
    bpy.data.scenes.remove(scene)


# Two figures of three boxes at x = 5 and x = -5, each parented to an empty there. FigA sets only part.parent, so its
# two parented parts move by the empty's offset to x = 10, away from the third; FigB keeps them in place.
FIGURES_CODE = """# Two figures
def box(name, x, z):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.4)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = (x, 5, z)
    scene.collection.objects.link(obj)
    return obj
for fig, x, keep in (("FigA", 5, False), ("FigB", -5, True)):
    root = bpy.data.objects.new(fig, None)
    root.location = (x, 0, 0)
    scene.collection.objects.link(root)
    for letter, z in (("A", 0.2), ("B", 0.6)):
        part = box(fig + "_Part" + letter, x, z)
        part.parent = root
        if keep:
            part.matrix_parent_inverse = root.matrix_basis.inverted()
    box(fig + "_PartC", x, 1.0)
"""

OVERLAP_CODE = """# A kiosk with a walker standing on its roof
def box(name, centre, size):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = centre
    obj.scale = size
    scene.collection.objects.link(obj)
box("Kiosk_Block", (80, 80, 1.5), (4, 4, 3))
box("Walker", (80, 80, 3.9), (0.5, 0.3, 1.8))
"""


ROOM_CODE = """# A closed room with a fireplace, and a camera inside aimed at it
def box(name, size, at):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = at
    scene.collection.objects.link(obj)
    return obj
box("Floor", (8, 8, 0.2), (0, 0, -0.1))
box("Ceiling", (8, 8, 0.2), (0, 0, 3.1))
box("Wall N", (8, 0.2, 3), (0, 4, 1.5))
box("Wall S", (8, 0.2, 3), (0, -4, 1.5))
box("Wall E", (0.2, 8, 3), (4, 0, 1.5))
box("Wall W", (0.2, 8, 3), (-4, 0, 1.5))
fire = box("Fireplace", (1.6, 0.6, 1.2), (0, 3.5, 0.6))
aim = bpy.data.objects.new("Aim", None)
aim.location = (0, 3.5, 0.6)
scene.collection.objects.link(aim)
cam = bpy.data.objects.new("Room camera", bpy.data.cameras.new("Room camera"))
cam.location = (0, -3, 1.6)
scene.collection.objects.link(cam)
track = cam.constraints.new("TRACK_TO")
track.target = aim
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"
scene.camera = cam
"""


def test_camera_view_room():
    """camera_view says whether the camera is inside the space the chat built, what stands first towards its
    aim point, and how much of the frame the person's objects cover, by share and count only."""
    import json

    import bmesh

    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_room_view")
    scene.frame_start = scene.frame_end = 1
    build = scene_build.SceneBuild(scene, "roomview")
    made = _step(build, ROOM_CODE)
    view = build.execute("camera_view", {})["frames"][0]
    check("camera_view: a camera inside the chat's room is enclosed and sees the fireplace first",
          made.get("ok") and view["camera_enclosed"] is True and view["toward_target"]["first_hit"] == "Fireplace"
          and view["not_yours_in_view"] == 0 and view["not_yours_cover_pct"] == 0.0, json.dumps(view)[:400])
    blocker = bpy.data.objects.new("Person's crate", bpy.data.meshes.new("Person's crate"))
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(blocker.data)
    bm.free()
    blocker.location = (0, -1, 1.2)
    scene.collection.objects.link(blocker)
    view = build.execute("camera_view", {})["frames"][0]
    text = json.dumps(view)
    check("camera_view: the person's object in front is a share and a count, never a name",
          view["not_yours_in_view"] == 1 and view["not_yours_cover_pct"] > 10
          and view["toward_target"]["first_hit"] == "(not yours)" and "crate" not in text, text[:400])
    bpy.data.objects.remove(blocker)
    bpy.data.objects["Room camera"].location = (0, -9, 1.6)
    view = build.execute("camera_view", {})["frames"][0]
    check("camera_view: a camera outside the room is not enclosed and meets a wall first",
          view["camera_enclosed"] is False and view["toward_target"]["first_hit"] == "Wall S"
          and view["toward_target"]["hit_distance"] < view["toward_target"]["target_distance"], json.dumps(view)[:400])
    for obj in [o for o in bpy.data.objects if o.get(scene_build.RUN) == "roomview"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    coll = bpy.data.collections.get(build.collection_name or "")
    if coll is not None:
        bpy.data.collections.remove(coll)
    bpy.data.scenes.remove(scene)


def test_free_space():
    """read_scene lists the free areas of the chat's ground, and a new thing that stands through one that existed
    before the change."""
    import json

    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_free")
    build = scene_build.SceneBuild(scene, "free-space-run")
    try:
        town = BOX_CODE + ('box("Ground", (40, 20, 0.1), (20, 10, -0.1))\n'
                           'for i, x in enumerate((4, 14, 24, 34)):\n'
                           '    box("House_%d" % i, (8, 8, 7), (x, 16, 0))\n')
        check("free space: the town is built", build.execute("run_python", {"code": town}).get("ok"))
        seen = build.read_scene()
        free = seen.get("free_space") or {}
        biggest = (free.get("areas") or [{}])[0]
        check("free space: read_scene gives the ground and the biggest empty area in front of the houses",
              free.get("ground") == [0.0, 0.0, 40.0, 20.0] and biggest.get("size", [0])[0] >= 38
              and biggest.get("centre", [0, 99])[1] < 12, json.dumps(free))
        build.existing = {o.name for o in build._objects()}
        church = BOX_CODE + 'box("Church", (10, 18, 20), (8, 12, 0))\n'
        build.execute("run_python", {"code": church})
        overlaps = [o for o in build.read_scene().get("overlaps") or [] if "overlaps_existing" in o]
        check("free space: a new church through an existing house is listed by the chat's own names",
              overlaps and overlaps[0]["thing"] == "Church" and overlaps[0]["overlaps_existing"].startswith("House_")
              and "note" not in overlaps[0], json.dumps(overlaps))
        tower = BOX_CODE + 'box("Tower", (30, 30, 20), (20, 10, 0))\n'
        build.execute("run_python", {"code": tower})
        notes = [o.get("note") for o in build.read_scene().get("overlaps") or [] if o.get("thing") == "Tower"]
        check("free space: when nothing fits, read_scene says to extend the ground",
              notes == ["no free area fits 30 x 30 m; extend the ground"], str(notes))
    finally:
        bpy.data.scenes.remove(scene)


SOLIDS_CODE = (
    'import bmesh\n'
    'def box(name, size, at, parent=None):\n'
    '    bm = bmesh.new()\n'
    '    bmesh.ops.create_cube(bm, size=1.0)\n'
    '    bmesh.ops.scale(bm, vec=size, verts=bm.verts)\n'
    '    bmesh.ops.translate(bm, vec=at, verts=bm.verts)\n'
    '    me = bpy.data.meshes.new(name)\n'
    '    bm.to_mesh(me)\n'
    '    bm.free()\n'
    '    ob = bpy.data.objects.new(name, me)\n'
    '    scene.collection.objects.link(ob)\n'
    '    if parent is not None:\n'
    '        attach(ob, parent)\n'
    '    return ob\n'
    'box("Solid ground", (40, 40, 0.02), (0, 0, -0.01))\n'
    'house = bpy.data.objects.new("Solid house", None)\n'
    'scene.collection.objects.link(house)\n'
    'box("Solid house body", (4, 4, 3), (0, 0, 1.5), house)\n'
    'roof = box("Solid house roof", (4.4, 4.4, 2), (0, 0, 4), house)\n'
    'box("Solid house clock", (0.6, 0.2, 0.6), (0, 0, 4.0), house)\n'
    'box("Solid house window", (0.8, 0.1, 0.8), (0, -2.04, 1.5), house)\n'
    'box("Solid fence", (14, 0.3, 1.8), (0, 0, 0.9))\n'
    'box("Solid shed", (2, 2, 2), (8, 8, 1))\n'
    'bm = bmesh.new()\n'
    'bmesh.ops.create_cone(bm, cap_ends=False, segments=16, radius1=0.1, radius2=0.1, depth=2.0)\n'
    'me = bpy.data.meshes.new("Solid post")\n'
    'bm.to_mesh(me)\n'
    'bm.free()\n'
    'post = bpy.data.objects.new("Solid post", me)\n'
    'scene.collection.objects.link(post)\n'
    'post.location = (-8, 8, 1)\n'
    'bm = bmesh.new()\n'
    'bmesh.ops.create_cube(bm, size=1.0)\n'
    'bmesh.ops.scale(bm, vec=(4, 0.3, 3), verts=bm.verts)\n'
    'front = [f for f in bm.faces if f.normal.y < -0.5][0]\n'
    'inner = bmesh.ops.inset_region(bm, faces=[front], thickness=1.2)\n'
    'bmesh.ops.delete(bm, geom=[front], context="FACES_ONLY")\n'
    'me = bpy.data.meshes.new("Solid wall")\n'
    'bm.to_mesh(me)\n'
    'bm.free()\n'
    'wall = bpy.data.objects.new("Solid wall", me)\n'
    'scene.collection.objects.link(wall)\n'
    'wall.location = (-8, -8, 1.5)\n'
)


def test_solids():
    """Separate things that pass through each other, a part hidden inside a bigger part of its own thing, and
    small flat open ends closed while a window opening in a wall stays open."""
    import json

    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_solids")
    build = scene_build.SceneBuild(scene, "solids-run")
    try:
        check("solids: the scene is built", _step(build, SOLIDS_CODE).get("ok"))
        seen = build.read_scene()
        crossing = seen.get("crossing") or []
        pairs = {frozenset((c["thing"], c["crosses"])) for c in crossing}
        check("solids: the fence running through the house is listed as crossing it",
              frozenset(("Solid fence", "Solid house")) in pairs, json.dumps(crossing))
        check("solids: the shed apart and the house on the ground are not listed",
              not any("Solid shed" in p or "Solid ground" in p for p in pairs), json.dumps(crossing))
        hidden = {h["part"]: h for h in seen.get("hidden_parts") or []}
        check("solids: the clock inside the roof is listed as hidden in it",
              hidden.get("Solid house clock", {}).get("inside") == "Solid house roof", json.dumps(hidden))
        check("solids: the window against the wall is not listed as hidden", "Solid house window" not in hidden,
              json.dumps(hidden))
        post, wall = scene.objects["Solid post"], scene.objects["Solid wall"]
        open_post = _boundary(post)
        open_wall = _boundary(wall)
        build.note_change()
        build.end_stage("layout")
        check("solids: the post's open ends are closed at the end of the stage",
              open_post > 0 and _boundary(post) == 0 and "Solid post" in build.closed_ends,
              "%d -> %d %s" % (open_post, _boundary(post), build.closed_ends))
        check("solids: the window opening in the wall stays open", open_wall > 0 and _boundary(wall) == open_wall,
              "%d -> %d" % (open_wall, _boundary(wall)))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


FOREST_CODE = """# One tree, then a forest of copies that share its meshes
import bmesh, random
box_ground = bpy.data.meshes.new("Forest ground")
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=100)
bm.to_mesh(box_ground)
bm.free()
scene.collection.objects.link(bpy.data.objects.new("Forest ground", box_ground))
tree = bpy.data.objects.new("Pine", None)
scene.collection.objects.link(tree)
for name, r1, r2, depth, z in (("Pine trunk", 0.2, 0.15, 3, 1.5), ("Pine crown", 1.6, 0.0, 5, 5.5)):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=r1, radius2=r2, depth=depth)
    bmesh.ops.translate(bm, vec=(0, 0, z), verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    part = bpy.data.objects.new(name, me)
    scene.collection.objects.link(part)
    attach(part, tree)
random.seed(7)
for i in range(300):
    copy_thing(tree, (random.uniform(-90, 90), random.uniform(-90, 90), 0), random.uniform(0, 6.28),
               random.uniform(0.8, 1.2))
"""


def test_forest_copies():
    """Hundreds of copies of a many-part thing share its meshes, stand where they were placed, and the checks stay
    fast and quiet about trees touching each other."""
    import json
    import time

    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_forest")
    build = scene_build.SceneBuild(scene, "forest-run")
    try:
        started = time.monotonic()
        result = _step(build, FOREST_CODE)
        step_s = time.monotonic() - started
        crowns = [o for o in scene.objects if o.name.startswith("Pine crown")]
        check("forest: 300 copies of the tree are made in one step, sharing the crown mesh",
              result.get("ok") and len(crowns) == 301 and len({o.data.name for o in crowns}) == 1,
              "%s %d %.1fs" % (str(result)[:200], len(crowns), step_s))
        roots = [o for o in scene.objects if o.name.startswith("Pine") and o.parent is None]
        far = [o for o in roots if o.name != "Pine" and abs(o.matrix_world.translation.x) > 90.01]
        check("forest: every copy stands where it was placed", len(roots) == 301 and not far, str(len(roots)))
        started = time.monotonic()
        seen = build.read_scene()
        read_s = time.monotonic() - started
        check("forest: read_scene stays fast and lists no crossing between touching trees",
              read_s < 20 and not any("Pine" in c.get("thing", "") and "Pine" in c.get("crosses", "")
                                      for c in seen.get("crossing") or []),
              "%.1fs %s" % (read_s, json.dumps(seen.get("crossing"))[:300]))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


def test_blend():
    """blend() fuses a dog's round parts into one smooth surface on its root, keeps both fur colours, and leaves
    the eyes and collar it was not given as separate parts on the result."""
    import mathutils

    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_blend")
    build = scene_build.SceneBuild(scene, "blend-run")
    try:
        result = _step(build, DOG_CODE)
        dog = scene.objects.get("Dog")
        left = sorted(o.name for o in scene.objects)
        check("blend: the round parts become one mesh on the root, the eyes and collar stay separate",
              result.get("ok") and dog is not None
              and left == ["Dog", "Dog collar", "Dog ear", "Dog eye L", "Dog eye R", "Dog tail"]
              and all(scene.objects[n].parent == dog for n in ("Dog collar", "Dog eye L", "Dog eye R")),
              "%s %s" % (str(result)[:300], left))
        check("blend: a flat ear and a thin tail stay out, attached to the root, and the output names them",
              dog is not None and all(scene.objects[n].parent == dog for n in ("Dog ear", "Dog tail"))
              and "Dog ear" in result.get("output", "") and "Dog tail" in result.get("output", ""),
              repr(result.get("output")))
        if dog is not None:
            mesh = dog.data
            used = {p.material_index for p in mesh.polygons}
            check("blend: the result is one closed smooth surface of a sensible size, with both fur colours",
                  2000 < len(mesh.vertices) < 200000 and all(p.use_smooth for p in mesh.polygons)
                  and [m.name for m in mesh.materials] == ["Dog fur blended", "Dog belly blended"]
                  and used == {0, 1} and not dog.modifiers,
                  "%d verts, %s %s" % (len(mesh.vertices), [m.name for m in mesh.materials], used))
            colours = mesh.color_attributes.get("blend_other")
            mixes = [c.color[3] for c in colours.data] if colours is not None else []
            fading = sum(1 for m in mixes if 0.1 < m < 0.9)
            check("blend: the two fur colours fade into each other where they meet, and stay plain elsewhere",
                  colours is not None and colours.domain == "CORNER" and fading > 50
                  and sum(1 for m in mixes if m < 0.01) > len(mixes) // 2
                  and scene.objects["Dog eye L"].data.materials[0].name == "Dog belly",
                  "%d of %d corners fading" % (fading, len(mixes)))
            low = min((dog.matrix_world @ v.co).z for v in mesh.vertices)
            check("blend: the legs survive the remesh and still reach the ground", low < 0.05, "%.3f" % low)
            eye = scene.objects.get("Dog eye L")
            check("blend: a part left out keeps its place in the world",
                  eye is not None and (eye.matrix_world.translation - mathutils.Vector((0.55, 0.08, 0.62))).length
                  < 1e-4, str(eye and eye.matrix_world.translation))
        bad = _step(build, "blend([scene.objects['Dog']])")
        check("blend: one part is refused with a plain error", not bad.get("ok")
              and "two or more mesh objects" in (bad.get("error") or ""), str(bad)[:300])
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


# A small dog of overlapping spheres and cylinders; the body is the root and the parts are attached to it.
DOG_CODE = """import bmesh
fur = bpy.data.materials.new("Dog fur")
belly = bpy.data.materials.new("Dog belly")

def ball(name, size, at, mat):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.location, obj.scale = at, size
    mesh.materials.append(mat)
    return obj

def leg(name, at):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.05, radius2=0.05, depth=0.4)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.location = at
    mesh.materials.append(belly)
    return obj

dog = ball("Dog", (0.35, 0.16, 0.16), (0, 0, 0.42), fur)
parts = [ball("Dog head", (0.12, 0.11, 0.11), (0.42, 0, 0.6), fur),
         ball("Dog belly", (0.3, 0.13, 0.08), (0, 0, 0.33), belly)]
parts += [leg("Dog leg %d" % i, (x, y, 0.2)) for i, (x, y) in enumerate(((0.22, 0.08), (0.22, -0.08),
                                                                          (-0.22, 0.08), (-0.22, -0.08)))]
for part in parts:
    attach(part, dog)
extra = [ball("Dog eye L", (0.02, 0.02, 0.02), (0.55, 0.08, 0.62), belly),
         ball("Dog eye R", (0.02, 0.02, 0.02), (0.55, -0.08, 0.62), belly),
         ball("Dog collar", (0.05, 0.12, 0.12), (0.33, 0, 0.52), belly)]
for part in extra:
    attach(part, parts[0])
ear = ball("Dog ear", (0.05, 0.008, 0.06), (0.4, 0.08, 0.72), fur)
tail = leg("Dog tail", (-0.5, 0, 0.5))
tail.scale = (0.4, 0.4, 1.0)
attach(ear, parts[0])
attach(tail, dog)
thing(dog, "dog", "puppy")
blend([dog] + parts + [ear, tail], 0.5)
"""


def _boundary(obj):
    """Open edges of an object's mesh."""
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        return sum(1 for e in bm.edges if e.is_boundary)
    finally:
        bm.free()
