"""Generated textures, the concept picture and the look stages that wait for them."""

import os
import threading
import types

import bpy

from eachlabs import preferences
from tests.blender_fakes import FakeClient, KIOSK_CODE, code_reply, offline_api, text_reply, tool_reply
from tests.smoke.chat_common import _ScriptLLM, _chat_drive, _tick_until, _tool_contents
from tests.smoke.common import BOX_CODE, WORK, check


BRICK_WALL = BOX_CODE + """# A brick wall with its material, on its ground
box("Wall ground", (20, 20, 0.05), (0, 0, -0.05))
wall = box("Wall", (6, 0.3, 3), (0, 0, 0))
paint = bpy.data.materials.new("Brick paint")
wall.data.materials.append(paint)
"""


def test_generated_textures():
    """The materials stage may order a texture: it is drawn by the texture worker, kept in the cache and set on the
    material as a box-projected image; a second order past the limit is refused."""
    import json

    from eachlabs import chat_run, generation
    from tests import glb_fixture

    os.environ[preferences.USER_DIR_ENV] = os.path.join(WORK, "user")
    drawn = []

    def worker(spec, cancel, emit, client):
        emit({"state": generation.RUNNING, "remote_id": "pr-" + spec.job_id})
        os.makedirs(spec.folder, exist_ok=True)
        path = os.path.join(spec.folder, spec.job_id + ".png")
        with open(path, "wb") as fh:
            fh.write(glb_fixture.png())
        drawn.append(spec.description)
        emit({"state": generation.READY, "path": path, "cost": 0.15})

    real_worker, real_limit = chat_run.TEX_WORKER, preferences.textures_limit
    chat_run.TEX_WORKER = worker
    preferences.textures_limit = lambda context=None: 1
    scene = bpy.data.scenes.new("eachlabs_textures")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    try:
        with offline_api() as client:
            order = ("generate_texture", {"description": "weathered red brick", "material": "Brick paint",
                                          "tile_m": 2})
            again = ("generate_texture", {"description": "mossy stone", "material": "Brick paint"})
            client.chat_llm = _ScriptLLM([code_reply(BRICK_WALL), text_reply("Laid out."), tool_reply(order),
                                          tool_reply(again), text_reply("Painted."), text_reply("Lit."),
                                          text_reply("Filmed."), text_reply("A brick wall.")])
            client.balances = [5.0, 4.8]
            chat_run.new_scene()
            chat_run.start(context, "a brick wall")
            shown = _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            plan = chat_run.STATE.plan
            check("textures: with 3D objects Off a plan with only the looks line asks first, and no step ran",
                  shown and plan is not None and plan.looks_only and plan.looks.startswith("Looks: up to 1 texture · up to $0.15. This run: about ")
                  and client.chat_llm.calls == 0 and not drawn, str(plan))
            chat_run.plan_answer("build")
            _chat_drive(30)
            mat = bpy.data.materials.get("Brick paint")
            image = mat.node_tree.nodes.get("Eachlabs texture image") if mat is not None else None
            linked = image is not None and any(l.from_node == image and l.to_socket.name == "Base Color"
                                               for l in mat.node_tree.links)
            mapping = mat.node_tree.nodes.get("Eachlabs texture mapping") if mat is not None else None
            check("textures: the ordered texture is set on the material, box-projected, one tile per 2 m",
                  drawn == ["weathered red brick"] and linked and image.projection == "BOX"
                  and image.image is not None and tuple(mapping.inputs["Scale"].default_value) == (0.5, 0.5, 0.5),
                  "%s %s" % (drawn, image and image.projection))
            llm = client.chat_llm
            materials = [m for m in llm.messages if "This stage: the materials" in m[0]["content"]]
            answers = _tool_contents(materials[-1], "generate_texture") if materials else []
            check("textures: the order is acknowledged, and one past the scene's limit is refused",
                  len(answers) == 2 and answers[0].get("ok") and "Brick paint" in answers[0].get("note", "")
                  and answers[1].get("ok") is False and "ordered its 1 textures" in answers[1].get("error", ""),
                  json.dumps(answers)[:400])
            rows = chat_run.STATE.objects
            check("textures: the run waits for it, and the bar row says it is done with its cost",
                  chat_run.STATE.status == "done" and any(r["kind"] == "texture" and r["state"] == "done"
                                                         and r["cost"] == 0.15 for r in rows), str(rows))
            seen = chat_run._build.read_scene().get("textures")
            check("textures: read_scene lists the texture as ready",
                  seen == [{"material": "Brick paint", "description": "weathered red brick", "status": "ready"}],
                  str(seen))
    finally:
        chat_run.TEX_WORKER, preferences.textures_limit = real_worker, real_limit
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)


def test_concept_picture():
    """A new scene starts with a concept picture: drawn once, only after Build on a plan that shows its price, shown
    to the layout and materials stages as an image, and linked in Show code's text; a follow-up draws none."""
    from eachlabs import chat_run
    from tests import glb_fixture

    os.environ[preferences.USER_DIR_ENV] = os.path.join(WORK, "user")
    picture = os.path.join(WORK, "concept-source.png")
    with open(picture, "wb") as fh:
        fh.write(glb_fixture.png())
    real = preferences.concept_picture, chat_run.preferences_folder
    preferences.concept_picture = lambda context=None: True
    folders = []  # (folder name, on the main thread)

    def folder(name):
        folders.append((name, threading.current_thread() is threading.main_thread()))
        return real[1](name)

    chat_run.preferences_folder = folder
    scene = bpy.data.scenes.new("eachlabs_concept")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)

    def drawn():
        return [e for e in FakeClient.log if e[0] == "create" and e[1] == "nano-banana-pro"]

    try:
        with offline_api() as client:
            FakeClient.results["next"] = picture
            first = len(drawn())
            restored = []
            real_restore, chat_run.restore_prompt = chat_run.restore_prompt, restored.append
            idle = _ScriptLLM([])
            client.chat_llm, client.balances = idle, [5.0, 5.0]
            chat_run.new_scene()
            chat_run.start(context, "a kiosk at dusk")
            shown = _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            plan = chat_run.STATE.plan
            check("concept: with 3D objects Off a new scene shows a plan with only the looks line and its price",
                  shown and plan is not None and plan.looks_only and plan.items == []
                  and plan.looks.startswith("Looks: a concept picture · $0.15. This run: about "), str(plan))
            check("concept: nothing is drawn and no step runs before Build", len(drawn()) == first and idle.calls == 0,
                  str(len(drawn()) - first))
            chat_run.plan_answer("cancel")
            _chat_drive(5)
            check("concept: Cancel draws nothing and gives the prompt back",
                  len(drawn()) == first and restored == ["a kiosk at dusk"] and chat_run.STATE.status == "idle"
                  and not chat_run.has_scene(), "%s %s" % (restored, chat_run.STATE.status))
            chat_run.restore_prompt = real_restore

            llm = _ScriptLLM([code_reply(KIOSK_CODE), text_reply("Laid out.")])
            client.chat_llm, client.balances = llm, [5.0, 4.8]
            chat_run.new_scene()
            chat_run.start(context, "a kiosk at dusk")
            _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            check("concept: still nothing drawn while the plan waits", len(drawn()) == first)
            chat_run.plan_answer("build")
            _chat_drive(30)
            created = drawn()[first:]
            with_picture = [m[0]["content"].split("This stage: ")[1].split(".")[0] for m in llm.messages
                            if any(isinstance(x["content"], list) for x in m)]
            check("concept: one picture is drawn after Build, wide, from the prompt, and the layout and materials "
                  "stages see it",
                  len(created) == 1 and created[0][2]["aspect_ratio"] == "16:9"
                  and "a kiosk at dusk" in created[0][2]["prompt"]
                  and sorted(set(with_picture)) == ["the layout", "the materials"], "%s %s" % (created, with_picture))
            check("concept: its folder is found on the main thread, never by the worker",
                  ("concepts", True) in folders and all(main for _name, main in folders), str(folders))
            check("concept: Show code's text links the picture", "# Concept picture: https://fake.invalid/"
                  in chat_run.code_text(), chat_run.code_text()[:300])
            llm2 = _ScriptLLM([text_reply("ok")])
            client.chat_llm, client.balances = llm2, [5.0, 5.0]
            chat_run.start(context, "make the kiosk blue")
            _chat_drive(30)
            check("concept: a follow-up draws none and asks for nothing", len(drawn()) == first + 1
                  and chat_run.STATE.status == "done", "%d %s" % (len(drawn()) - first, chat_run.STATE.status))
            car = _ScriptLLM([text_reply("ok")])
            car.intent = '{"intent": "build", "label": "concept car", "concept": false}'
            client.chat_llm, client.balances = car, [5.0, 5.0]
            chat_run.start(context, "add a concept car")
            _chat_drive(30)
            check("concept: the word alone does not draw one: the quick call says a concept car is a thing",
                  len(drawn()) == first + 1 and chat_run.STATE.status == "done", str(len(drawn()) - first))
            asked = _ScriptLLM([text_reply("ok")])
            asked.intent = '{"intent": "build", "label": "concept picture", "concept": true}'
            client.chat_llm, client.balances = asked, [5.0, 5.0]
            chat_run.start(context, "draw me a new concept picture of this, then add a bench")
            shown = _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            plan = chat_run.STATE.plan
            check("concept: a follow-up that asks for one shows its price first",
                  shown and plan is not None and plan.looks.startswith("Looks: a concept picture · $0.15. This run: about ")
                  and len(drawn()) == first + 1, str(plan))
            chat_run.plan_answer("build")
            _chat_drive(30)
            check("concept: ... and draws it after Build", len(drawn()) == first + 2, str(len(drawn()) - first))
    finally:
        preferences.concept_picture, chat_run.preferences_folder = real
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)


def test_looks_need_build():
    """With 3D objects on, a concept picture or a texture is never paid for unless a plan showed its price and the
    person pressed Build: a plan call that fails, an empty plan and a follow-up that adds nothing each show a plan
    with only the looks line; a plan of objects carries the line itself."""
    import json

    from eachlabs import chat_run, generation
    from tests import glb_fixture

    os.environ[preferences.USER_DIR_ENV] = os.path.join(WORK, "user")
    ran = []

    def worker(spec, cancel, emit, client):
        os.makedirs(spec.folder, exist_ok=True)
        path = os.path.join(spec.folder, spec.job_id + ".png")
        with open(path, "wb") as fh:
            fh.write(glb_fixture.png())
        ran.append(spec.description)
        emit({"state": generation.READY, "path": path, "cost": 0.15})

    real = chat_run.TEX_WORKER, chat_run.GEN_WORKER, preferences.textures_limit, preferences.objects_3d
    chat_run.TEX_WORKER = worker
    chat_run.GEN_WORKER = lambda spec, cancel, emit, client: emit({"state": generation.FAILED, "error": "no"})
    preferences.textures_limit = lambda context=None: 1
    preferences.objects_3d = lambda context=None: "AUTO"
    scene = bpy.data.scenes.new("eachlabs_looks")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    order = ("generate_texture", {"description": "red brick", "material": "Brick paint"})
    for mat in [m for m in bpy.data.materials if m.name.startswith("Brick paint")]:  # the wall's name stays exact
        bpy.data.materials.remove(mat)

    try:
        with offline_api() as client:
            def ask(prompt, replies, label):
                llm = _ScriptLLM(replies)
                client.chat_llm, client.balances = llm, [5.0, 5.0]
                chat_run.start(context, prompt)
                shown = _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
                plan = chat_run.STATE.plan
                check("looks: %s shows a plan with only the looks line" % label,
                      shown and plan is not None and plan.looks_only
                      and plan.looks.startswith("Looks: up to 1 texture · up to $0.15. This run: about ") and not ran, str(plan))
                return llm

            chat_run.new_scene()
            ask("a brick wall", [text_reply("I cannot plan that.")], "a plan the chat could not make")
            chat_run.plan_answer("cancel")
            _chat_drive(5)
            chat_run.new_scene()
            ask("a brick wall", [text_reply('{"objects_3d": [], "code": []}')], "an empty plan")
            chat_run.plan_answer("cancel")
            _chat_drive(5)
            check("looks: Cancel orders nothing", not ran and not chat_run.STATE.running)

            chat_run.new_scene()
            plan_reply = text_reply(json.dumps({"objects_3d": [], "code": ["brick wall"]}))
            llm = _ScriptLLM([plan_reply, code_reply(BRICK_WALL), text_reply("Laid out.")])
            client.chat_llm, client.balances = llm, [5.0, 5.0]
            chat_run.start(context, "a brick wall")
            _tick_until(lambda: chat_run.STATE.plan_waiting, 5)
            plan = chat_run.STATE.plan
            check("looks: a plan of objects carries the looks line itself",
                  plan is not None and not plan.looks_only and bool(plan.items)
                  and plan.looks.startswith("Looks: up to 1 texture · up to $0.15. This run: about "), str(plan))
            chat_run.plan_answer("build")
            _tick_until(lambda: llm.calls >= 2, 5)
            check("looks: after Build no second plan is asked for", not chat_run.STATE.plan_waiting)
            _chat_drive(30)

            ask("make the wall brick", [text_reply('{"objects_3d": [], "code": [], "adds_objects": false}'),
                                        text_reply("Kept."), tool_reply(order), text_reply("Painted.")],
                "a follow-up that adds nothing")
            chat_run.plan_answer("build")
            _chat_drive(30)
            check("looks: after Build the follow-up may order its texture", ran == ["red brick"], str(ran))
    finally:
        chat_run.TEX_WORKER, chat_run.GEN_WORKER, preferences.textures_limit, preferences.objects_3d = real
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)
