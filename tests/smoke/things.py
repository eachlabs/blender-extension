"""Things in Blender: ids, parents, replaced parts and removal."""

import types

import bpy

from tests.smoke.common import BOX_CODE, _step, check


REPLACE_CODE = '''
def flat(name, size, where, parent):
    m = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bm.to_mesh(m)
    bm.free()
    o = bpy.data.objects.new(name, m)
    scene.collection.objects.link(o)
    o.location = where
    attach(o, parent)
    return o

shop = bpy.data.objects.new("Shop", None)
scene.collection.objects.link(shop)
flat("Shop sign board", (2.0, 0.05, 0.6), (0, 0, 3), shop)
flat("Shop window glass", (1.0, 0.02, 1.2), (3, 0, 2), shop)
flat("Shop window frame", (1.1, 0.06, 1.3), (3, 0.02, 2), shop)
flat("Shop old door", (1.0, 0.05, 2.1), (-3, 0, 1.05), shop)
'''

REPLACE_CODE_2 = '''
shop = bpy.data.objects["Shop"]
m = bpy.data.meshes.new("carved")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bmesh.ops.scale(bm, vec=(2.1, 0.08, 0.62), verts=bm.verts)
bm.to_mesh(m)
bm.free()
o = bpy.data.objects.new("Shop sign board carved", m)
scene.collection.objects.link(o)
o.location = (0, 0.05, 3)
attach(o, shop)
door = bpy.data.objects.new("Shop new door", bpy.data.objects["Shop old door"].data.copy())
scene.collection.objects.link(door)
door.location = (-3, 0, 1.05)
attach(door, shop)
replace(bpy.data.objects["Shop old door"], door)
'''


def test_replaced_parts():
    """A rebuilt part's old version goes: replace() removes it at once, and a stacked old version of the same job is
    removed after the stage; a window's glass and frame stay."""
    from eachlabs import scene_build
    from eachlabs.scene import replaced

    scene = bpy.data.scenes.new("eachlabs_replace")
    build = scene_build.SceneBuild(scene, "replace-run")
    try:
        check("replace: the shop is built", _step(build, REPLACE_CODE).get("ok"))
        check("replace: the rebuilt sign and door are built", _step(build, REPLACE_CODE_2).get("ok"))
        names = set(o.name for o in scene.objects)
        check("replace: replace() removed the old door at once", "Shop old door" not in names
              and "Shop new door" in names, str(sorted(names)))
        done = replaced.prune(build)
        names = set(o.name for o in scene.objects)
        check("replace: the old sign under the carved one is removed, the window's glass and frame stay",
              "Shop sign board" not in names and "Shop sign board carved" in names
              and {"Shop window glass", "Shop window frame"} <= names
              and [d["removed"] for d in done] == ["Shop sign board"], "%s %s" % (sorted(names), done))
        check("replace: read_scene names what was replaced",
              (build.read_scene().get("replaced_parts") or [{}])[0].get("removed") == "Shop sign board")
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


THINGS_WALL_CODE = """
def box(name, x, y, z, sx, sy, sz):
    m = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(m)
    bm.free()
    o = bpy.data.objects.new(name, m)
    scene.collection.objects.link(o)
    o.location = (x, y, z)
    o.scale = (sx, sy, sz)
    return o
wall = box("Larger village stone perimeter wall", 0, 0, 1, 10, 0.4, 2)
thing(wall, "fence", "wall, perimeter, boundary")
for i in range(4):
    attach(box("perimeter merlon %d" % i, -4 + i * 2.5, 0, 2.3, 0.4, 0.4, 0.6), wall)
hall = box("town hall", 20, 0, 3, 6, 6, 6)
thing(hall, "town hall", "hall, civic building")
clock = box("analog clock", 20, -3.1, 5, 1.5, 0.1, 1.5)
thing(clock, "clock", "dial", parent=hall)
loose = box("loose crate", 30, 0, 0.5, 1, 1, 1)
"""


def test_things():
    """Every object belongs to a thing: labels find a fence named a wall, removing a root takes its parts and child
    things along, copies are things of their own, orphans are reported then adopted, and things get collections."""
    from eachlabs import scene_build
    from eachlabs.things import after_step as things_after, ids as thing_ids, registry

    scene = bpy.data.scenes.new("eachlabs_things")
    build = scene_build.SceneBuild(scene, "things-run")
    try:
        result = _step(build, THINGS_WALL_CODE)
        check("things: the wall, merlons, hall and clock are built", result.get("ok"), str(result)[:300])
        objs = build._objects()
        entries = {e["name"]: e for e in registry.inventory(objs)}
        wall = entries.get("Larger village stone perimeter wall", {})
        check("things: the wall is a fence by its kind and labels", wall.get("kind") == "fence"
              and thing_ids.matches(wall, "fence") and thing_ids.matches(wall, "boundary") and wall.get("parts") == 4,
              str(wall))
        check("things: the clock's parent thing is the town hall",
              entries.get("analog clock", {}).get("parent") == "town hall", str(entries.get("analog clock")))
        check("things: the loose crate is reported as an orphan", result.get("orphans") == ["loose crate"]
              and "attach(" in (result.get("orphans_note") or ""), str(result.get("orphans")))
        merlon = scene.objects["perimeter merlon 2"]
        check("things: a merlon carries its wall's thing id",
              registry.thing_of(merlon) == registry.thing_of(scene.objects["Larger village stone perimeter wall"]))
        names = sorted(o.name for o in registry.subtree_objects(objs, ["perimeter merlon 0"]))
        check("things: a selected merlon means the whole fence", len(names) == 5
              and "Larger village stone perimeter wall" in names, str(names))
        _step(build, 'g = bpy.data.objects.new("village gate", bpy.data.meshes.new("g"))\n'
                     'scene.collection.objects.link(g)\nthing(g, "gate", "entrance")\n')
        build.owned = [("gate", "fence")]  # the plan: the gate belongs to the fence
        things_after.end_of_stage(build, build._collection(), build.tag)
        gate = {e["name"]: e for e in registry.inventory(build._objects())}.get("village gate", {})
        check("things: a gate the plan puts in the fence becomes the fence's child thing",
              gate.get("parent") == "Larger village stone perimeter wall", str(gate))
        gone_ids = {registry.thing_of(scene.objects[n]) for n in ("Larger village stone perimeter wall", "village gate")}
        gone_colls = [c.name for c in bpy.data.collections if c.get(thing_ids.THING) in gone_ids]
        removed = _step(build, 'bpy.data.objects.remove(bpy.data.objects["Larger village stone perimeter wall"])\n'
                               'bpy.data.objects.remove(bpy.data.objects["town hall"])\n')
        left = sorted(o.name for o in scene.objects)
        check("things: removing the wall and the hall takes the merlons, the gate and the clock along",
              not any(n.startswith("perimeter merlon") or n in ("analog clock", "village gate") for n in left)
              and sorted(removed.get("removed_with") or []) == sorted(["analog clock", "village gate"] + [
                  "perimeter merlon %d" % i for i in range(4)]), "%s %s" % (left, removed.get("removed_with")))
        things_after.end_of_stage(build, build._collection(), build.tag)
        check("things: the removed fence's collection goes with its gate's, nested inside it",
              len(gone_colls) == 2 and not any(n in bpy.data.collections for n in gone_colls), str(gone_colls))
        copied = _step(build, 'tree = bpy.data.meshes.new("t")\no = bpy.data.objects.new("pine", tree)\n'
                              'scene.collection.objects.link(o)\nthing(o, "pine tree")\n'
                              'for i in range(3):\n    copy_thing(o, (i * 3, 10, 0))\n')
        pines = [o for o in scene.objects if o.name.startswith("pine")]
        check("things: copies are things of their own", copied.get("ok") and len(pines) == 4
              and len({registry.thing_of(o) for o in pines}) == 4, str([registry.thing_of(o) for o in pines]))
        build.end_stage("layout")
        crate = scene.objects["loose crate"]
        check("things: an orphan left at the end of a stage becomes a thing of its own", registry.is_root(crate))
        top = build._collection()
        colls = {c.name for c in top.children_recursive}
        check("things: every thing has its collection", {"loose crate", "pine"} <= colls, str(sorted(colls)))
        renamed = things_after.finish(build)
        colls = {c.name for c in top.children_recursive}
        check("things: names follow one scheme, collections with them; copies go by their kind",
              renamed > 0 and "Pine tree 1" in scene.objects and "Pine tree 4" in scene.objects
              and not any(o.name.startswith("Pine ") and not o.name.startswith("Pine tree") for o in scene.objects)
              and "Loose crate" in scene.objects and {"Pine tree 1", "Loose crate"} <= colls,
              "%s %s" % (sorted(o.name for o in scene.objects), sorted(colls)))
        _step(build, 'for n in ("House 2", "House 1", "house"):\n'
                     '    o = bpy.data.objects.new(n, bpy.data.meshes.new(n))\n'
                     '    scene.collection.objects.link(o)\n    thing(o, "house")\n')
        two, one = scene.objects.get("House 2"), scene.objects.get("House 1")
        things_after.finish(build)
        check("things: a thing already numbered keeps its number; a new one takes the next free",
              two is not None and one is not None and two.name == "House 2" and one.name == "House 1"
              and "House 3" in scene.objects, str(sorted(o.name for o in scene.objects if "ouse" in o.name)))
        _step(build, 'camp = bpy.data.objects.new("camp", None)\nscene.collection.objects.link(camp)\n'
                     'thing(camp, "camp")\nfire = bpy.data.objects.new("campfire", None)\n'
                     'scene.collection.objects.link(fire)\nthing(fire, "campfire", parent=camp)\n'
                     'for i in range(3):\n    s = bpy.data.objects.new("stone", bpy.data.meshes.new("s"))\n'
                     '    scene.collection.objects.link(s)\n    s.parent = fire\n')
        things_after.finish(build)
        again = things_after.finish(build)
        stones = sorted(o.name for o in scene.objects if "Stone" in o.name)
        check("things: naming twice changes nothing; a child thing names its parent once; repeated parts are "
              "numbered", again == 0 and "Campfire (Camp)" in scene.objects
              and stones == ["Campfire / Stone 1", "Campfire / Stone 2", "Campfire / Stone 3"],
              "%s %s %s" % (again, stones, sorted(o.name for o in scene.objects if "amp" in o.name)))
        legacy = bpy.data.objects.new("old shed", None)
        scene.collection.objects.link(legacy)
        build.adopt(legacy)
        part = bpy.data.objects.new("old shed roof", bpy.data.meshes.new("r"))
        scene.collection.objects.link(part)
        build.adopt(part)
        part.parent = legacy
        for key in (thing_ids.THING, thing_ids.KIND, thing_ids.LABELS, thing_ids.PARENT):
            for obj in (legacy, part):
                if key in obj:
                    del obj[key]
        registry.migrate(build._objects(), lambda o: bool(o.get("zone")))
        check("things: a scene from before things gets one thing per top object, parts by hierarchy",
              registry.is_root(legacy) and registry.thing_of(part) == registry.thing_of(legacy))
        check("things: a step cannot name an empty kind",
              "ValueError" in (_step(build, 'thing(bpy.data.objects["Pine tree 1"], "")\n').get("error") or ""))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


FENCE_CODE = BOX_CODE + """# A stone fence: its empty holds nothing, its wall segments are objects of their own
box("Fence ground", (60, 60, 0.05), (0, 0, -0.05))
fence = bpy.data.objects.new("Stone fence", None)
scene.collection.objects.link(fence)
box("Boundary masonry north", (30, 0.5, 2), (0, 0, 0))
box("Boundary masonry east", (0.5, 30, 2), (15, 0, 0))
house = box("Village house", (6, 6, 5), (0, 0, 0))
leaves = box("Village house ivy leaf", (0.3, 0.05, 0.3), (0, -3.15, 2.5))
attach(leaves, house)
"""


def test_empty_group_edit():
    """An edit that names an empty holding nothing becomes a normal change of the scene: the empty is listed,
    the wall through the house is listed, and a leaf floating off its wall is listed with its gap."""
    import json

    from eachlabs import chat_loop, chat_run, scene_build

    scene = bpy.data.scenes.new("eachlabs_fence")
    build = scene_build.SceneBuild(scene, "fence-run")
    try:
        check("empty group: the scene is built", _step(build, FENCE_CODE).get("ok"))
        seen = build.read_scene()
        check("empty group: the fence empty that holds nothing is listed",
              seen.get("empty_groups") == ["Stone fence"], json.dumps(seen.get("empty_groups")))
        check("empty group: the wall segment through the house is listed as crossing it",
              any({c["thing"], c["crosses"]} == {"Boundary masonry north", "Village house"}
                  for c in seen.get("crossing") or []), json.dumps(seen.get("crossing")))
        check("empty group: the leaf 15 cm off the house wall is listed as floating off it",
              any(g.get("thing") == "Village house" for g in seen.get("gaps") or []), json.dumps(seen.get("gaps")))
        check("empty group: both go to the fix stage", {"empty_groups", "crossing"} <= set(
            chat_loop.placement_problems(seen)), json.dumps(sorted(chat_loop.placement_problems(seen))))
        run = types.SimpleNamespace(build=build, targets=["Stone fence"])
        check("empty group: an edit of the empty alone is found hollow", chat_run._hollow(run))
        run.targets = ["Stone fence", "Village house"]
        check("empty group: an edit that also names the house is not hollow", not chat_run._hollow(run))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


MERLON_CODE = BOX_CODE + """# A wall with merlons on top built as objects of their own, and a bench beside it
box("Merlon ground", (60, 60, 0.05), (0, 0, -0.05))
box("Perimeter wall", (20, 0.6, 2.4), (0, 0, 0))
for i in range(5):
    box("Perimeter merlon.%03d" % i, (0.5, 0.6, 0.5), (-8 + 4 * i, 0, 2.4))
box("Bench", (2, 0.6, 0.5), (0, 3, 0))
"""


def test_resting_on_removed():
    """Before an edit, the things resting on its targets are known: the merlons on the wall, not the bench beside
    it, so removing the wall can take them along."""
    import json

    from eachlabs import chat_run, scene_build

    scene = bpy.data.scenes.new("eachlabs_merlons")
    build = scene_build.SceneBuild(scene, "merlon-run")
    try:
        check("resting: the wall is built", _step(build, MERLON_CODE).get("ok"))
        resting = chat_run._resting_on(types.SimpleNamespace(build=build), ["Perimeter wall"])
        check("resting: every merlon rests on the wall and the bench does not",
              sorted(resting) == ["Perimeter merlon.%03d" % i for i in range(5)]
              and set(resting.values()) == {"Perimeter wall"}, json.dumps(resting))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


HOLDER_CODE = """# A workbench with a hammer far from it, and a vase with flowers in it
import bmesh
def box(name, size, at):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=at, verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    return ob
box("Workbench", (2, 0.8, 0.9), (0, 0, 0.45))
box("Tools hammer", (0.3, 0.05, 0.05), (6, 0, 0.03))
box("Vase", (0.2, 0.2, 0.4), (3, 0, 0.2))
box("Flowers", (0.2, 0.2, 0.3), (3, 0, 0.5))
box("Stall", (2, 1, 0.9), (-4, 0, 0.45))
box("Fish buried", (0.5, 0.2, 0.1), (-4, 0, 0.6))
box("Bread", (0.4, 0.2, 0.1), (-4, 0, 0.95))
"""


def test_contents_on_holder():
    """A planned thing with a holder counts only when it stands on or in it."""
    from eachlabs import scene_build
    from eachlabs.chat import plan_flow

    scene = bpy.data.scenes.new("eachlabs_holder")
    build = scene_build.SceneBuild(scene, "holder-run")
    try:
        check("holder: the scene is built", _step(build, HOLDER_CODE).get("ok"))
        check("holder: tools lying away from the workbench are not on it",
              not plan_flow._on_holder(build, "tools", "workbench"))
        check("holder: flowers in the vase are in it", plan_flow._on_holder(build, "flowers", "vase"))
        check("holder: a holder nobody built does not list the item again",
              plan_flow._on_holder(build, "flowers", "pantry"))
        check("holder: a thing buried inside the holder's volume is not on it",
              not plan_flow._on_holder(build, "fish", "stall"))
        check("holder: a thing lying on the holder's top is on it", plan_flow._on_holder(build, "bread", "stall"))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)
