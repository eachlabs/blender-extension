"""Finding things, the tabs and targeted edits."""

import json
import re
import time
import types

import bpy

from tests import blender_fakes
from tests.blender_fakes import FakeLLM, KIOSK_CODE, code_reply, offline_api, text_reply
from tests.smoke.chat_common import _ScriptLLM, _chat_drive, _scene_in, _tool_contents
from tests.smoke.common import BOX_CODE, check


def test_find_and_selection():
    """Find and list answer without building; "this" means the selection, and without one nothing runs."""
    import json

    from eachlabs import chat_run
    from eachlabs.ui import bar_state
    from eachlabs.ui.text_field import TextField

    scene = bpy.data.scenes.new("eachlabs_find")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    layer = scene.view_layers[0]
    restored = []
    real_restore, chat_run.restore_prompt = chat_run.restore_prompt, restored.append
    try:
        with offline_api() as client:
            client.chat_llm, client.balances = FakeLLM([code_reply(KIOSK_CODE), text_reply("A kiosk.")]), [5.0, 5.0]
            chat_run.new_scene()
            chat_run.start(context, "a kiosk")
            _chat_drive()
            kiosk = scene.objects.get("Kiosk")
            check("find: the scene has a kiosk", kiosk is not None and chat_run.STATE.status == "done", "%s %s %s" % (
                chat_run.STATE.status, chat_run.STATE.error, sorted(o.name for o in scene.objects)))

            def ask(prompt, answer, replies=()):
                llm = _ScriptLLM(list(replies))
                llm.intent = json.dumps(answer)
                client.chat_llm, client.balances = llm, [5.0, 4.999]
                started = chat_run.start(context, prompt)
                _chat_drive()
                return started, llm

            kiosk.select_set(False, view_layer=layer)
            _started, llm = ask("find me the kiosk you built", {"intent": "find", "label": "kiosk",
                                                                "names": ["Kiosk", "Invented"]})
            state = chat_run.STATE
            bar = bar_state.from_chat(state, TextField([], mac=False), False, time.monotonic())
            check("find: no stage and no plan run, the kiosk is selected and the bar says what was found",
                  llm.calls == 0 and state.status == "found" and state.reply == "Found: Kiosk (1 object)"
                  and kiosk.select_get(view_layer=layer) and bar.mode == "done" and bar.actions == ["frame", "new"]
                  and re.fullmatch("1 ROUND \u00b7 \\d+ S \u00b7 \\$0.001", bar.cost_text), "%s %r %s %s" % (state.status, state.reply,
                                                                             bar.actions, bar.cost_text))
            check("find: a question is not added to the scene's prompts", "find me the kiosk you built"
                  not in chat_run._build.prompts, str(chat_run._build.prompts))
            ask("show me the castle", {"intent": "find", "label": "castle", "names": []})
            check("find: no match says so", chat_run.STATE.reply == 'Nothing like "castle" in this scene. Try other '
                  'words, or ask for it to be built.', chat_run.STATE.reply)
            ask("what did you build?", {"intent": "list", "names": ["Kiosk"]})
            check("find: a list names the main things", chat_run.STATE.reply == "This scene has: Kiosk.",
                  chat_run.STATE.reply)

            # "this" with nothing selected: nothing runs, the prompt comes back.
            for obj in scene.objects:
                obj.select_set(False, view_layer=layer)
            _started, llm = ask("make this one red", {"intent": "build", "selection": True})
            check("selection: 'this' with nothing selected asks for a selection and keeps the prompt",
                  llm.calls == 0 and chat_run.STATE.error == "Select the object first, then send again."
                  and restored[-1:] == ["make this one red"] and not chat_run.STATE.running, chat_run.STATE.error)

            # The person's own object, selected on purpose: the chat may change it.
            mine = bpy.data.objects.new("My crate", bpy.data.meshes.new("My crate"))
            scene.collection.objects.link(mine)
            mine.select_set(True, view_layer=layer)
            paint = code_reply("# paint it red\nobj = bpy.data.objects['My crate']\nobj.location.z = 2.0")
            _started, llm = ask("make this one red", {"intent": "build", "selection": True},
                                [paint, text_reply("Red now.")])
            sent = llm.messages[0][1]["content"] if llm.messages else ""
            answers = _tool_contents(llm.messages[1], "run_python") if len(llm.messages) > 1 else []
            check("selection: the stages are told the selected object is the target, by its name",
                  "The person selected these objects and means them: My crate." in sent, sent[:300])
            check("selection: changing the person's selected object is not reported as touching theirs",
                  answers and answers[0].get("ok") and not answers[0].get("note")
                  and mine.location.z == 2.0, str(answers)[:300])
    finally:
        chat_run.restore_prompt = real_restore
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)


class _TabLLM(_ScriptLLM):
    """A _ScriptLLM that also keeps the user message of each quick intent call."""

    def __call__(self, messages, tools):
        if blender_fakes.is_intent_call(messages):
            self.asked.append(messages[1]["content"])
        return super().__call__(messages, tools)


def test_tab_change():
    """On Assets and Characters a selected thing, or a thing the prompt names, is changed by a targeted edit; with
    nothing selected the prompt adds one new thing."""
    from eachlabs import chat_run
    from eachlabs.chat import selection
    from eachlabs.instructions import targets

    scene = bpy.data.scenes.new("eachlabs_tab_change")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    layer = scene.view_layers[0]

    def ask(prompt, replies=(), answer=None):
        llm = _TabLLM(list(replies))
        llm.intent, llm.asked = json.dumps(answer) if answer else None, []
        client.chat_llm, client.balances = llm, [5.0, 4.999]
        chat_run.start(context, prompt)
        _chat_drive()
        return llm

    def select(*objects):
        for obj in scene.objects:
            obj.select_set(False, view_layer=layer)
        for obj in objects:
            obj.select_set(True, view_layer=layer)

    try:
        with offline_api() as client:
            chat_run.new_scene()
            chat_run.STATE.target = "scene"
            client.chat_llm, client.balances = FakeLLM([code_reply(KIOSK_CODE), text_reply("A kiosk.")]), [5.0, 5.0]
            chat_run.start(context, "a kiosk")
            _chat_drive()
            kiosk = next((o for o in scene.objects if o.name.startswith("Kiosk")), None)
            check("tabs: the first build made a kiosk", kiosk is not None)
            camera = bpy.data.objects.new("Tab camera", bpy.data.cameras.new("Tab camera"))
            scene.collection.objects.link(camera)
            before = sorted(o.name for o in scene.objects)

            chat_run.STATE.target = targets.ASSET
            select(kiosk, camera)  # the camera is no thing to change on Assets
            walnut = code_reply("# make it walnut\nbpy.data.objects[%r].scale.z = 2.5" % kiosk.name)
            llm = ask("make it walnut", [walnut, text_reply("Walnut now.")])
            state = chat_run.STATE
            seen = [o["name"] for o in _scene_in(llm.messages[0]).get("objects", [])] if llm.messages else []
            asked = "\n".join(str(m.get("content")) for call in llm.messages for m in call)
            check("tabs: on Assets a selected thing is changed by a targeted edit, without the quick call",
                  state.status == "done" and state.stages == {"edit": "done"} and not llm.asked
                  and seen == [kiosk.name] and round(kiosk.scale.z, 2) == 2.5,
                  "%s %s %s %s %s" % (state.status, state.stages, llm.asked, seen, tuple(kiosk.scale)))
            check("tabs: the change adds no new thing and asks for none",
                  sorted(o.name for o in scene.objects) == before and "Add exactly one new thing" not in asked,
                  str(sorted(o.name for o in scene.objects)))

            select()
            barrel = code_reply(BOX_CODE + 'box("Barrel", (0.6, 0.6, 0.9), (3, 0, 0))')
            llm = ask("a wooden barrel", [barrel, text_reply("A barrel.")])
            asked = "\n".join(str(m.get("content")) for call in llm.messages for m in call)
            check("tabs: on Assets with nothing selected the prompt adds one new thing, as before",
                  chat_run.STATE.status == "done" and "Add exactly one new thing to the scene: a wooden barrel" in asked
                  and any(o.name.startswith("Barrel") for o in scene.objects) and "edit" not in chat_run.STATE.stages,
                  "%s %s" % (chat_run.STATE.status, list(chat_run.STATE.stages)))
            check("tabs: the quick call is told the tab and decides whether a named thing is changed",
                  len(llm.asked) == 1 and llm.asked[0].startswith(targets.KIND_NOTE[targets.ASSET]), str(llm.asked))

            taller = code_reply("# make the kiosk taller\nbpy.data.objects[%r].scale.z = 3.0" % kiosk.name)
            llm = ask("make the kiosk taller", [taller, text_reply("Taller now.")],
                      {"intent": "build", "label": "kiosk", "names": [kiosk.name], "edit": True})
            seen = [o["name"] for o in _scene_in(llm.messages[0]).get("objects", [])] if llm.messages else []
            check("tabs: on Assets a thing the prompt names is changed when the quick call says so",
                  chat_run.STATE.stages == {"edit": "done"} and seen == [kiosk.name]
                  and round(kiosk.scale.z, 2) == 3.0, "%s %s %s" % (chat_run.STATE.stages, seen, tuple(kiosk.scale)))

            chat_run.STATE.target = targets.CHARACTER
            llm = ask("a ginger cat", [code_reply(BOX_CODE + 'box("Cat", (0.5, 0.2, 0.3), (-3, 0, 0))'),
                                       text_reply("A cat.")])
            check("tabs: on Characters the quick call is told to count only people and animals",
                  len(llm.asked) == 1 and llm.asked[0].startswith(targets.KIND_NOTE[targets.CHARACTER])
                  and "Add exactly one new character" in "\n".join(str(m.get("content")) for c in llm.messages
                                                                    for m in c), str(llm.asked))

            select(kiosk)
            check("tabs: the bar names the selected thing, not a camera or a hidden object",
                  selection.selected_things(types.SimpleNamespace(view_layer=layer, scene=scene)) == [kiosk.name])
            kiosk.hide_set(True, view_layer=layer)
            check("tabs: a hidden selected object is no thing to change",
                  selection.selected_things(types.SimpleNamespace(view_layer=layer, scene=scene)) == [])
            kiosk.hide_set(False, view_layer=layer)
    finally:
        chat_run.STATE.target = "scene"
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)


HOUSE_AND_GARAGE = BOX_CODE + """# A house and a garage that share one wall paint
paint = bpy.data.materials.new("Wall paint")
paint.diffuse_color = (0.9, 0.9, 0.9, 1)
house = bpy.data.objects.new("House", None)
scene.collection.objects.link(house)
for part in (box("House walls", (8, 6, 3), (0, 0, 0)), box("House roof", (8, 6, 1), (0, 0, 3))):
    part.parent = house
    part.data.materials.append(paint)
garage = box("Garage", (4, 6, 3), (9, 0, 0))
garage.data.materials.append(paint)
"""

# One step that paints the shared wall paint red and also moves and reshapes the garage.
RED_AND_MORE = """# paint the house red
paint = bpy.data.materials["Wall paint"]
paint.diffuse_color = (0.8, 0.05, 0.05, 1)
garage = bpy.data.objects["Garage"]
garage.location.x += 5
for v in garage.data.vertices:
    v.co.z *= 2
"""


def test_targeted_edit():
    """A request that only changes its targets runs one short stage that sees only them, and every other object
    of the chat's own is put back after each step, with the model told."""
    import json

    from eachlabs import chat_run

    scene = bpy.data.scenes.new("eachlabs_edit")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    layer = scene.view_layers[0]
    try:
        with offline_api() as client:
            client.chat_llm = FakeLLM([code_reply(HOUSE_AND_GARAGE), text_reply("A house and a garage.")])
            client.balances = [5.0, 5.0]
            chat_run.new_scene()
            chat_run.start(context, "a house with a garage")
            _chat_drive()
            garage = scene.objects.get("Garage")
            check("edit: the house and the garage are built", garage is not None and "House / Walls" in scene.objects)
            garage_at, garage_z = tuple(garage.location), max(v.co.z for v in garage.data.vertices)
            for obj in scene.objects:
                obj.select_set(False, view_layer=layer)
            scene.objects["House / Roof"].select_set(True, view_layer=layer)  # one part of it

            llm = _ScriptLLM([code_reply(RED_AND_MORE), text_reply("The house is red now.")])
            llm.intent = json.dumps({"intent": "build", "label": "house", "selection": True, "edit": True})
            client.chat_llm, client.balances = llm, [5.0, 4.99]
            chat_run.start(context, "make this red")
            _chat_drive()
            state = chat_run.STATE
            walls, garage = scene.objects["House / Walls"], scene.objects["Garage"]
            house_colour = tuple(round(c, 2) for c in walls.material_slots[0].material.diffuse_color)
            garage_mat = garage.material_slots[0].material
            check("edit: one short stage runs, not the five, and the run ends with its reply",
                  llm.calls == 2 and state.status == "done" and state.stages == {"edit": "done"}
                  and state.reply == "The house is red now."
                  and "This stage: change only the target." in llm.messages[0][0]["content"],
                  "%s %s %s %r" % (llm.calls, state.status, state.stages, state.reply))
            seen = [o["name"] for o in _scene_in(llm.messages[0]).get("objects", [])]
            flat = json.dumps(seen)
            check("edit: read_scene lists only the target's objects", "House / Walls" in flat and "Garage" not in flat,
                  flat)
            check("edit: 'make this red' changes only the target",
                  house_colour == (0.8, 0.05, 0.05, 1.0)
                  and tuple(round(c, 2) for c in garage_mat.diffuse_color) == (0.9, 0.9, 0.9, 1.0)
                  and tuple(garage.location) == garage_at
                  and max(v.co.z for v in garage.data.vertices) == garage_z,
                  "%s %s %s" % (house_colour, tuple(garage_mat.diffuse_color), tuple(garage.location)))
            answers = _tool_contents(llm.messages[1], "run_python") if len(llm.messages) > 1 else []
            told = answers[0] if answers else {}
            check("edit: a step that moves another object is undone, and the model is told",
                  told.get("put_back") == ["Garage"] and "Change only the target: House." in told.get("note", ""),
                  json.dumps(told)[:400])
            check("edit: the guard is gone after the run, with its copies",
                  chat_run._build.guard is None and not chat_run._build.focus
                  and not any(m.users == 0 for m in bpy.data.materials if m.name.startswith("Wall paint")),
                  str([(m.name, m.users) for m in bpy.data.materials]))
    finally:
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)
