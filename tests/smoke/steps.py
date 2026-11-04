"""Model steps run through the tool path: the step runner, edit mode, errors and the helper library."""

import os
import shutil
import sys
import tempfile
import threading
import time

import bpy
import mathutils

from eachlabs import compat, preferences
from tests.smoke.common import WORK, _chat_tree, _step, check


def test_scene_tools():
    """Build a street with model-written steps in a scene that also holds the person's default objects."""
    import json

    from eachlabs import scene_build, scene_tools
    from tests.blender_fakes import CAMERA_CODE, LAYOUT_CODE, LIGHT_CODE, MATERIALS_CODE

    default = bpy.context.scene
    people = list(default.objects)
    scene = bpy.data.scenes.new("eachlabs_street")
    for obj in people:
        scene.collection.objects.link(obj)
    scene.render.fps, scene.render.fps_base = 24, 1.0
    cube = bpy.data.objects["Cube"]
    cube_before = (cube.name, tuple(round(v, 4) for v in cube.location), tuple(cube.scale),
                   [s.material for s in cube.material_slots])
    collections_before = len([c for c in bpy.data.collections if not c.get("eachlabs_thing")])

    own_world = bpy.data.worlds.new("My world")
    if own_world.node_tree is None:
        own_world.use_nodes = True
    tree = own_world.node_tree
    rgb = tree.nodes.new("ShaderNodeRGB")
    background = next(n for n in tree.nodes if n.type == "BACKGROUND")
    tree.links.new(rgb.outputs[0], background.inputs["Color"])
    scene.world = own_world

    def world_state(world):
        t = world.node_tree
        return (len(t.nodes), len(t.links), tuple(world.color), sorted(world.keys()))
    own_before = world_state(own_world)

    build = scene_build.SceneBuild(scene, "smoke")
    check("scene tools: collection_name before the first object is None and makes nothing",
          build.collection_name is None and len(bpy.data.collections) == collections_before)
    first = build.execute("read_scene", {})
    text = json.dumps(first)
    check("scene tools: read_scene before building counts the person's objects and names none of them",
          first["other_objects"] == len(people) and first["objects"] == [] and first["world"]["yours"] is False
          and not any(name in text for name in [o.name for o in people] + [own_world.name]), text)
    layout = _step(build, LAYOUT_CODE)
    mark = build.mark()
    materials = _step(build, MATERIALS_CODE)
    light = _step(build, LIGHT_CODE)
    since = build.created_since(mark)
    camera = _step(build, CAMERA_CODE)
    build.end_stage("layout")
    names = [o["name"] for o in layout.get("summary", {}).get("new_objects", [])]
    check("scene tools: every step ran", all(r.get("ok") for r in (layout, materials, light, camera)),
          str([r.get("error", "")[-200:] for r in (layout, materials, light, camera)]))
    check("scene tools: the layout step reports its three meshes", names == ["Ground", "Building A", "Building B"],
          str(names))
    check("scene tools: one new collection, with one collection per thing in it",
          len([c for c in bpy.data.collections if not c.get("eachlabs_thing")]) == collections_before + 1
          and build.collection_name.startswith("Eachlabs scene")
          and build.collection_name in [c.name for c in scene.collection.children], str(build.collection_name))
    check("scene tools: created_since lists what the light step made", sorted(since) == ["Street lamp", "Sun"],
          str(since))
    created = list(bpy.data.collections[build.collection_name].all_objects)
    check("scene tools: every created object is tagged and in the chat collection", len(created) == 7
          and all(o.get(scene_build.ID) and o.get(scene_build.RUN) == "smoke" for o in created)
          and all(len(o.users_collection) == 1 and o.users_collection[0] in _chat_tree(build) for o in created),
          str(sorted(o.name for o in created)))
    check("scene tools: the scene camera is the step's camera", scene.camera is not None
          and scene.camera.name == "Street camera" and scene.camera.get(scene_build.RUN) == "smoke")
    check("scene tools: frame range is 1 to 120 at 24 fps", (scene.frame_start, scene.frame_end) == (1, 120),
          str((scene.frame_start, scene.frame_end)))
    keys = sorted({round(kp.co[0]) for fc in compat.object_fcurves(scene.camera) for kp in fc.keyframe_points})
    check("scene tools: camera keyed at 1 and 120", keys == [1, 120], str(keys))
    check("scene tools: camera_path reads the scene camera's keys",
          build.camera_path() == [(-20.0, -14.0, 3.0), (20.0, -14.0, 3.0)]
          and build.camera_look_at() == (0.0, 6.0, 6.0), "%s %s" % (build.camera_path(), build.camera_look_at()))
    check("scene tools: the world the step made is the scene's, the person's world is untouched",
          scene.world.name == "Evening sky" and scene.world.get(scene_build.RUN) == "smoke"
          and own_world.name in bpy.data.worlds and world_state(own_world) == own_before
          and own_world.get(scene_build.RUN) is None, "%s %s %s" % (scene.world.name, world_state(own_world), own_before))
    saved = os.path.join(tempfile.mkdtemp(prefix="eachlabs-world-"), "saved.blend")
    bpy.ops.wm.save_as_mainfile(filepath=saved, copy=True)
    with bpy.data.libraries.load(saved) as (data_from, _data_to):
        saved_worlds = list(data_from.worlds)
    shutil.rmtree(os.path.dirname(saved), ignore_errors=True)
    check("scene tools: the replaced world gets a fake user and is still in the saved file",
          own_world.use_fake_user and own_world.name in saved_worlds, "%s %s" % (own_world.use_fake_user, saved_worlds))

    state = build.execute("read_scene", {})
    by_name = {o["name"]: o for o in state["objects"]}
    check("scene tools: read_scene lists only this run's objects, with sizes and materials",
          sorted(by_name) == ["Building A", "Building B", "Camera target", "Ground", "Street camera"]
          and by_name["Building B"]["dimensions"] == [7.0, 6.0, 18.0]
          and by_name["Building B"]["materials"] == ["Building B material"]
          and state["other_objects"] == len(people), json.dumps(state)[:400])
    check("scene tools: read_scene lists lights, world and camera",
          sorted(l["name"] for l in state["lights"]) == ["Street lamp", "Sun"]
          and state["world"]["yours"] and state["world"]["strength"] == 0.4
          and state["camera"]["name"] == "Street camera" and state["camera"]["yours"]
          and state["camera"]["target"]["name"] == "Camera target" and state["camera"]["location_keys"] == [1, 120]
          and state["frame_range"] == [1, 120] and state["fps"] == 24, json.dumps(state)[:400])
    check("scene tools: read_scene is JSON", isinstance(json.dumps(state), str))
    targets = sorted(o.name for o in build.frame_targets())
    check("scene tools: framing uses the buildings, not the flat ground", targets == ["Building A", "Building B"],
          str(targets))

    scene.frame_current = 37
    view = build.execute("camera_view", {})
    frames = view.get("frames", [])
    seen = [{v["name"]: v for v in f["visible"]} for f in frames]
    check("scene tools: camera_view reads the first and the last frame and puts the frame back",
          view.get("camera") == "Street camera" and [f["frame"] for f in frames] == [1, 120]
          and scene.frame_current == 37, json.dumps(view)[:300])
    check("scene tools: camera_view sees both buildings at both ends with a sensible share",
          len(seen) == 2 and all(0 < s.get(name, {}).get("coverage_pct", 0) < 100 for s in seen
                                 for name in ("Building A", "Building B"))
          and all(0 <= f["empty_pct"] < 100 for f in frames), json.dumps(view)[:500])
    check("scene tools: every object in view says whether the frame cuts it off",
          all(isinstance(v["cut_off"], bool) for s in seen for v in s.values()), json.dumps(view)[:500])
    behind = _step(build, "# A crate behind the camera\nmesh = bpy.data.meshes.new('Crate')\n"
                          "bm = bmesh.new()\nbmesh.ops.create_cube(bm, size=1.0)\nbm.to_mesh(mesh)\nbm.free()\n"
                          "crate = bpy.data.objects.new('Crate', mesh)\ncrate.location = (-35, -29, 1)\n"
                          "scene.collection.objects.link(crate)")
    view = build.execute("camera_view", {})
    check("scene tools: an object behind the camera is listed as behind it", behind.get("ok")
          and "Crate" in view["frames"][0]["behind_camera"], json.dumps(view["frames"][0])[:300])

    moved = _step(build, '# Nudge the cube\nbpy.data.objects["Cube"].location.x += 1.5')
    check("scene tools: a step that moves the person's Cube is told how many objects it changed, not which",
          moved.get("ok") and moved["summary"]["touched_other"] == 1
          and moved.get("note") == "Your step changed 1 object you did not create; do not change them."
          and "Cube" not in json.dumps(moved) and scene_build.RUN not in cube.keys(), str(moved)[:300])
    cube.location = cube_before[1]
    started = time.monotonic()
    stopped = build.execute("run_python", {"code": "# Spin\nwhile True:\n    pass"}, 1.0)
    check("scene tools: execute passes the step time limit to the runner", not stopped.get("ok")
          and "longer than 1 s" in stopped.get("error", "") and time.monotonic() - started < 4,
          stopped.get("error", "")[-120:])

    tower = bpy.data.objects["Building B"]
    bpy.data.objects.remove(tower)
    listed = [o["name"] for o in build.execute("read_scene", {})["objects"]]
    gone = _step(build, '# Paint the tower\nbpy.data.objects["Building B"].data.materials.clear()')
    check("scene tools: an object the person deleted is gone from read_scene, and a step that uses it gets "
          "the error", "Building B" not in listed and not gone.get("ok")
          and "KeyError" in gone.get("error", ""), str(gone)[:300])

    painted = _step(build, '# A material\nm = bpy.data.materials.new("Chat brick")\n'
                           'bpy.data.objects["Building A"].data.materials.append(m)')
    told = build.execute("chat_context", {})["objects"]
    check("scene tools: Code check is told the chat's own materials and objects by kind, not the person's",
          painted.get("ok") and {"kind": "material", "name": "Chat brick"} in told
          and {"kind": "object", "name": "Building A"} in told
          and not any(e["name"] in ("Cube", "Material") for e in told), str(told)[:300])
    theirs = bpy.data.materials.new("Their paint")
    mine = bpy.data.objects["Building A"]
    forged = _step(build, '# Claim them\nbpy.data.materials["Their paint"]["%s"] = "%s"\n'
                          'c = bpy.data.objects["Cube"]\nc["%s"] = "%s"\nc["%s"] = "%s"'
                   % (scene_build.RUN, build.run_id, scene_build.RUN, build.run_id, scene_build.ID, mine[scene_build.ID]))
    told = build.execute("chat_context", {})["objects"]
    listed = [o["name"] for o in build.execute("read_scene", {})["objects"]]
    check("scene tools: copying the chat's tags onto the person's material or object does not make them the chat's",
          not any(e["name"] in ("Their paint", "Cube") for e in told) and "Cube" not in listed,
          "%s %s %s" % (forged.get("ok"), str(told)[:150], listed[:8]))
    cube_obj = bpy.data.objects["Cube"]
    for key in (scene_build.RUN, scene_build.ID):
        if key in cube_obj.keys():
            del cube_obj[key]
    bpy.data.materials.remove(theirs)

    original = bpy.data.objects["Building A"]
    copy = original.copy()
    scene.collection.objects.link(copy)
    listed = [o["name"] for o in build.execute("read_scene", {})["objects"]]
    check("scene tools: read_scene lists an object the person copied once", listed.count("Building A") == 1
          and copy.name not in listed, str(listed))
    bpy.data.objects.remove(copy)
    original.name = "My building"
    listed = [o["name"] for o in build.execute("read_scene", {})["objects"]]
    check("scene tools: a renamed object is listed by its new name", "My building" in listed, str(listed))

    run_coll = bpy.data.collections[build.collection_name]
    parent = bpy.data.collections.new("My set")
    scene.collection.children.link(parent)
    scene.collection.children.unlink(run_coll)
    parent.children.link(run_coll)
    _step(build, "# One more box\nbpy.data.objects.new('Marker', None)")
    check("scene tools: a run collection the person moved stays where they put it",
          run_coll.name not in scene.collection.children and run_coll.name in parent.children
          and build.collection_name == run_coll.name and "Marker" in run_coll.objects,
          str([c.name for c in scene.collection.children]))
    bad = None
    try:
        build.execute("run_python", {})
    except scene_tools.ToolArgError as exc:
        bad = str(exc)
    check("scene tools: execute validates arguments", bad and "code is required" in bad, str(bad))
    cube_after = (cube.name, tuple(round(v, 4) for v in cube.location), tuple(cube.scale),
                  [s.material for s in cube.material_slots])
    check("scene tools: the person's cube is back as it was", cube.name in scene.objects and cube_after == cube_before,
          "%s vs %s" % (cube_after, cube_before))

    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 320, 180, 100
    scene.frame_set(60)
    path = os.path.join(WORK, "street.png")
    scene.render.filepath = path
    compat.set_image_output(scene.render.image_settings)
    bpy.ops.render.render(write_still=True, scene=scene.name)
    image = bpy.data.images.load(path)
    pixels = list(image.pixels)
    corner = pixels[0:3]
    differing = sum(1 for i in range(0, len(pixels), 4)
                    if max(abs(pixels[i + c] - corner[c]) for c in range(3)) > 0.02)
    check("scene tools: Workbench frame of the street is not blank", differing > len(pixels) // 4 * 0.1,
          "%d of %d pixels differ from the corner" % (differing, len(pixels) // 4))
    bpy.data.images.remove(image)
    for obj in [o for o in bpy.data.objects if o.get(scene_build.RUN) == "smoke"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.scenes.remove(scene)
    bpy.data.collections.remove(parent)
    bpy.data.collections.remove(run_coll)
    bpy.data.worlds.remove(own_world)
    test_edit_mode()


def test_edit_mode():
    """A step while the person is in Edit Mode is answered "busy" and changes nothing."""
    from eachlabs import scene_build

    scene = bpy.context.scene
    cube = bpy.data.objects["Cube"]
    bpy.context.view_layer.objects.active = cube
    build = scene_build.SceneBuild(scene, "smoke-edit")
    objects, collections = len(bpy.data.objects), len(bpy.data.collections)
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        entered = cube.mode == "EDIT"
        result = _step(build, "# A box\nbpy.data.objects.new('Box', None)")
        read = build.execute("read_scene", {})
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    check("scene tools: in Edit Mode a step answers busy and touches nothing",
          entered and not result.get("ok") and "Blender is busy in edit mode" in result.get("error", "")
          and len(bpy.data.objects) == objects and len(bpy.data.collections) == collections
          and read["objects"] == [], str(result))


def test_step_left_in_edit_mode():
    """A step that leaves Blender in Edit Mode is put back in Object Mode, its mesh edit kept, and the model told."""
    from eachlabs import scene_build

    scene = bpy.context.scene
    build = scene_build.SceneBuild(scene, "smoke-left-edit")
    code = ("# A box left in Edit Mode\nimport bmesh\nmesh = bpy.data.meshes.new('Left')\nbm = bmesh.new()\n"
            "bmesh.ops.create_cube(bm, size=1)\nbm.to_mesh(mesh)\nobj = bpy.data.objects.new('Left', mesh)\n"
            "bpy.context.collection.objects.link(obj)\nbpy.context.view_layer.objects.active = obj\n"
            "bpy.ops.object.mode_set(mode='EDIT')\n")
    first = _step(build, code)
    second = _step(build, "# Another box\nbpy.data.objects.new('Next', None)")
    left = bpy.data.objects.get("Left")
    check("scene tools: a step left in Edit Mode is put back in Object Mode and the next step runs",
          first.get("ok") and "Object Mode" in first.get("mode", "") and second.get("ok")
          and left is not None and left.mode == "OBJECT" and len(left.data.vertices) == 8,
          "%s %s" % (first, second))
    for name in ("Left", "Next"):
        if bpy.data.objects.get(name) is not None:
            bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    bpy.context.view_layer.objects.active = bpy.data.objects.get("Cube")


def test_asked_colour():
    """read_scene names a thing whose biggest surfaces are not the colour the request asked for, until they are."""
    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_colour")
    build = scene_build.SceneBuild(scene, "colour-run")
    build.asked_colours = {"sofa": "#b01818"}
    code = ("import bmesh\nmesh = bpy.data.meshes.new('Sofa')\nbm = bmesh.new()\n"
            "bmesh.ops.create_cube(bm, size=1)\nbm.to_mesh(mesh)\nsofa = bpy.data.objects.new('Sofa', mesh)\n"
            "scene.collection.objects.link(sofa)\nmat = bpy.data.materials.new('Sofa cloth')\n"
            "mat.diffuse_color = (0.2, 0.1, 0.05, 1)\nmesh.materials.append(mat)\nthing(sofa, 'sofa', '')\n")
    try:
        _step(build, code)
        first = build.execute("read_scene", {})
        recolour = ("mat = bpy.data.materials['Sofa cloth']\nmat.diffuse_color = (0.43, 0.01, 0.01, 1)\n"
                    "if mat.use_nodes:\n"
                    "    mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = "
                    "(0.43, 0.01, 0.01, 1)\n")
        if bpy.data.materials["Sofa cloth"].use_nodes:  # Blender 5: the node colour is the one that renders
            bpy.data.materials["Sofa cloth"].node_tree.nodes["Principled BSDF"].inputs["Base Color"]\
                .default_value = (0.2, 0.1, 0.05, 1)
            first = build.execute("read_scene", {})
        _step(build, recolour)
        second = build.execute("read_scene", {})
        off = first.get("colour_off") or []
        check("colour: a brown sofa asked to be red is listed, and not once it is red",
              [e.get("thing") for e in off] == ["Sofa"] and off[0]["asked"] == "#b01818"
              and not second.get("colour_off"), "%s / %s" % (off, second.get("colour_off")))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


def test_helper_library():
    """A stored helper the step calls by name is defined for it; one the filter refuses never runs."""
    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_library_test")
    build = scene_build.SceneBuild(scene, "library-run")
    good = {"name": "lib_crate", "args": "name", "description": "a crate", "hash": "a", "source": (
        "def lib_crate(name):\n    m = bpy.data.meshes.new(name)\n    o = bpy.data.objects.new(name, m)\n"
        "    scene.collection.objects.link(o)\n    return o")}
    bad = {"name": "lib_leak", "args": "", "description": "leak", "hash": "b",
           "source": "def lib_leak():\n    f = open('/etc/hosts')\n    return f.read()"}
    build.library = [good, bad]
    try:
        result = _step(build, 'lib_crate("Library crate")\n')
        check("library: a stored helper the step calls is defined and runs",
              result.get("ok") and scene.objects.get("Library crate") is not None, str(result)[:200])
        result = _step(build, 'rng = random.Random(7)\nvalues = [rng.uniform(0, 1) for i in range(3)]\n'
                              'assert random.Random(7).uniform(0, 1) == values[0]\n')
        check("step namespace: random.Random(seed) gives a seeded generator", result.get("ok"), str(result)[:200])
        result = _step(build, 'lib_leak()\n')
        check("library: a helper the filter refuses is not defined", not result.get("ok")
              and "lib_leak" in str(result.get("error", "")), str(result)[:200])
    finally:
        bpy.data.scenes.remove(scene)


# Steps that write mesh data the filter allows but Blender cannot evaluate: each one crashed Blender 4.2 and 5.2
# on the next view-layer update when nothing repaired it.
BROKEN_MESH_STEPS = (
    ("a face pointing at a missing vertex",
     'm = bpy.data.meshes.new("Broken face")\n'
     'm.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 9)])\n'
     'o = bpy.data.objects.new("Broken face", m)\n'
     'o.modifiers.new("Bevel", "BEVEL")\n'
     'scene.collection.objects.link(o)\n'),
    ("faces added without their corners",
     'm = bpy.data.meshes.new("Broken corners")\n'
     'm.vertices.add(4)\n'
     'm.vertices.foreach_set("co", [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0])\n'
     'm.loops.add(4)\n'
     'm.loops.foreach_set("vertex_index", [0, 1, 2, 3])\n'
     'm.polygons.add(3)\n'
     'o = bpy.data.objects.new("Broken corners", m)\n'
     'scene.collection.objects.link(o)\n'),
    ("a step that fails after writing broken faces",
     'm = bpy.data.meshes.new("Broken then failed")\n'
     'm.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 400000)])\n'
     'o = bpy.data.objects.new("Broken then failed", m)\n'
     'scene.collection.objects.link(o)\n'
     'raise ValueError("stopped half way")\n'),
)


def test_broken_mesh_steps():
    """A step that leaves broken mesh data has it repaired before Blender evaluates it, and the model is told."""
    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_broken")
    build = scene_build.SceneBuild(scene, "broken-run")
    person = bpy.data.meshes.new("Person mesh")
    person.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    try:
        for label, code in BROKEN_MESH_STEPS:
            result = _step(build, code)
            name = code.split('"')[1]
            check("broken mesh: %s is repaired and named to the model" % label,
                  name in (result.get("repaired_meshes") or []) and "repair_note" in result, str(result)[:300])
            for layer in scene.view_layers:  # what crashed before the repair
                layer.update()
        check("broken mesh: Blender evaluates the scene after every broken step", True)
        clean = _step(build, 'm = bpy.data.meshes.new("Clean")\n'
                             'm.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])\n'
                             'scene.collection.objects.link(bpy.data.objects.new("Clean", m))\n')
        check("broken mesh: a valid step reports no repair", clean.get("ok") and "repaired_meshes" not in clean,
              str(clean)[:300])
        check("broken mesh: a mesh of the person's the step did not touch keeps its data",
              len(person.polygons) == 1 and len(person.vertices) == 3)
    finally:
        bpy.data.scenes.remove(scene)
        bpy.data.meshes.remove(person)


PARENT_STEP = (
    'root = bpy.data.objects.new("Camp", None)\n'
    'scene.collection.objects.link(root)\n'
    'root.location = (-28, -16, 0)\n'
    'mesh = bpy.data.meshes.new("Camp tent")\n'
    'mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (0, 1, 0), (0, 0, 2)], [], [(0, 1, 2), (0, 1, 3), (1, 2, 3), (2, 0, 3)])\n'
    'tent = bpy.data.objects.new("Camp tent", mesh)\n'
    'scene.collection.objects.link(tent)\n'
    'tent.location = (-25, -14, 0)\n'
)


def test_attach_parenting():
    """A part parented to a root made in the same step keeps its world place with attach(); the matrix_world
    pattern that doubles the root's offset is refused, with the helper named."""
    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_attach")
    build = scene_build.SceneBuild(scene, "attach-run")
    try:
        # The cause, outside the add-on: a fresh root has no world matrix yet, so its inverse is the identity.
        root = bpy.data.objects.new("Raw root", None)
        scene.collection.objects.link(root)
        root.location = (-28, -16, 0)
        part = bpy.data.objects.new("Raw part", None)
        scene.collection.objects.link(part)
        part.location = (-25, -14, 0)
        part.parent = root
        part.matrix_parent_inverse = root.matrix_world.inverted()
        scene.view_layers[0].update()
        check("attach: the raw matrix_world pattern puts a fresh root's part at twice its offset",
              (part.matrix_world.translation - mathutils.Vector((-53, -30, 0))).length < 1e-3,
              str(tuple(part.matrix_world.translation)))
        bpy.data.objects.remove(part)
        bpy.data.objects.remove(root)

        refused = _step(build, PARENT_STEP + 'tent.parent = root\ntent.matrix_parent_inverse = root.matrix_world.inverted()\n')
        check("attach: the doubled-offset pattern is refused and the refusal names attach()",
              not refused.get("ok") and "attach(part, root)" in str(refused.get("error")), str(refused)[:300])
        result = _step(build, PARENT_STEP + 'attach(tent, root)\n'
                       'outer = bpy.data.objects.new("Camp site", None)\nscene.collection.objects.link(outer)\n'
                       'outer.location = (5, 0, 0)\nattach(root, outer)\n')
        scene.view_layers[0].update()
        tent = scene.objects.get("Camp tent")
        check("attach: a part attached to a fresh root stays where it was built",
              result.get("ok") and tent is not None and tent.parent is not None
              and (tent.matrix_world.translation - mathutils.Vector((-25, -14, 0))).length < 1e-3,
              "%s %s" % (str(result)[:200], tuple(tent.matrix_world.translation) if tent else None))
        placed = {p.get("name"): p for p in result.get("summary", {}).get("placed", []) if isinstance(p, dict)}
        site = placed.get("Camp site", {})
        check("attach: the step result places the new thing where its geometry is, not at its origin",
              site.get("centre") == [-25.0, -14.0, 1.0] and site.get("size") == [2.0, 2.0, 2.0], str(placed))
        root = scene.objects.get("Camp")
        check("attach: attaching a root to another fresh root keeps both in place",
              root is not None and (root.matrix_world.translation - mathutils.Vector((-28, -16, 0))).length < 1e-3,
              str(tuple(root.matrix_world.translation)) if root else "no root")
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


THREE_BLOCKS = """
mat = bpy.data.materials.new("eachlabs_red")
holder = bpy.data.collections.new("eachlabs_holder")
bpy.context.scene.collection.children.link(holder)
for i in range(3):
    mesh = bpy.data.meshes.new("eachlabs_block")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(mat)
    obj = bpy.data.objects.new("eachlabs_block_%d" % i, mesh)
    obj.location = (i * 2.0, 0, 0)
    if i == 0:
        bpy.context.scene.collection.objects.link(obj)
    elif i == 1:
        holder.objects.link(obj)
print("built", i + 1)
"""

DEEP_ERROR = """
def down(n):
    if n == 0:
        raise ValueError("deep")
    down(n - 1)
down(40)
"""

SWALLOWS_TIMEOUT = """
while True:
    try:
        while True:
            pass
    except Exception:
        pass
"""


WORLD_DAWN_CODE = """# A dawn sky
world = bpy.data.worlds.new("Dawn sky")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.9, 0.6, 0.4, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
scene.world = world
"""

WORLD_NIGHT_CODE = """# A stall, and the sky turned to night on the way
stall = bpy.data.objects.new("Stall", None)
scene.collection.objects.link(stall)
scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.02
night = bpy.data.worlds.new("Night sky")
scene.world = night
"""


def test_world_kept():
    """A follow-up that is not about the light puts the world back after a step changed it, and says so."""
    from eachlabs import edit_guard, scene_build

    scene = bpy.data.scenes.new("eachlabs_world_kept")
    build = scene_build.SceneBuild(scene, "world-run")
    try:
        check("world kept: the dawn sky is built", _step(build, WORLD_DAWN_CODE).get("ok"))

        build.world_guard = edit_guard.WorldGuard(build)
        result = _step(build, WORLD_NIGHT_CODE)
        check("world kept: the step's new thing stays", "Stall" in scene.objects, str(result))
        strength = scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value
        check("world kept: the dawn sky is the scene's world again, at its strength",
              scene.world.name == "Dawn sky" and abs(strength - 1.0) < 1e-4, "%s %s" % (scene.world.name, strength))
        check("world kept: the step's result says the world was put back and why",
              edit_guard.WorldGuard.PUT_BACK in (result.get("put_back") or [])
              and "not about the light" in result.get("note", ""), str(result))
        build.world_guard = None
        _step(build, "scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.5\n")
        check("world kept: without the guard a step may change the world",
              abs(scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value - 0.5) < 1e-4)
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


def test_error_hints():
    """A step that fails on a missing attribute or a missing bmesh key comes back with the answer."""
    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_error_hints")
    build = scene_build.SceneBuild(scene, "hint-run")
    try:
        result = _step(build, "m = mathutils.Matrix.translation_matrix((0, 0, 1))\n")
        check("error hints: a missing attribute lists the close names the type has",
              not result.get("ok") and "Translation" in result.get("hint", ""), str(result.get("hint")))
        result = _step(build, "bm = bmesh.new()\nr = bmesh.ops.create_cube(bm, size=1.0)\nf = r['faces']\nbm.free()\n")
        check("error hints: a create operator's missing faces key says what it returns",
              "link_faces" in result.get("hint", ""), str(result.get("hint")))
    finally:
        bpy.data.scenes.remove(scene)


def test_code_runner():
    """Run model-written code into a build of the default scene, which holds the person's Cube."""
    from eachlabs import code_runner, scene_build

    scene = bpy.context.scene
    cube = bpy.data.objects["Cube"]
    cube_location = tuple(cube.location)
    build = scene_build.SceneBuild(scene, "coderunner01")
    mark = build.mark()
    collections_before = {c.session_uid for c in bpy.data.collections}
    stdout_before = sys.stdout
    try:
        result = code_runner.run(THREE_BLOCKS, build)
        summary = result.get("summary", {})
        names = [o["name"] for o in summary.get("new_objects", [])]
        check("code runner: three meshes and a material", result.get("ok") and len(names) == 3
              and all(o["type"] == "MESH" for o in summary["new_objects"])
              and summary.get("new_materials") == ["eachlabs_red"], str(result)[:300])
        check("code runner: printed output comes back", result.get("output") == "built 3\n", repr(result.get("output")))
        objs = [bpy.data.objects[n] for n in names]
        coll = bpy.data.collections.get(build.collection_name or "")
        check("code runner: every new object is in the chat collection only",
              coll is not None and all(list(o.users_collection) == [coll] for o in objs),
              str([[c.name for c in o.users_collection] for o in objs]))
        check("code runner: new objects carry the run tags",
              all(o.get(scene_build.RUN) == build.run_id and o.get(scene_build.ID) for o in objs)
              and len({o[scene_build.ID] for o in objs}) == 3)
        mat = bpy.data.materials["eachlabs_red"]
        check("code runner: new mesh and material carry the run tag",
              mat.get(scene_build.RUN) == build.run_id
              and all(o.data.get(scene_build.RUN) == build.run_id for o in objs))
        check("code runner: the empty collection the step made is removed",
              "eachlabs_holder" not in bpy.data.collections)
        check("code runner: highlights list the new objects", sorted(build.created_since(mark)) == sorted(names),
              str(build.created_since(mark)))
        check("code runner: nothing of the person's was touched", summary.get("touched_other") == 0)
        check("code runner: the step counts as a change for its stage", build.end_stage("layout"))

        result = code_runner.run('bpy.data.objects["Cube"].location.x += 1.5', build)
        check("code runner: moving the Cube is reported", result.get("ok")
              and result["summary"]["touched_other"] == 1, str(result))
        check("code runner: the Cube is not taken into the build", scene_build.RUN not in cube.keys())
        mesh_before = [tuple(v.co) for v in cube.data.vertices]
        result = code_runner.run('bpy.data.objects["Cube"].data.vertices[0].co.x += 3.0', build)
        check("code runner: an in-place edit of the Cube's mesh is reported", result.get("ok")
              and result["summary"]["touched_other"] == 1, str(result))
        for v, co in zip(cube.data.vertices, mesh_before):
            v.co = co
        mat = cube.material_slots[0].material if cube.material_slots else None
        color_before = tuple(mat.diffuse_color) if mat else None
        step = ('m = bpy.data.objects["Cube"].material_slots[0].material\n'
                'm.diffuse_color = (1.0, 0.0, 0.0, 1.0)\n'
                'n = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None\n'
                'if n:\n    n.inputs["Base Color"].default_value = (1.0, 0.0, 0.0, 1.0)')
        color_node = None
        if mat is not None and mat.node_tree is not None and mat.node_tree.nodes.get("Principled BSDF"):
            color_node = tuple(mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value)
        result = code_runner.run(step, build)
        check("code runner: an in-place edit of the Cube's material is reported", mat is not None
              and result.get("ok") and result["summary"]["touched_other"] == 1, str(result))
        if mat is not None:
            mat.diffuse_color = color_before
            if color_node is not None:
                mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = color_node
        result = code_runner.run('import random\nimport math as m\nfrom math import *\nrandom.seed(3)\n'
                                 'print(hasattr(random, "seed"), hasattr(random, "Random"), round(pi, 2), '
                                 'm.floor(2.5), 0 <= random.uniform(0, 1) <= 1)', build)
        check("code runner: math and random are public-only copies, random with its seeded Random", result.get("ok")
              and result.get("output") == "True True 3.14 2 True\n", str(result))
        copy_code = 'c = bpy.data.objects["%s"].copy()\nbpy.context.scene.collection.objects.link(c)' % names[0]
        result = code_runner.run(copy_code, build)
        copy = bpy.data.objects.get(result["summary"]["new_objects"][0]["name"]) if result.get("ok") else None
        check("code runner: a copy of a run object gets its own id",
              copy is not None and copy[scene_build.ID] != objs[0][scene_build.ID], str(result))

        result = code_runner.run(DEEP_ERROR, build)
        lines = result.get("error", "").splitlines()
        check("code runner: traceback trimmed to the step's last 20 lines",
              not result.get("ok") and 0 < len(lines) <= 20 and lines[-1] == "ValueError: deep"
              and not any("code_runner" in line for line in lines), "\n".join(lines[-3:]))

        result = code_runner.run("import os\nbpy.data.objects.new('eachlabs_never', None)", build)
        check("code runner: a refused step does not run", not result.get("ok")
              and "system-module" in result.get("error", "") and "eachlabs_never" not in bpy.data.objects, str(result))

        started = time.monotonic()
        result = code_runner.run("while True:\n    pass", build)
        took = time.monotonic() - started
        check("code runner: an endless loop stops after 20 s", not result.get("ok") and 19.5 <= took < 25
              and "longer than 20 s" in result.get("error", ""), "%.1f s, %s" % (took, result.get("error", "")[-120:]))
        time.sleep(0.2)
        check("code runner: the time limit's helper thread ends with the step",
              not any(t.name == "eachlabs-step-limit" for t in threading.enumerate()))
        check("code runner: stdout is restored after a stop", sys.stdout is stdout_before)
        started = time.monotonic()
        result = code_runner.run(SWALLOWS_TIMEOUT, build, limit_s=1.0)
        took = time.monotonic() - started
        check("code runner: a step that catches the stop still stops", not result.get("ok") and took < 3
              and "longer than 1 s" in result.get("error", ""), "%.1f s" % took)
        result = code_runner.run(SWALLOWS_TIMEOUT.replace("except Exception:", "except:"), build, limit_s=1.0)
        check("code runner: a bare except, which could keep the stop, is refused", not result.get("ok")
              and "broad-except" in result.get("error", ""), result.get("error", ""))
        check("code runner: no stop is left pending after a timeout", sum(i for i in range(200000)) > 0)

        key = "el-smoke-credential-0123"
        step = 'bpy.data.objects.new("eachlabs_%s" % "{0}", None)\nprint("{0}")\nraise ValueError("{0}")'.format(key)
        checker = code_runner.code_check.check
        code_runner.code_check.check = lambda code: None  # the filter refuses this; the redaction is what is tested
        prefs = preferences.get_preferences()  # None when the add-on is registered from this checkout
        old_key = prefs.api_key if prefs is not None else os.environ.get(preferences.ENV_KEY)
        try:
            if prefs is not None:
                prefs.api_key = key
            else:
                os.environ[preferences.ENV_KEY] = key
            result = code_runner.run(step, build)
        finally:
            if prefs is not None:
                prefs.api_key = old_key
            elif old_key is None:
                os.environ.pop(preferences.ENV_KEY, None)
            else:
                os.environ[preferences.ENV_KEY] = old_key
            code_runner.code_check.check = checker
        check("code runner: the API key is redacted from the summary, output and error",
              key not in repr(result) and "[redacted]" in result["summary"]["new_objects"][0]["name"]
              and "[redacted]" in result.get("output", "") and "ValueError: [redacted]" in result.get("error", ""),
              repr(result)[:300])
        refused = code_runner.run('k = bpy.context.preferences.addons["eachlabs"].preferences.api_key', build)
        check("code runner: reading the add-on's settings is refused", not refused["ok"]
              and "credentials" in refused["error"], refused.get("error", ""))
        result = code_runner.run("x = sum(range(1000))\nprint(x)", build)
        check("code runner: Blender keeps running steps after a stop", result.get("ok")
              and result.get("output") == "499500\n", str(result))
    finally:
        cube.location = cube_location
        for obj in [o for o in bpy.data.objects if o.get(scene_build.RUN) == build.run_id]:
            bpy.data.objects.remove(obj, do_unlink=True)
        for kind in ("meshes", "materials"):
            blocks = getattr(bpy.data, kind)
            for block in [b for b in blocks if b.get(scene_build.RUN) == build.run_id]:
                blocks.remove(block)
        for coll in [c for c in bpy.data.collections if c.session_uid not in collections_before]:
            bpy.data.collections.remove(coll)
