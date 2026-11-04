"""The detail stage."""

import threading
import types

import bpy

from eachlabs import preferences
from tests import blender_fakes
from tests.blender_fakes import code_reply, offline_api, text_reply
from tests.smoke.chat_common import _chat_drive, _tool_contents
from tests.smoke.common import check


DETAIL_LAYOUT = """# A car with its body, and the ground
root = bpy.data.objects.new("Car", None)
scene.collection.objects.link(root)
root.location = (2, 0, 0)
mesh = bpy.data.meshes.new("Car_Body")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bmesh.ops.scale(bm, vec=(1.8, 4.4, 1.2), verts=bm.verts)
bmesh.ops.translate(bm, vec=(0, 0, 0.9), verts=bm.verts)
bm.to_mesh(mesh)
bm.free()
body = bpy.data.objects.new("Car_Body", mesh)
body.location = (2, 0, 0)
scene.collection.objects.link(body)
body.parent = root
body.matrix_parent_inverse = root.matrix_basis.inverted()
ground = bpy.data.objects.new("Detail ground", bpy.data.meshes.new("Detail ground"))
scene.collection.objects.link(ground)
"""

# Every shape the instructions show, as the model would write them, plus a move of another object.
DETAIL_SHAPES = """# Wheels, a rounded body, a window frame, a rail and a lathe-turned hub
import math
root = bpy.data.objects["Car"]
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.35, radius2=0.35, depth=0.25)
f = max(bm.faces, key=lambda face: len(face.verts))
bmesh.ops.inset_region(bm, faces=[f], thickness=0.06, depth=-0.04)
ret = bmesh.ops.extrude_face_region(bm, geom=[f])
bmesh.ops.translate(bm, vec=(0, 0, 0.02), verts=[v for v in ret["geom"] if isinstance(v, bmesh.types.BMVert)])
for face in bm.faces:
    face.smooth = True
mesh = bpy.data.meshes.new("Car_Wheel_FL")
bm.to_mesh(mesh)
bm.free()
wheel = bpy.data.objects.new("Car_Wheel_FL", mesh)
wheel.location = (3.0, 1.4, 0.35)
scene.collection.objects.link(wheel)
sub = wheel.modifiers.new("Smooth", "SUBSURF")
sub.levels = 2
sub.render_levels = 2
m = wheel.modifiers.new("Mirror", "MIRROR")
m.use_clip = True
a = wheel.modifiers.new("Row", "ARRAY")
a.count = 2
a.relative_offset_displace = (1.5, 0, 0)
s = wheel.modifiers.new("Shell", "SOLIDIFY")
s.thickness = 0.02
bm = bmesh.new()
verts = [bm.verts.new((0.1 + 0.05 * i, 0, 0.1 * i)) for i in range(4)]
edges = [bm.edges.new((verts[i], verts[i + 1])) for i in range(3)]
bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=(0, 0, 1), angle=math.tau, steps=32)
hub_mesh = bpy.data.meshes.new("Car_Hub")
bm.to_mesh(hub_mesh)
bm.free()
hub = bpy.data.objects.new("Car_Hub", hub_mesh)
hub.location = (3.0, -1.4, 0.35)
scene.collection.objects.link(hub)
n = 4
cu = bpy.data.curves.new("Car_Rail", "CURVE")
cu.dimensions = "3D"
cu.bevel_depth = 0.02
sp = cu.splines.new("POLY")
sp.points.add(n - 1)
for i in range(n):
    sp.points[i].co = (2 + 0.5 * i, 0, 1.6, 1)
rail = bpy.data.objects.new("Car_Rail", cu)
scene.collection.objects.link(rail)
bpy.data.objects["Detail ground"].location.x += 5
"""


class _DetailLLM:
    """Answers the stage loop, the detail stage's pick and its object rounds by the instructions it gets."""

    def __init__(self, pick):
        from eachlabs import detail

        self.detail = detail
        self.pick = pick
        self.object_replies = [code_reply(DETAIL_SHAPES), text_reply("The car has wheels now.")]
        self.layout = [code_reply(DETAIL_LAYOUT), text_reply("A car.")]
        self.lock = threading.Lock()
        self.object_messages = []
        self.picks = []

    def __call__(self, messages, tools):
        with self.lock:
            system = messages[0].get("content") if messages else ""
            if blender_fakes.is_intent_call(messages):
                return text_reply('{"intent": "build"}')
            if isinstance(system, str) and system.startswith(self.detail.PICK.split("%")[0][:60]):
                self.picks.append(messages)
                return text_reply(self.pick)
            if isinstance(system, str) and system.startswith(self.detail.INSTRUCTIONS[:60]):
                self.object_messages.append([dict(m) for m in messages])
                return self.object_replies.pop(0) if self.object_replies else text_reply("Done.")
            if isinstance(system, str) and "This stage: the layout." in system:
                return self.layout.pop(0) if self.layout else text_reply("Done.")
            return text_reply("Done.")


def test_detail_stage():
    """After the layout the detail stage improves the picked object in its own rounds: the shape examples run,
    new parts join the object where they stand, another object a step moves is put back, and the close-up renders
    the object alone and leaves the scene as it was."""
    import json

    from eachlabs import chat_run, visual_check

    scene = bpy.data.scenes.new("eachlabs_detail")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    real = preferences.detail_settings
    preferences.detail_settings = lambda context=None: (2, 2, False, False)
    try:
        with offline_api() as client:
            llm = _DetailLLM(json.dumps({"objects": [
                {"name": "Car", "level": "high", "parts": ["wheels", "hubs"]},
                {"name": "Spaceship"}, {"name": "Car_Body"}]}))
            client.chat_llm, client.balances = llm, [5.0, 4.9]
            chat_run.new_scene()
            chat_run.start(context, "a red car on a street")
            _chat_drive(60)
            state = chat_run.STATE
            check("detail: the stage shows between the layout and the materials, and ends done",
                  list(state.stages)[:3] == ["layout", "detail", "materials"] and state.stages["detail"] == "done"
                  and state.status == "done", "%s %s %s" % (state.stages, state.status, state.error))
            from eachlabs import detail as detail_mod

            extra = llm.object_messages[2:]  # one fix round when the measure after the last round finds problems
            check("detail: the pick saw the scene, and only the car's rounds ran (a part or an unknown name is not "
                  "picked)",
                  len(llm.picks) == 1 and len(llm.object_messages) in (2, 3)
                  and all('The object: "Car"' in m[1]["content"] for m in llm.object_messages)
                  and all(str(m[-1]["content"]).startswith(detail_mod.MEASURED) for m in extra),
                  "%d %d %s" % (len(llm.picks), len(llm.object_messages),
                                [str(m[-1]["content"])[:200] for m in extra]))
            answers = _tool_contents(llm.object_messages[1], "run_python") if len(llm.object_messages) > 1 else []
            told = answers[0] if answers else {}
            check("detail: every shape the instructions show runs on this Blender", told.get("ok") is True,
                  json.dumps(told)[:600])
            check("detail: a step that moves another object is undone, and the model is told",
                  told.get("put_back") == ["Detail ground"] and scene.objects["Detail ground"].location.x == 0.0,
                  json.dumps(told)[:400])
            wheel, rail, root = (scene.objects.get(n) for n in ("Car / Wheel FL", "Car / Rail", "Car"))
            check("detail: new parts become parts of the car where they were built",
                  wheel is not None and rail is not None and wheel.parent == root and rail.parent == root
                  and tuple(round(v, 4) for v in wheel.matrix_world.translation) == (3.0, 1.4, 0.35),
                  "%s %s" % (wheel and wheel.parent, wheel and tuple(wheel.matrix_world.translation)))
            check("detail: the steps are listed under their stage for Show code, and the guard is gone",
                  [s["stage"] for s in state.code_steps].count("detail") == 1 and chat_run._build.guard is None
                  and not chat_run._build.focus, str([s["stage"] for s in state.code_steps]))
            build = chat_run._build
            camera, engine = scene.camera, scene.render.engine
            person = bpy.data.objects.new("Person's lamp", bpy.data.meshes.new("Lamp"))
            scene.collection.objects.link(person)
            found = visual_check.render_object(build, "Car")
            check("detail: the close-up renders the car from four sides",
                  len(found.get("images", [])) == 4 and all(u.startswith("data:image/png;base64,")
                                                             for u in found["images"]), str(found)[:300])
            check("detail: the close-up leaves the scene as it was",
                  scene.camera == camera and scene.render.engine == engine and not person.hide_render
                  and not scene.objects["Detail ground"].hide_render
                  and not any(o.name.startswith(visual_check.OVERVIEW) for o in bpy.data.objects),
                  "%s %s %s" % (scene.camera, scene.render.engine, person.hide_render))
            check("detail: the close-up refuses the person's objects",
                  visual_check.render_object(build, "Person's lamp").get("images") == [])
            car_part = next(o for o in [scene.objects["Car"]] + list(scene.objects["Car"].children_recursive)
                            if o.type == "MESH")
            paint = bpy.data.materials.new("Close-up paint")
            paint.use_nodes = True
            paint.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.8, 0.02, 0.02, 1)
            paint.diffuse_color = (0.3, 0.3, 0.3, 1)  # stale: only the Base Color was set
            car_part.data.materials.clear()
            car_part.data.materials.append(paint)
            seen = []

            def peek(*_args):
                seen.append(tuple(paint.diffuse_color[:3]))
            bpy.app.handlers.render_pre.append(peek)
            try:
                visual_check.render_object(build, "Car")
            finally:
                bpy.app.handlers.render_pre.remove(peek)
            check("detail: the close-up shows a material's Base Color, and its viewport colour is put back",
                  seen and all(abs(c[0] - 0.8) < 1e-4 for c in seen)
                  and abs(paint.diffuse_color[0] - 0.3) < 1e-4, "%s %s" % (seen[:1], tuple(paint.diffuse_color)))
            from eachlabs import look_around
            around = look_around.render_view(build, None, ["Car"], "xray")
            check("look_at: the whole scene from four sides in X-ray, with a thing hidden, leaves the scene as it was",
                  len(around.get("images", [])) == 4 and len(around.get("views", [])) == 4
                  and scene.camera == camera and scene.render.engine == engine
                  and not scene.objects["Car"].hide_render and not scene.display.shading.show_xray
                  and not any(o.name.startswith(visual_check.OVERVIEW) for o in bpy.data.objects),
                  str({k: v for k, v in around.items() if k != "images"})[:300])
            check("look_at: refuses the person's objects and a bad mode",
                  look_around.render_view(build, "Person's lamp").get("images") == []
                  and look_around.render_view(build, None, (), "wire").get("images") == [])
            bpy.data.objects.remove(person)
    finally:
        preferences.detail_settings = real
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)
