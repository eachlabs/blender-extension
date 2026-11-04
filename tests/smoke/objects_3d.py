"""The 3D generator: the plan, its jobs, stand-ins and generated files."""

import math
import os
import threading
import time
import types

import bpy
import mathutils

from eachlabs import preferences
from tests.blender_fakes import code_reply, offline_api, text_reply, tool_reply
from tests.smoke.chat_common import _ScriptLLM, _chat_drive, _tick_until, _tool_contents
from tests.smoke.common import BOX_CODE, WORK, _chat_tree, check


# A car along Y; a second car as an empty turned a quarter, its body parented along the empty's X; a lamp; a bus.
STAND_INS = BOX_CODE + '''box("Car 1", (2.0, 4.5, 1.4), (2, -1, 0))
root = bpy.data.objects.new("Car 2", None)
root.location = (8, -1, 0.2)
root.rotation_euler = (0, 0, math.pi / 2)
scene.collection.objects.link(root)
body = box("Car body 2", (4.5, 2.0, 1.4), (0, 0, 0))
body.parent = root
box("Lamp", (0.3, 0.3, 5.0), (0, 3, 0))
box("Bus", (2.5, 12.0, 3.0), (0, 9, 0))
'''

PAINT_ALL = '''# Paint every mesh and bevel it
paint = bpy.data.materials.new("Paint")
for obj in scene.objects:
    if obj.type == "MESH":
        obj.data.materials.clear()
        obj.data.materials.append(paint)
        obj.modifiers.new("Bevel", "BEVEL")
'''


def test_generated_objects():
    """generate_object: the job answers at once, the model arrives on the main thread at its placements, copies
    share the mesh, a step cannot repaint it, a failure is told to the model and the reply, Stop cancels."""
    import json

    from eachlabs import asset_cache, chat_run, generation, objects_3d, scene_build, thread_safety, workflow_3d
    from tests import glb_fixture

    os.environ[preferences.USER_DIR_ENV] = os.path.join(WORK, "user")
    release, imported = threading.Event(), threading.Event()
    started = []  # descriptions the fake worker ran

    def worker(spec, cancel, emit, client):
        emit({"state": generation.RUNNING, "remote_id": "ex-" + spec.job_id})
        if spec.description == "broken lamp":
            emit({"state": generation.FAILED, "error": "the provider refused it"})
            return
        while not release.wait(0.02):
            if cancel.is_set():
                emit({"state": generation.CANCELLED, "error": "Stopped"})
                return
        path = os.path.join(spec.folder, spec.job_id + ".glb")
        with open(path, "wb") as fh:
            fh.write(glb_fixture.box_glb((2.0, 1.0, 0.5)))
        path = asset_cache.Cache(spec.cache_folder).put(spec.description, workflow_3d.cache_tier(spec.tier), path,
                                                     "v1", 0.45)
        started.append(spec.description)
        emit({"state": generation.READY, "path": path, "cost": 0.45})

    real_worker, real_mode = chat_run.GEN_WORKER, preferences.objects_3d
    chat_run.GEN_WORKER = worker
    preferences.objects_3d = lambda context=None: "AUTO"
    stand_ins = ("run_python", {"code": STAND_INS})
    scene = bpy.data.scenes.new("eachlabs_3d")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)

    def plan_reply(*items):
        return text_reply(json.dumps({"objects_3d": [{"name": n, "description": d, "tier": "large"} for n, d in items],
                                      "code": ["road", "sidewalks"]}))

    try:
        with offline_api() as client:
            # Cancel on the plan: nothing is built and the prompt comes back.
            restored = []
            real_restore, chat_run.restore_prompt = chat_run.restore_prompt, restored.append
            client.chat_llm = _ScriptLLM([plan_reply(("car", "red car"))])
            client.balances = [10.0, 10.0]
            chat_run.new_scene()
            chat_run.start(context, "a street with a red car")
            shown = _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            plan = chat_run.STATE.plan
            check("3d plan: the plan waits in the bar before anything is generated",
                  shown and plan is not None and [i.name for i in plan.three_d] == ["car"]
                  and not chat_run._run.jobs and client.chat_llm.calls == 1, str(plan))
            check("3d plan: the plan call asks for JSON with the 3D rules and the limit",
                  "At most 2 entries." in client.chat_llm.messages[0][0]["content"]
                  and "never generate a building, a vehicle" in client.chat_llm.messages[0][0]["content"]
                  and client.chat_sent[-1]["reasoning"] is False, client.chat_llm.messages[0][0]["content"][:200])
            check("3d plan: a chip click moves an item to code and back", chat_run.plan_toggle(0)
                  and plan.items[0].mode == "code" and chat_run.plan_toggle(0) and plan.items[0].mode == "3d")
            chat_run.cancel()  # Stop on the plan is its Cancel
            _chat_drive(5)
            check("3d plan: Cancel ends the run, builds nothing and gives the prompt back",
                  not chat_run.STATE.running and chat_run.STATE.status == "idle" and restored == ["a street with a red car"]
                  and not chat_run.has_scene() and not any(o.get("eachlabs_run") for o in scene.objects),
                  "%s %s" % (chat_run.STATE.status, restored))
            chat_run.restore_prompt = real_restore

            llm = _ScriptLLM([plan_reply(("car", "red car"), ("lamp", "broken lamp")),
                              tool_reply(stand_ins),
                              text_reply("Laid out."), code_reply(PAINT_ALL), text_reply("Painted."),
                              text_reply("Lit."), text_reply("Filmed."), text_reply("A street with two cars.")],
                             hold_at=3, hold=imported)
            client.chat_llm, client.balances = llm, [10.0, 9.0]
            chat_run.new_scene()
            check("3d: run starts", chat_run.start(context, "a street with two red cars"), chat_run.STATE.error)
            run = chat_run._run
            check("3d: Build starts the stages", _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
                  and chat_run.plan_answer("build"))
            _tick_until(lambda: len(run.jobs) == 2, 5)
            queued = [(j.name, j.state) for j in chat_run._jobs(run)]
            check("3d queue: Build queues every approved 3D item before the first step, without the model asking",
                  len(queued) == 2 and len(llm.messages) <= 2, "%s %d" % (queued, len(llm.messages)))
            _tick_until(lambda: len(run.jobs) == 2 and chat_run._jobs(run)[0].state == generation.RUNNING, 5)
            states = [(j.name, j.state) for j in chat_run._jobs(run)]
            check("3d queue: one 3D run at a time; the next waits in the queue",
                  states == [("car", "running"), ("lamp", "queued")], str(states))
            build = chat_run._build
            seen = build.read_scene().get("generated_3d") or []
            _tick_until(lambda: scene.objects.get("Car 1") is not None
                        and scene.objects["Car 1"].get(scene_build.PLACEHOLDER), 5)
            check("3d: read_scene lists the ordered objects as pending with their job ids",
                  [e["status"] for e in seen] in (["pending", "pending"], ["pending", "failed"])
                  and all(e["job_id"].startswith("3d-") for e in seen), str(seen))
            tagged = sorted(o.name for o in scene.objects if o.get(scene_build.PLACEHOLDER))
            check("3d: the code versions are tagged as placeholders, parts included, and read_scene names them",
                  tagged == ["Car 1", "Car 2", "Car body 2", "Lamp"]
                  and seen and seen[0].get("code_versions") == ["Car 1", "Car 2"], str(tagged))
            release.set()
            _tick_until(lambda: any(j.state == generation.DONE for j in chat_run._jobs(run)), 5)
            imported.set()
            ended = _chat_drive(30)
            check("3d plan: the layout stage is told the code versions to build, under their exact names",
                  '- "Car" (copies "Car 1", "Car 2"' in llm.messages[1][1]["content"]
                  and "generate_object" not in str(llm.messages), llm.messages[1][1]["content"][-300:])
            check("3d: an object nobody approved keeps its code version, never ordered",
                  "Bus" in scene.objects and len(run.jobs) == 2)
            done_paths = {os.path.normpath(j.path) for j in chat_run._jobs(run) if j.path}
            check("3d: a finished job lets go of its cache file, so the cache may evict it again",
                  done_paths and not (done_paths & asset_cache.held()), str(done_paths & asset_cache.held()))
            state = chat_run.STATE
            cars = sorted((o for o in scene.objects if o.get(scene_build.GENERATED)), key=lambda o: o.name)
            check("3d: run ends done", ended and state.status == "done", "%s %s" % (state.status, state.error))
            check("3d: two copies named after the object, in the chat's collection",
                  [o.name for o in cars] == ["Red car 1", "Red car 2"]
                  and all(build.owns(o) and o.users_collection[0] in _chat_tree(build) for o in cars),
                  str([o.name for o in cars]))
            check("3d: the copies share one mesh (linked duplicates)", len(cars) == 2 and cars[0].data == cars[1].data
                  and build.owns(cars[0].data))
            scene.view_layers[0].update()
            dims = [round(v, 3) for v in cars[0].dimensions] if cars else []
            check("3d: scaled to 4.5 m along its longest side, base on the ground", dims == [4.5, 1.125, 2.25]
                  and round(min((cars[0].matrix_world @ mathutils.Vector(c)).z for c in cars[0].bound_box), 4) == 0.0,
                  str(dims))
            check("3d: the second copy stands where its code version stood, turned like it",
                  len(cars) == 2 and tuple(round(v, 3) for v in cars[1].location) == (8.0, -1.0, 0.2)
                  and round(math.degrees(cars[1].rotation_euler.z)) == 90
                  and tuple(cars[0].color) == (1.0, 1.0, 1.0, 1.0), str([tuple(c.location) for c in cars]))
            box = cars[0].matrix_world if cars else None
            corners = [box @ mathutils.Vector(c) for c in cars[0].bound_box] if cars else []
            extent = [round(max(c[i] for c in corners) - min(c[i] for c in corners), 2) for i in range(2)]
            check("3d swap: the first copy takes its code version's place, size and long side (along Y)",
                  cars and tuple(round(v, 3) for v in cars[0].location) == (2.0, -1.0, 0.0) and extent[0] in (1.12, 1.13)
                  and extent[1] == 4.5,
                  "%s %s" % (tuple(cars[0].location) if cars else None, extent))
            check("3d swap: the code versions it replaced are gone, with their parts",
                  not any(n in scene.objects for n in ("Car 1", "Car 2", "Car body 2")),
                  str(sorted(o.name for o in scene.objects if "stand-in" in o.name or "body" in o.name)))
            lamp_stand_in = scene.objects.get("Lamp")
            check("3d fallback: the code version of the object that failed stays, as an ordinary object",
                  lamp_stand_in is not None and build.owns(lamp_stand_in)
                  and scene_build.PLACEHOLDER not in lamp_stand_in, str(lamp_stand_in))
            check("3d fallback: an object never ordered keeps its code version untouched",
                  "Bus" in scene.objects and scene_build.PLACEHOLDER not in scene.objects["Bus"])
            mesh = cars[0].data if cars else None
            mat = mesh.materials[0] if mesh and mesh.materials else None
            nodes = mat.node_tree.nodes if mat else []
            images = [n.image for n in nodes if n.type == "TEX_IMAGE" and n.image is not None]
            check("3d: textured: UVs, a packed base colour image, a roughness-metallic image, and the tint node",
                  mesh is not None and len(mesh.uv_layers) == 1 and len(images) == 2
                  and all(i.packed_file is not None for i in images)
                  and objects_3d.TINT_NODE in [n.name for n in nodes] and mat.name.startswith("eachlabs_"),
                  str([n.type for n in nodes]))
            check("3d: a step that repaints every mesh leaves the generated ones alone",
                  mat is not None and mat.name != "Paint" and all(not o.modifiers for o in cars),
                  "%s %s" % (mat.name if mat else None, [list(o.modifiers) for o in cars]))
            paint_answer = _tool_contents(llm.messages[4], "run_python") if len(llm.messages) > 4 else []
            check("3d: ... and says so to the model", paint_answer and "generated models keep their own textures"
                  in paint_answer[0].get("note", ""), str(paint_answer)[:300])
            check("3d: the failed object is told to the model once, to build in code",
                  len({m[1]["content"] for m in llm.messages  # one stage's request, sent with each of its rounds
                       if "The 3D model of broken lamp could not be made (the provider refused it)" in m[1]["content"]})
                  == 1, "%s %s" % (sorted(run.told), [m[1]["content"][-200:] for m in llm.messages]))
            check("3d: the reply says in one plain line that the lamp stays built in code",
                  "\nThe lamp stays built in code: its 3D model was not made (the provider refused it).\n"
                  in state.reply, state.reply)
            check("3d plan: planned things still missing got a stage of their own, then one reply line each",
                  state.stages.get("complete") == "done"
                  and state.reply.endswith("\nNot built: the road, the sidewalks."),
                  "%s %r" % (state.stages, state.reply))
            complete_asks = [m[1]["content"] for m in llm.messages if "build what is missing" in m[0]["content"]]
            check("3d plan: the complete stage is told what is missing, by name",
                  complete_asks and "build them now: road (named after it); sidewalks (named after it)"
                  in complete_asks[0], str(complete_asks)[:300])
            seen = build.read_scene().get("generated_3d") or []
            check("3d: read_scene now lists the car as ready with its copies and the lamp as failed",
                  [(e["status"], e.get("names")) for e in seen] == [("ready", ["Red car 1", "Red car 2"]),
                                                                    ("failed", None)], json.dumps(seen))
            listed = [o for o in build.read_scene()["objects"] if o.get("generated")]
            check("3d: generated objects are marked in read_scene", len(listed) == 2, str(listed))
            rows = {r["name"]: r for r in state.objects}
            check("3d: the bar's rows: the car done with its cost, the lamp failed",
                  rows.get("car", {}).get("state") == generation.DONE and rows["car"]["cost"] == 0.45
                  and rows.get("lamp", {}).get("state") == generation.FAILED, str(state.objects))
            check("3d: the API key never reaches the model", "fake-key" not in str(llm.messages))

            # The same object again, in a new scene: from the cache, with no run and no cost.
            chat_run.new_scene()
            studio = ("run_python", {"code": BOX_CODE + 'box("Car", (4.0, 1.8, 1.3), (0, 0, 0))\n'})
            cache_llm = _ScriptLLM([plan_reply(("car", "Red car")), tool_reply(studio),
                                    text_reply("Laid out.")])
            client.chat_llm, client.balances = cache_llm, [9.0, 9.0]
            ran_before = len(started)
            chat_run.start(context, "a red car in a studio")
            _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            plan = chat_run.STATE.plan
            check("3d cache: the plan shows the cached object as free",
                  plan is not None and plan.summary_3d() == "3D: car · 1 cached, free", plan and plan.summary_3d())
            chat_run.plan_answer("build")
            _chat_drive(30)
            run = chat_run._run
            job = chat_run._jobs(run)[0] if run.jobs else None
            copies = [o for o in scene.objects if job and o.get(scene_build.GENERATED) == job.job_id]
            scene.view_layers[0].update()
            check("3d cache: the same description and tier come from the cache, with no run and no cost",
                  job is not None and job.cached and job.cost == 0.0 and job.state == generation.DONE
                  and len(started) == ran_before,
                  "%s %s" % (job and (job.cached, job.cost, job.state), started))
            check("3d cache: ... and it is placed at the size asked this time", len(copies) == 1
                  and round(max(copies[0].dimensions), 3) == 4.0, str([tuple(o.dimensions) for o in copies]))
            check("3d cache: the bar row says cached", any(r.get("cached") and r.get("cost") == 0.0
                                                           for r in chat_run.STATE.objects), str(chat_run.STATE.objects))

            # A model still running when the check stage ends: the run waits for it, then swaps it in.
            release.clear()
            chat_run.new_scene()
            bike_plan = {"objects_3d": [{"name": "bike", "description": "green bike", "size_m": 2.0, "measure": "length"},
                                        {"name": "basket", "description": "wicker basket", "tier": "medium"}],
                         "code": []}
            late_llm = _ScriptLLM([text_reply(json.dumps(bike_plan)),
                                   tool_reply(("run_python", {"code": BOX_CODE + 'box("Bike", (0.6, 1.8, 1.1), '
                                                                       '(0, 0, 0.4))\nbox("Ground slab", (10, 10, '
                                                                       '0.15), (0, 0, 0))\n'}))])
            client.chat_llm, client.balances = late_llm, [9.0, 9.0]
            chat_run.start(context, "a green bike")
            _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            chat_run.plan_answer("build")
            waited = _tick_until(lambda: chat_run.STATE.objects_wait, 15)
            stages_done = all(v == "done" for v in chat_run.STATE.stages.values())
            check("3d wait: after the check stage the run keeps going while a 3D model is still coming",
                  waited and stages_done and chat_run.STATE.running and "Bike" in scene.objects,
                  "%s %s" % (chat_run.STATE.stages, chat_run.STATE.running))
            release.set()
            _chat_drive(15)
            bikes = [o.name for o in scene.objects if o.get(scene_build.GENERATED)
                     and o.get(scene_build.GENERATED) == (chat_run._run.jobs or [None])[0]]
            check("3d wait: ... and ends once the model replaced its code version",
                  chat_run.STATE.status == "done" and bikes == ["Green bike"] and "Bike" not in scene.objects,
                  "%s %s" % (chat_run.STATE.status, bikes))
            bike = scene.objects.get("Green bike")
            check("3d outcome: an approved 3D item the chat never built gets its own plain reply line",
                  chat_run.STATE.reply.endswith("\nBasket was not built (no code version of it was built).")
                  and chat_run.STATE.reply.count("Basket") == 1, repr(chat_run.STATE.reply))
            check("3d ground: a model whose code version floated rests on the surface under it",
                  bike is not None and round(bike.location.z, 3) == 0.15
                  and round(min((bike.matrix_world @ mathutils.Vector(c)).z for c in bike.bound_box), 3) == 0.15,
                  str(bike.location.z if bike else None))
            check("3d size: the model takes exactly the chat's size along its measure, not the code version's",
                  bike is not None and round(max(bike.dimensions[0], bike.dimensions[1]), 3) == 2.0,
                  str(tuple(bike.dimensions) if bike else None))

            # Follow-ups: a plan shows only when there is something to decide or pay for; the person's words put a
            # solid piece in 3D, never an object with parts; a change that only recolours shows none.
            client.chat_llm = _ScriptLLM([text_reply(json.dumps({"objects_3d": [], "code": ["bench"],
                                                                 "adds_objects": True}))])
            client.balances = [9.0, 9.0]
            chat_run.start(context, "add a bench")
            shown = _tick_until(lambda: chat_run.STATE.plan_waiting, 1.0)
            _chat_drive(15)
            check("3d follow-up: a change with nothing to decide or pay for shows no plan and runs",
                  not shown and chat_run.STATE.status == "done", chat_run.STATE.status)
            client.chat_llm = _ScriptLLM([text_reply(json.dumps({"objects_3d": [], "code": [
                {"name": "marble statues", "description": "white marble statues", "solid": True},
                {"name": "sports cars", "description": "red sports cars"}], "adds_objects": True}))])
            client.balances = [9.0, 9.0]
            chat_run.start(context, "add two hyper-realistic marble statues and two hyper-realistic sports cars")
            _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            plan = chat_run.STATE.plan
            check("3d follow-up: a solid piece the person calls hyper-realistic is in 3D; cars stay in code, in detail",
                  plan is not None and [i.name for i in plan.three_d] == ["marble statues"] and plan.three_d[0].chosen
                  and plan.items[1].mode == "code" and plan.items[1].detail == "high", str(plan))
            chat_run.plan_answer("cancel")
            _chat_drive(5)
            client.chat_llm = _ScriptLLM([text_reply(json.dumps({"objects_3d": [], "code": ["bike"],
                                                                 "adds_objects": False})), text_reply("Done.")])
            client.balances = [9.0, 9.0]
            chat_run.start(context, "make the bike blue")
            waited = _tick_until(lambda: chat_run.STATE.plan_waiting, 1.0)
            _chat_drive(15)
            check("3d follow-up: a change that only recolours shows no plan and runs",
                  not waited and chat_run.STATE.status == "done" and not chat_run._run.jobs, chat_run.STATE.status)

            # Stop cancels the jobs that are still running.
            release.clear()
            stop_llm = _ScriptLLM([plan_reply(("van", "blue van")),
                                   tool_reply(("run_python", {"code": BOX_CODE + 'box("Van", (2, 5, 2), (0, -8, 0))\n'})),
                                   text_reply("Laid out.")], hold_at=3, hold=threading.Event())
            client.chat_llm, client.balances = stop_llm, [9.0, 9.0]
            chat_run.start(context, "add a blue van")
            run = chat_run._run
            _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            follow_plan = stop_llm.messages[0][0]["content"] if stop_llm.messages else ""
            check("3d plan: a follow-up plan lists only new objects and knows the generated ones",
                  "list only the objects this change adds" in follow_plan and "green bike" in follow_plan
                  and "At most 1 entries" in follow_plan, follow_plan[-300:])
            chat_run.plan_answer("build")
            _tick_until(lambda: len(run.jobs) == 1 and chat_run._jobs(run)[0].state == generation.RUNNING, 5)
            counted = thread_safety._gen_threads
            chat_run.cancel()
            job = chat_run._jobs(run)[0] if run.jobs else None
            stop_llm.hold.set()
            _chat_drive(10)
            _tick_until(lambda: False, 0.3)
            check("3d: Stop cancels the running 3D jobs", job is not None and job.state == generation.CANCELLED
                  and job.cancel_event.is_set(), str(job and job.state))
            from eachlabs.ui import bar_state
            from eachlabs.ui.text_field import TextField
            seen = bar_state.from_chat(chat_run.STATE, TextField([], mac=False), False, time.monotonic())
            check("3d: Stop while a 3D run goes says it may still be billed",
                  chat_run.STATE.billed and job is not None and job.left_running
                  and seen.error == "Stopped — a 3D run already started may still be billed.", seen.error)
            ended = _tick_until(lambda: thread_safety._gen_threads == 0, 3)
            check("3d: the 3D worker counts for Blender 4.2's guard while it runs, and is counted out once stopped",
                  counted >= 1 and ended, "%d %d" % (counted, thread_safety._gen_threads))
            check("3d: ... and nothing of it is imported", not any(o.get(scene_build.GENERATED) == (job and job.job_id)
                                                                 for o in scene.objects))

            # Upgrade in place: select a code-built solid piece, "make this hyper-realistic".
            release.set()
            _chat_drive(10)
            chat_run.new_scene()
            preferences.objects_3d = lambda context=None: "OFF"
            old_car = BOX_CODE + ('root = bpy.data.objects.new("Old lion", None)\nroot.location = (3, 4, 0)\n'
                                  'scene.collection.objects.link(root)\n'
                                  'body = box("Old lion body", (1.8, 4.2, 1.2), (0, 0, 0))\nbody.parent = root\n'
                                  'wheel = box("Old lion paw", (0.3, 0.6, 0.6), (0.9, 1.5, 0))\nwheel.parent = root\n')
            client.chat_llm, client.balances = _ScriptLLM([code_reply(old_car), text_reply("A lion.")]), [5.0, 5.0]
            chat_run.start(context, "a stone lion")
            _chat_drive(15)
            preferences.objects_3d = lambda context=None: "AUTO"
            layer = scene.view_layers[0]
            for obj in scene.objects:
                obj.select_set(False, view_layer=layer)
            scene.objects["Old lion / Body"].select_set(True, view_layer=layer)  # one part of it, named by the scheme at the end of the run
            up = _ScriptLLM([text_reply('{"objects_3d": [], "code": [{"name": "old lion", "solid": true}], '
                                        '"adds_objects": false}')])
            up.intent = json.dumps({"intent": "build", "label": "old lion", "selection": True, "edit": True})
            client.chat_llm, client.balances = up, [5.0, 5.0]
            release.clear()
            body = scene.objects["Old lion / Body"]
            car_before = (tuple(body.matrix_world.translation), tuple(body.dimensions), len(body.data.vertices),
                          len(body.material_slots))
            chat_run.start(context, "make this hyper-realistic")
            shown = _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            plan = chat_run.STATE.plan
            item = plan.three_d[0] if plan is not None and plan.three_d else None
            check("3d upgrade: the plan shows the selected solid piece as a 3D item at its own size",
                  shown and item is not None and item.targets == ["Old lion"] and item.size_m == 4.2
                  and item.measure == "length", str(plan))
            check("3d upgrade: its picture prompt comes from the object's parts and the request",
                  item is not None and item.picture_prompt.startswith(
                      'Old lion, as the person asked: "make this hyper-realistic"; with body, paw;'),
                  item.picture_prompt if item is not None else "")
            chat_run.plan_answer("build")
            run = chat_run._run
            _tick_until(lambda: run.jobs and chat_run._jobs(run)[0].state == generation.RUNNING, 5)
            _tick_until(lambda: False, 0.5)
            body = scene.objects.get("Old lion / Body")
            car_now = body and (tuple(body.matrix_world.translation), tuple(body.dimensions),
                                len(body.data.vertices), len(body.material_slots))
            check("3d upgrade: no step runs and the code version stays untouched until the swap",
                  up.calls == 1 and car_now == car_before and chat_run.STATE.stages == {"edit": "active"},
                  "%s %s %s" % (up.calls, car_now, chat_run.STATE.stages))
            release.set()
            _chat_drive(30)
            check("3d upgrade: the reply says the object is now a 3D model",
                  "Old lion is now a 3D model, at the same place and size." in chat_run.STATE.reply,
                  chat_run.STATE.reply)
            new = [o for o in scene.objects if o.get(scene_build.GENERATED) in chat_run._run.jobs]
            scene.view_layers[0].update()
            corners = [o.matrix_world @ mathutils.Vector(c) for o in new for c in o.bound_box]
            middle = [(min(c[i] for c in corners) + max(c[i] for c in corners)) / 2 for i in range(2)] if corners \
                else []
            check("3d upgrade: the model replaces the group at its place and size, and its old parts are gone",
                  len(new) == 1 and round(max(new[0].dimensions[0], new[0].dimensions[1]), 3) == 4.2
                  and abs(middle[0] - 3.075) < 0.05 and abs(middle[1] - 4.0) < 0.05
                  and new[0].name == "Old lion"
                  and not any(n in scene.objects for n in ("Old lion / Body", "Old lion / Paw")),
                  "%s %s %s" % ([o.name for o in new], middle, [o.name for o in scene.objects][:8]))
    finally:
        chat_run.GEN_WORKER, preferences.objects_3d = real_worker, real_mode
        release.set()
        imported.set()
        chat_run.new_scene()


def test_placeholder_parts():
    """A 3D model's code version is the tagged root with every part later parented under it, plus the chat's loose
    objects named after it that stand inside it; not another copy, and not one standing outside it."""
    from eachlabs import objects_3d, scene_build

    scene = bpy.data.scenes.new("eachlabs_parts")
    build = scene_build.SceneBuild(scene, "partsrun")
    scope = {"scene": scene, "bpy": bpy, "bmesh": __import__("bmesh")}
    exec(BOX_CODE + """
church = box("Church", (10, 20, 12), (0, 0, 0))
door = box("Church_Door", (2, 0.2, 3), (0, -10, 0))
bench = box("Church_Bench", (2, 0.5, 0.5), (0, -30, 0))
copy = box("Church 2", (10, 20, 12), (2, 3, 0))
""", scope)
    try:
        for obj in list(scene.objects):
            build.adopt(obj)
        church = scene.objects["Church"]
        church[scene_build.PLACEHOLDER] = "job1"
        window = bpy.data.objects.new("Window", bpy.data.meshes.new("Window"))  # a later stage's part
        scene.collection.objects.link(window)
        build.adopt(window)
        window.parent = church
        scene.view_layers[0].update()
        roots, parts = objects_3d.placeholders(build, "job1")
        names = sorted(o.name for o in parts)
        check("placeholder: the code version takes its later parts and its loose door, not the bench or a copy",
              roots == [church] and names == sorted((church.name, scene.objects["Church_Door"].name, window.name)),
              str(names))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


def test_failed_note_paths():
    """A 3D object that failed with a local path in its error is told to the model without the path."""
    from eachlabs import chat_run, generation

    home = os.path.expanduser("~")
    job = generation.Job("3d-path", "object", "car", "red car", "large", state=generation.FAILED,
                         error="OSError: cannot write '%s/eachlabs/3d-cache/car.glb'" % home)
    chat_run.GEN.add(job)
    run = types.SimpleNamespace(jobs=["3d-path"], told=set())
    try:
        notes = chat_run._failed_notes(run)
    finally:
        chat_run.GEN.jobs.pop("3d-path", None)
    check("3d: a failure sent to the model has no local path, and the person's folder reads as ~",
          len(notes) == 1 and home not in notes[0] and "'~/eachlabs/3d-cache/car.glb'" in notes[0], str(notes))


def test_generated_files():
    """Clear generated files empties the 3D cache (models and textures) and the concept pictures; a job's claim
    reads an index of the scene's names that is built again only when the names change."""
    from eachlabs import asset_cache, chat_run, generation, plan3d, scene_build

    os.environ[preferences.USER_DIR_ENV] = os.path.join(WORK, "user")
    for name, file in (("3d-cache", "car.glb"), ("concepts", "concept-1.jpg")):
        with open(os.path.join(preferences.user_folder(name), file), "wb") as fh:
            fh.write(b"x" * 2048)
    check("files: the Preferences line counts the 3D cache and the concept pictures",
          preferences.cache_text().startswith("Generated files: ")
          and preferences.EACHLABS_OT_clear_3d_cache.bl_label == "Clear generated files", preferences.cache_text())
    result = bpy.ops.eachlabs.clear_3d_cache()
    left = [n for name in preferences.GENERATED_FOLDERS for n in os.listdir(preferences.user_folder(name))]
    check("files: Clear generated files deletes 3D models, textures and concept pictures", result == {"FINISHED"}
          and not left and preferences.cache_text() == "Generated files: none", str(left))

    scene = bpy.data.scenes.new("eachlabs_claim")
    build = scene_build.SceneBuild(scene, "claimtest")
    run = types.SimpleNamespace(build=build, name_key=None, name_index={})
    for i in range(30):
        obj = bpy.data.objects.new("Bench %d" % i if i < 2 else "Prop %d" % i, None)
        scene.collection.objects.link(obj)
    item = plan3d.Item("bench", "wooden bench", "medium")
    job = generation.Job("3d-claim", "object", "bench", "wooden bench", "medium", context={"item": item})
    real, calls = plan3d.name_words, []

    def counted(name):
        calls.append(name)
        return real(name)

    plan3d.name_words = counted
    try:
        for _ in range(5):
            chat_run._claim(run, job)
        first = len(calls)
        for _ in range(5):
            chat_run._claim(run, job)
        again = len(calls) - first
        scene.objects["Prop 5"].name = "Bench 9"
        chat_run._claim(run, job)
        renamed = run.name_index.get(("bench",), [])
    finally:
        plan3d.name_words = real
    check("files: the claim splits each name once while nothing changes, and again after a rename",
          first <= 30 + 5 and again == 5 and "Bench 9" in renamed, "%d %d %s" % (first, again, renamed))
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj)
    bpy.data.scenes.remove(scene)
