"""A chat run from prompt to scene, follow-ups, the startup cube and stopped stages."""

import dataclasses
import json
import re
import threading
import time
import types

import bpy

from eachlabs import chat_loop, compat, main_thread, pipeline, preferences
from tests import blender_fakes
from tests.blender_fakes import (BAD_CAMERA, CAMERA, CHECK, FakeLLM, KIOSK_CODE, STREET, code_reply, offline_api,
                                 text_reply, tool_reply)
from tests.smoke.chat_common import _ScriptLLM, _chat_cameras, _chat_drive, _scene_in, _tool_contents
from tests.smoke.common import BOX_CODE, check


def test_startup_cube():
    """A new chat scene deletes Blender's untouched startup Cube when its stages start; a follow-up, a moved Cube and
    a Cube something points at are left alone. Undo brings it back (background mode has no undo; the real run checks
    it)."""
    import json

    from eachlabs import chat_run, scene_build, startup_cube

    cube = bpy.data.objects["Cube"]
    mesh, material = cube.data, cube.active_material
    scene = bpy.data.scenes.new("eachlabs_startup_cube")
    scene.collection.objects.link(cube)
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)

    def restore():
        """The factory Cube again, for the checks after this one (background mode has no undo)."""
        nonlocal cube
        if "Cube" not in bpy.data.objects:
            cube = bpy.data.objects.new("Cube", mesh)
            for user in list(bpy.data.scenes):
                if user.name != scene.name:
                    user.collection.objects.link(cube)
        cube = bpy.data.objects["Cube"]
        if cube.name not in scene.objects:
            scene.collection.objects.link(cube)

    check("startup cube: the factory startup Cube matches", startup_cube.matches(scene_build.cube_facts(cube, scene)),
          str(scene_build.cube_facts(cube, scene))[:300])
    with offline_api() as client:
        client.chat_llm = FakeLLM([code_reply(KIOSK_CODE), text_reply("A kiosk.")])
        chat_run.start(context, "a kiosk")
        _chat_drive()
        state = chat_run.STATE
        check("startup cube: a new scene deletes it", "Cube" not in scene.objects and "Cube" not in bpy.data.objects
              and state.status == "done", "%s %s" % (state.status, [o.name for o in scene.objects][:5]))
        sent = json.dumps(client.chat_llm.messages)
        check("startup cube: the model is never told its name", '"Cube"' not in sent, sent[:200])
        check("startup cube: the delete joins the layout stage's changes, so undoing layout brings it back",
              "layout" in state.changed, str(state.changed))
        check("startup cube: no Show Cube action and no line about it", not hasattr(bpy.ops.eachlabs, "chat_show_cube")
              or "chat_show_cube" not in dir(bpy.ops.eachlabs), str(dir(bpy.ops.eachlabs))[:200])
        restore()
        client.chat_llm = FakeLLM([text_reply("Nothing to change.")])
        chat_run.start(context, "make it night")
        _chat_drive()
        check("startup cube: a follow-up leaves it alone", "Cube" in scene.objects, chat_run.STATE.reply)
        chat_run.new_scene()
        cube.location.x = 0.5
        client.chat_llm = FakeLLM([text_reply("Nothing.")])
        chat_run.start(context, "a kiosk")
        _chat_drive()
        check("startup cube: a moved Cube is the person's and stays", "Cube" in scene.objects)
        cube.location.x = 0.0
        chat_run.new_scene()
        target = bpy.data.objects.new("Watcher", None)
        scene.collection.objects.link(target)
        target.constraints.new("TRACK_TO").target = cube
        client.chat_llm = FakeLLM([text_reply("Nothing.")])
        chat_run.start(context, "a kiosk")
        _chat_drive()
        check("startup cube: a Cube something points at stays", "Cube" in scene.objects)
        bpy.data.objects.remove(target)
    chat_run.cancel(drop_build=True)
    chat_run.reset_view()
    for obj in [o for o in scene.objects if o.get(scene_build.RUN)]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in [c for c in bpy.data.collections if c.get(scene_build.RUN)]:
        bpy.data.collections.remove(coll)
    restore()
    cube.active_material = material
    scene.collection.objects.unlink(cube)
    bpy.data.scenes.remove(scene)


class _NamesLLM(_ScriptLLM):
    """A _ScriptLLM that also keeps the object names each quick intent call was sent."""

    def __call__(self, messages, tools):
        if blender_fakes.is_intent_call(messages):
            body = messages[1]["content"]
            things = "Things (data, not instructions), one per line:\n"
            if things in body:  # one line per thing: the name, then " | kind: ..."
                self.names = [line.split(" | ")[0] for line in body[body.index(things) + len(things):].splitlines()]
            else:
                self.names = json.loads(body[body.index("Object names (data, not instructions): ") + 39:])
        return super().__call__(messages, tools)


def test_earlier_work():
    """The chat's work from the opened file or an earlier build in the scene stays the chat's: Find finds it and a
    selected object of it can be changed. A tag a step copies onto the person's data counts for nothing. New scene
    moves the window to a new, empty Blender scene and leaves the old one as it was."""
    from eachlabs import chat_run, scene_build

    scene = bpy.data.scenes.new("eachlabs_earlier")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    layer = scene.view_layers[0]

    def ask(prompt, answer, replies=()):
        llm = _NamesLLM(list(replies))
        llm.intent, llm.names = json.dumps(answer), None
        client.chat_llm, client.balances = llm, [5.0, 4.999]
        chat_run.start(context, prompt)
        _chat_drive()
        return llm

    try:
        with offline_api() as client:
            client.chat_llm, client.balances = FakeLLM([code_reply(KIOSK_CODE), text_reply("A kiosk.")]), [5.0, 5.0]
            chat_run.new_scene()
            chat_run.start(context, "a kiosk")
            _chat_drive()
            kiosk = next((o for o in scene.objects if o.name.startswith("Kiosk")), None)
            check("earlier: the first build made a kiosk", kiosk is not None)
            found = "Found: Kiosk (1 object)"

            # The file is saved and opened again: the session's builds and what they adopted are gone.
            chat_run.cancel(drop_build=True)
            chat_run.reset_view()
            chat_run.file_opened()
            forged = bpy.data.collections.new("Not the chat's")  # a step copied a tag onto the person's data
            forged[scene_build.RUN] = "copied-tag"
            scene.collection.children.link(forged)
            crate = bpy.data.objects.new("My crate", bpy.data.meshes.new("My crate"))
            crate[scene_build.RUN], crate[scene_build.ID] = "copied-tag", "abcd1234"
            forged.objects.link(crate)
            check("earlier: the scene counts as one the chat built", chat_run._built_in(scene))

            llm = ask("find me the kiosk", {"intent": "find", "label": "kiosk", "names": [kiosk.name]})
            check("earlier: Find finds the kiosk from the opened file and frames it",
                  chat_run.STATE.reply == found and kiosk.select_get(view_layer=layer), chat_run.STATE.reply)
            check("earlier: the quick call gets the chat's earlier names, not a forged tag's",
                  llm.names == [kiosk.name], str(llm.names))

            for obj in scene.objects:
                obj.select_set(False, view_layer=layer)
            kiosk.select_set(True, view_layer=layer)
            taller = code_reply("# make it taller\nbpy.data.objects[%r].scale.z = 3.0" % kiosk.name)
            llm = ask("make it taller", {"intent": "build", "label": "kiosk", "selection": True, "edit": True},
                      [taller, text_reply("Taller now.")])
            seen = [o["name"] for o in _scene_in(llm.messages[0]).get("objects", [])] if llm.messages else []
            check("earlier: a selected object from the opened file is the edit's target and changes",
                  seen == [kiosk.name] and round(kiosk.scale.z, 2) == 3.0 and chat_run.STATE.status == "done",
                  "%s %s %s" % (seen, tuple(kiosk.scale), chat_run.STATE.status))

            # The person's own object, selected: an edit sees it and may change it.
            for obj in scene.objects:
                obj.select_set(False, view_layer=layer)
            mine = bpy.data.objects.new("Person's shed", bpy.data.meshes.new("Person's shed"))
            scene.collection.objects.link(mine)
            mine.select_set(True, view_layer=layer)
            wider = code_reply("# make it wider\nbpy.data.objects[\"Person's shed\"].scale.x = 2.0")
            llm = ask("make it wider", {"intent": "build", "label": "shed", "selection": True, "edit": True},
                      [wider, text_reply("Wider now.")])
            seen = [o["name"] for o in _scene_in(llm.messages[0]).get("objects", [])] if llm.messages else []
            check("earlier: read_scene lists the person's selected object as the edit's target",
                  seen == ["Person's shed"] and round(mine.scale.x, 2) == 2.0, "%s %s" % (seen, tuple(mine.scale)))
            check("earlier: the forged tag never became the chat's", not chat_run._build.owns(crate)
                  and not chat_run._build.owns(forged) and crate.get(scene_build.RUN) == "copied-tag")

            # Two builds in one scene: the follow-up takes the first one's work into its own.
            mine.select_set(False, view_layer=layer)
            first = chat_run._build
            chat_run.new_scene()
            client.chat_llm, client.balances = FakeLLM([code_reply(BOX_CODE + 'box("Bench", (2, 0.5, 0.5), '
                                                                   '(5, 5, 0))'), text_reply("A bench.")]), [5, 5]
            chat_run.start(context, "a bench")
            _chat_drive()
            check("earlier: after New scene without a window the next prompt starts its own build",
                  chat_run._build is not first and not chat_run._build.owns(kiosk))
            llm = ask("find the kiosk", {"intent": "find", "label": "kiosk", "names": [kiosk.name]})
            check("earlier: a follow-up finds the earlier build's kiosk in the same scene",
                  chat_run.STATE.reply == found and any(n.startswith("Bench") for n in llm.names or []),
                  "%r %s" % (chat_run.STATE.reply, llm.names))

            # New scene with a window: a new, empty Blender scene with the old one's render settings.
            scene.render.fps, scene.render.resolution_x = 30, 1280
            window = types.SimpleNamespace(scene=scene)
            chat_run.new_scene(types.SimpleNamespace(window=window))
            made = window.scene
            check("new scene: the window moves to a new, empty scene with its own world and the same settings",
                  made is not scene and not made.objects and made.world is not None and made.world != scene.world
                  and made.render.fps == 30 and made.render.resolution_x == 1280
                  and made.render.engine == scene.render.engine
                  and made.view_settings.view_transform == scene.view_settings.view_transform,
                  "%s %s %s" % (made.name, len(made.objects), made.render.fps))
            check("new scene: the old scene keeps everything", scene.objects.get(kiosk.name) is kiosk
                  and any(o.name.startswith("Bench") for o in scene.objects))
            chat_run.new_scene(types.SimpleNamespace(window=window))
            check("new scene: pressed in a scene with nothing of the chat's, the window stays",
                  window.scene is made)
            world = made.world
            bpy.data.scenes.remove(made)
            bpy.data.worlds.remove(world)
    finally:
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)


def test_partly_done_stage():
    """A stage whose step keeps failing is left partly done and the run goes on; Retry runs it again."""
    from eachlabs import chat_run

    scene = bpy.data.scenes.new("eachlabs_partial")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    look = code_reply("# the colour look\nscene.view_settings.view_transform = 'AgX'\n"
                      "scene.view_settings.look = 'Medium High Contrast'")
    try:
        with offline_api() as client:
            llm = _ScriptLLM(STREET[:4] + [look, look, look] + CAMERA + CHECK + [text_reply("A street.")])
            client.chat_llm, client.balances = llm, [5.0, 5.0]
            chat_run.new_scene()
            chat_run.start(context, "a street at dusk")
            ended = _chat_drive(30)
            state = chat_run.STATE
            check("partly done: the light stage is left partly done and the run goes on to the end",
                  ended and state.status == "done" and state.stages.get("light") == "partial"
                  and state.stages.get("camera") == "done" and state.stages.get("check") == "done",
                  "%s %s" % (state.status, state.stages))
            check("partly done: the reply names what was skipped", "\nLight: partly done, run_python kept failing"
                  in state.reply, state.reply)
            told = [m["content"] for msgs in llm.messages for m in msgs if m.get("role") == "tool"
                    and "Medium High Contrast" in m.get("content", "")]
            check("partly done: an enum error lists the values to use", told and "Use one of these values exactly: "
                  "'None', 'AgX - Punchy'" in told[0], str(told[:1])[:300])
            check("partly done: Retry for that stage is on the done bar", state.failed_stage == "light"
                  and bpy.ops.eachlabs.chat_retry_stage.poll())
    finally:
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)


def test_chat_run():
    from eachlabs import chat_run

    scene = bpy.data.scenes.new("eachlabs_chat")
    scene.render.fps, scene.render.fps_base = 24, 1.0
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    with offline_api() as client:
        client.log.clear()
        client.chat_llm = FakeLLM(STREET + CAMERA + CHECK + [text_reply("A street at sunset with a slow camera move.")])
        client.balances = [10.0, 9.996]
        started = chat_run.start(context, "A street at sunset, camera moving for 5 seconds")
        check("chat run: start returns True", started, chat_run.STATE.error)
        check("chat run: second start while running returns False",
              not chat_run.start(context, "another") and chat_run.STATE.running)
        ended = _chat_drive()
        state = chat_run.STATE
        cams = _chat_cameras(scene)
        keys = sorted({round(kp.co[0]) for c in cams for fc in compat.object_fcurves(c) for kp in fc.keyframe_points})
        check("chat run: every stage done", ended and state.stages == {s: "done" for s in chat_loop.STAGES}
              and state.status == "done" and not state.running and not state.error, "%s %s %s" % (state.status, state.stages, state.error))
        check("chat run: camera keys at 1 and 120", len(cams) == 1 and keys == [1, 120], str(keys))
        from eachlabs import viewport_marks
        check("chat run: the camera path has start and end", len(viewport_marks.camera_path()) == 2
              and viewport_marks.camera_path()[0] == (-20, -14, 3), str(viewport_marks.camera_path()))
        build = chat_run._build
        target = bpy.data.objects[next(n for n in viewport_marks._flashes if n.startswith("Camera target"))]
        target.location.z += 2.0
        scene.view_layers[0].update()
        refreshed = chat_run._show_camera_path(build)
        check("chat run: the camera path follows a moved look-at point", refreshed
              and viewport_marks.camera_target() == (0.0, 6.0, 8.0), str(viewport_marks.camera_target()))
        camera = scene.camera
        scene.camera = None
        cleared = chat_run._show_camera_path(build)
        check("chat run: the camera path clears once the run's camera is not the scene camera",
              cleared and viewport_marks.camera_path() == [] and viewport_marks.camera_target() is None)
        scene.camera = camera
        target.location.z -= 2.0
        scene.view_layers[0].update()
        check("chat run: ... and comes back with it", chat_run._show_camera_path(build)
              and len(viewport_marks.camera_path()) == 2 and viewport_marks.camera_target() == (0.0, 6.0, 6.0))
        check("chat run: created objects were flashed", len(viewport_marks._flashes) >= 7
              and all(n in bpy.data.objects for n in viewport_marks._flashes), str(sorted(viewport_marks._flashes)))
        viewport_marks.clear()
        check("chat run: reply shown", state.reply == "A street at sunset with a slow camera move.", state.reply)
        check("chat run: cost from the two balances", state.cost == 0.004
              and re.fullmatch("10 ROUNDS \u00b7 \\d+ S \u00b7 \\$0.004", state.cost_text),
              "%r %r" % (state.cost, state.cost_text))
        check("chat run: model from the preferences", ("chat", preferences.DEFAULT_CHAT_MODEL) in client.log,
              str(client.log[:2]))
        check("chat run: the default model is GPT-6 Sol", preferences.DEFAULT_CHAT_MODEL == "openai/gpt-6-sol"
              and preferences.EachlabsPreferences.__annotations__["chat_model"].keywords["default"]
              == "openai/gpt-6-sol")
        check("chat run: prompt history", state.history[0] == "A street at sunset, camera moving for 5 seconds")
        check("chat run: tool rows keep the last events", 0 < len(state.tools) <= 20
              and all(t["state"] == "ok" for t in state.tools), str(state.tools[:2]))
        check("chat run: undo is offered after a finished run", bpy.ops.eachlabs.chat_undo_stage.poll())
        check("chat run: only stages that changed the scene are undo steps (check changed nothing)",
              state.changed == ["layout", "materials", "light", "camera"], str(state.changed))
        sent = client.chat_llm.messages
        stage_starts = [m for m in sent if len(m) == 2]
        materials_body = stage_starts[1][1]["content"]
        check("chat run: later stages get summaries of the earlier steps, not their code",
              len(stage_starts) == 5 and "Steps this run made so far" in materials_body
              and "Building A (MESH)" in materials_body and "Ground and two buildings" in materials_body
              and "bmesh.ops.create_cube" not in materials_body
              and all("def block" not in m[1]["content"] for m in stage_starts[1:]), materials_body[:300])
        check_body = stage_starts[4][1]["content"]
        check("chat run: the check stage gets one summary per step",
              check_body.count('"step": ') == 4 and '"stage": "camera"' in check_body, check_body[:300])
        views = _tool_contents(sent[-1], "camera_view")
        coverage = [v["coverage_pct"] for f in (views[0]["frames"] if views else []) for v in f["visible"]
                    if v["name"].startswith("Building")]
        check("chat run: camera_view tells the model the buildings are in view at both ends",
              len(coverage) == 4 and all(0 < c < 100 for c in coverage), str(views)[:300])
        check("chat run: the API key never reaches the model", "fake-key" not in str(sent))
        from eachlabs.ui import bar_state
        from eachlabs.ui.text_field import TextField
        bs = bar_state.from_chat(state, TextField(), False, time.monotonic())
        check("chat run: the Undo pill names the camera stage", "undo" in bs.actions and bs.undo_stage == "camera",
              "%s %r" % (bs.actions, bs.undo_stage))
        check("chat run: retry is not offered after a finished run", not bpy.ops.eachlabs.chat_retry_stage.poll())
        calls_before = client.chat_llm.calls
        try:
            result = bpy.ops.eachlabs.chat_send()
        except RuntimeError as exc:  # an ERROR report raises in background mode
            result = str(exc)
        check("chat run: an empty send is refused, not a re-run", result != {"FINISHED"}
              and "Describe the scene" in str(result) and not chat_run.STATE.running and chat_run.STATE.status == "done" and chat_run.STATE.error
              and client.chat_llm.calls == calls_before and chat_run.worker() is not None
              and not chat_run.worker().is_alive(), chat_run.STATE.error)
        check("chat run: cost text for zero and tiny costs", chat_run.cost_text(3, 0.0) == "3 ROUNDS \u00b7 $0"
              and chat_run.cost_text(1, 0.0002) == "1 ROUND \u00b7 $<0.001", chat_run.cost_text(3, 0.0))
        ran = []
        chat_run._call_soon(lambda: 1 / 0)
        chat_run._call_soon(lambda: ran.append(1))
        chat_run.tick()
        check("chat run: a failing queued call does not stop the rest", ran == [1])

        objects_before = len(scene.objects)
        gate = threading.Event()
        client.chat_llm = FakeLLM([], gate=gate, cancel=lambda: chat_run.STATE.status == "cancelled")
        client.balances = []
        check("chat run: second prompt starts", chat_run.start(context, "Make it night"), chat_run.STATE.error)
        client.chat_llm.waiting.wait(5)
        main_thread.tick()
        check("chat run: send is refused while running", not chat_run.start(context, "again"))
        worker = chat_run.worker()
        chat_run.STATE.reply, chat_run.STATE.changed = "the last run's reply", ["layout"]
        history = list(chat_run.STATE.history)
        pipeline.on_load_pre(None)
        st = chat_run.STATE
        check("chat run: opening a file cancels the chat and clears the bar, keeping the history",
              st.status == "idle" and not st.running and st.reply == "" and st.changed == [] and st.stages == {}
              and st.tools == [] and st.cost_text == "" and st.history == history and history,
              "%s %r %s" % (st.status, st.reply, st.stages))
        stopped_at = time.time()
        ended = _chat_drive(timeout=2)
        check("chat run: worker ends within 2 s of cancel", ended and not worker.is_alive(),
              "%.2f s" % (time.time() - stopped_at))
        check("chat run: nothing built after cancel, late events ignored",
              len(scene.objects) == objects_before and chat_run.STATE.status == "idle", chat_run.STATE.status)
        gate.set()

        gate = threading.Event()
        client.chat_llm = FakeLLM([code_reply(KIOSK_CODE)], gate=gate)
        chat_run.start(context, "One box")
        client.chat_llm.waiting.wait(5)
        main_thread.tick()
        objects_before = len(scene.objects)
        bpy.ops.eachlabs.chat_cancel()
        snapshot = dataclasses.asdict(chat_run.STATE)
        chat_run.STATE.error = "Stopped. What was built is kept."
        chat_run.dismiss()
        check("chat run: Keep the scene clears the bar's view", chat_run.STATE.status == "idle"
              and not chat_run.STATE.error and not chat_run.STATE.stages and not chat_run.STATE.tools)
        for key, value in snapshot.items():
            setattr(chat_run.STATE, key, value)
        gate.set()  # the request that was in flight answers after the cancel
        ended = _chat_drive(timeout=5)
        check("chat run: a late model answer after cancel builds nothing and changes no state",
              ended and len(scene.objects) == objects_before and dataclasses.asdict(chat_run.STATE) == snapshot,
              "%d -> %d objects" % (objects_before, len(scene.objects)))

        prefs = types.SimpleNamespace(api_key="fake-key", base_url="https://api.eachlabs.ai", poll_interval=2.0,
                                      timeout_minutes=60, chat_model="test/other-model", chat_total_rounds=20,
                                      chat_light_model=preferences.SAME_MODEL,
                                      chat_max_failures=3, chat_step_seconds=7, chat_code_consent="ALLOWED",
                                      texture_wait_seconds=111, concept_wait_seconds=112,
                                      model_reply_wait_seconds=77, download_wait_seconds=114)
        prefs_context = types.SimpleNamespace(scene=scene, preferences=types.SimpleNamespace(
            addons={"eachlabs": types.SimpleNamespace(preferences=prefs)}))
        client.log.clear()
        client.chat_sent.clear()
        client.chat_llm = FakeLLM([])
        chat_run.start(prefs_context, "Nothing new")
        step_seconds = chat_run._run.step_seconds
        run_waits = (chat_run._run.texture_seconds, chat_run._run.concept_seconds, chat_run._run.reply_seconds,
                     chat_run._run.download_seconds)
        _chat_drive()
        check("chat run: the four wait limits come from the preferences", run_waits == (111.0, 112.0, 77.0, 114.0),
              str(run_waits))
        check("chat run: every model call waits as long as the reply wait limit says",
              client.chat_sent and all(s["timeout"] == 77.0 for s in client.chat_sent), str(client.chat_sent[:2]))
        check("chat run: the step time limit comes from the preferences", step_seconds == 7
              and preferences.step_seconds(bpy.context) == 20, str(step_seconds))
        check("chat run: a run that changed nothing offers no undo", chat_run.STATE.status == "done"
              and chat_run.STATE.changed == [] and not bpy.ops.eachlabs.chat_undo_stage.poll(),
              "%s %s" % (chat_run.STATE.status, chat_run.STATE.changed))
        check("chat run: the model slug comes from the preferences",
              client.log and all(entry == ("chat", "test/other-model") for entry in client.log), str(client.log[:2]))
        check("chat run: a model without its own cap asks for 5000 tokens",
              client.chat_sent and all(s["max_tokens"] == 5000 for s in client.chat_sent), str(client.chat_sent[:2]))
        check("chat run: other models are asked for no reasoning in the check stage",
              any(s["reasoning"] is False for s in client.chat_sent), str([s["reasoning"] for s in client.chat_sent][-6:]))

        prefs.chat_model = "anthropic/claude-opus-5.5"
        client.log.clear()
        client.chat_sent.clear()
        client.chat_llm = FakeLLM([])
        chat_run.start(prefs_context, "Nothing new either")
        _chat_drive()
        check("chat run: an Anthropic model asks for 3000 tokens",
              client.chat_sent and all(s["max_tokens"] == 3000 for s in client.chat_sent), str(client.chat_sent[:2]))
        check("chat run: an Anthropic model is never asked to turn its reasoning off",
              client.chat_sent and all(s["reasoning"] is True for s in client.chat_sent), str(client.chat_sent))

        prefs.chat_model, prefs.chat_light_model = "test/other-model", preferences.DEFAULT_LIGHT_MODEL
        prefs.chat_quality = "PROTOTYPE"
        client.log.clear()
        client.chat_sent.clear()
        client.chat_llm = FakeLLM([])
        chat_run.start(prefs_context, "Nothing new in a draft")
        _chat_drive()
        check("chat run: Prototype sends every stage to the scene's model, light and materials too",
              client.log and all(e == ("chat", "test/other-model") for e in client.log), str(client.log[:8]))

        on_scene = chat_run.continues(scene)
        for obj in scene.objects:  # nothing selected: Assets adds
            obj.select_set(False, view_layer=scene.view_layers[0])
        chat_run.STATE.target = "asset"
        client.chat_llm = FakeLLM([])
        chat_run.start(prefs_context, "a wooden barrel")
        _chat_drive()
        asked = [str(m.get("content")) for call in client.chat_llm.messages for m in call if m.get("role") == "user"]
        check("chat run: an Assets run on a scene asks for one new thing and skips the light and the camera",
              on_scene and chat_run.STATE.status == "done" and "light" not in chat_run.STATE.stages
              and "camera" not in chat_run.STATE.stages
              and any("Add exactly one new thing to the scene: a wooden barrel" in a for a in asked),
              "%s %s %s" % (on_scene, chat_run.STATE.status, list(chat_run.STATE.stages)))
        chat_run.STATE.target = "scene"

        prefs.chat_quality = "ADVANCED"
        client.log.clear()
        client.chat_sent.clear()
        client.chat_llm = FakeLLM([])
        chat_run.start(prefs_context, "Nothing new again")
        _chat_drive()
        light = [s for e, s in zip(client.log, client.chat_sent) if e == ("chat", preferences.DEFAULT_LIGHT_MODEL)]
        check("chat run: the light and materials stages go to their own model, the rest to the scene's model",
              light and any(e == ("chat", "test/other-model") for e in client.log)
              and set(client.log) <= {("chat", "test/other-model"), ("chat", preferences.DEFAULT_LIGHT_MODEL)},
              str(client.log))
        check("chat run: the light and materials model gets its own reply cap",
              light and all(s["max_tokens"] == 3000 for s in light), str(light[:2]))

        scene2 = bpy.data.scenes.new("eachlabs_chat_retry")
        scene2.render.fps, scene2.render.fps_base = 24, 1.0
        context2 = types.SimpleNamespace(scene=scene2, preferences=bpy.context.preferences)
        bad = ("run_python", {"code": "# Camera\ncam = bpy.data.objects['No such camera']"})
        client.chat_llm = FakeLLM(STREET + [BAD_CAMERA, tool_reply(bad, bad)])  # three failures in two rounds
        client.balances = [5.0]
        chat_run.start(context2, "A street, camera for 5 seconds")
        _chat_drive()
        state = chat_run.STATE
        check("chat run: three camera failures leave the camera stage partly done and the run goes on",
              state.status == "done" and state.failed_stage == "camera" and state.stages["camera"] == "partial"
              and state.stages["check"] == "done", "%s %s %s" % (state.status, state.failed_stage, state.stages))
        check("chat run: cost is left out without a second balance", state.cost is None
              and "$" not in state.cost_text, state.cost_text)
        collection = [c.name for c in scene2.collection.children]
        check("chat run: retry is offered after a failed stage", bpy.ops.eachlabs.chat_retry_stage.poll())
        client.chat_llm = FakeLLM(CAMERA + CHECK + [text_reply("Fixed the camera.")])
        result = bpy.ops.eachlabs.chat_retry_stage()
        _chat_drive()
        state = chat_run.STATE
        check("chat run: retry runs camera and check to done", result == {"FINISHED"} and state.status == "done"
              and state.stages == {s: "done" for s in chat_loop.STAGES}, "%s %s" % (state.status, state.stages))
        check("chat run: retry builds in the same collection, one camera",
              [c.name for c in scene2.collection.children] == collection and len(collection) == 1
              and len(_chat_cameras(scene2)) == 1, "%s %d" % (collection, len(_chat_cameras(scene2))))
        check("chat run: undo, redo and update handlers are registered",
              chat_run.on_undo in bpy.app.handlers.undo_post and chat_run.on_undo in bpy.app.handlers.redo_post
              and chat_run.on_depsgraph in bpy.app.handlers.depsgraph_update_post)
        chat_run.STATE.changed = ["camera"]
        chat_run.on_undo(scene2)
        check("chat run: an undo outside the pill hides the Undo pill, the reply stays",
              chat_run.STATE.changed == [] and chat_run.STATE.status == "done")
    bpy.data.scenes.remove(scene2)
    reports = []
    fake = types.SimpleNamespace(report=lambda kind, text: reports.append(text))
    result = chat_run.EACHLABS_OT_chat_frame_result.execute(fake, bpy.context)
    check("chat run: frame result reports a deleted scene", result == {"CANCELLED"} and reports
          and "no longer exists" in reports[0], str(reports))
    chat_run.cancel(drop_build=True)
    bpy.data.scenes.remove(scene)


def test_chat_follow_up():
    """A second prompt changes the scene the first one built; New scene starts a new collection."""
    from eachlabs import chat_run, scene_build

    chat_run.cancel(drop_build=True)
    chat_run.reset_view()
    scene = bpy.data.scenes.new("eachlabs_follow_up")
    scene.render.fps, scene.render.fps_base = 24, 1.0
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)

    def chat_collections():
        return [c for c in scene.collection.children if c.get(scene_build.RUN)]

    with offline_api() as client:
        check("follow-up: no scene before the first prompt", not chat_run.continues(scene))
        client.chat_llm = FakeLLM(STREET + CAMERA + CHECK + [text_reply("A street.")])
        chat_run.start(context, "a street at dusk, slow dolly forward over 5 seconds")
        _chat_drive()
        first = chat_collections()
        first_ids = {o["eachlabs_id"] for o in scene.objects if o.get(scene_build.ID)}
        first_names = {o.name for o in scene.objects if o.get(scene_build.ID)}
        check("follow-up: the first prompt builds one collection", chat_run.STATE.status == "done"
              and len(first) == 1 and first_ids and chat_run.continues(scene), str([c.name for c in first]))

        client.chat_llm = FakeLLM([code_reply(KIOSK_CODE), text_reply("Added a kiosk.")])
        chat_run.start(context, "add windows to buildings")
        _chat_drive()
        sent = client.chat_llm.messages
        seen = _scene_in(sent[0])
        listed = {o["name"] for o in seen["objects"]} | {o["name"] for o in seen["lights"]}
        check("follow-up: read_scene of the second run lists what the first run built",
              first_names <= listed and seen["other_objects"] == 0
              and seen["camera"]["yours"] and seen["camera"]["name"] in first_names, "%d of %d, other %s" % (
                  len(first_names & listed), len(first_names), seen["other_objects"]))
        check("follow-up: the stages get the change instructions and the earlier prompt",
              sent[0][0]["content"] == chat_loop.system_text(chat_loop.FOLLOW_UP_INSTRUCTIONS["layout"],
                                                             bpy.app.version)
              and sent[0][1]["content"].startswith("Change request: add windows to buildings")
              and "- a street at dusk, slow dolly forward over 5 seconds" in sent[0][1]["content"],
              sent[0][1]["content"][:200])
        coll = chat_collections()
        new_box = [o for o in scene.objects if o.name.startswith("Kiosk") and o.get(scene_build.ID)]
        check("follow-up: the second prompt adds to the same collection, nothing is rebuilt",
              chat_run.STATE.status == "done" and coll == first and len(new_box) == 1
              and new_box[0].name in first[0].all_objects
              and {o["eachlabs_id"] for o in scene.objects if o.get(scene_build.ID)} == first_ids | {new_box[0]["eachlabs_id"]},
              "%s %d" % ([c.name for c in coll], len(new_box)))
        check("follow-up: stages with nothing to change push no undo step", chat_run.STATE.changed == ["layout"],
              str(chat_run.STATE.changed))
        from eachlabs import viewport_marks
        check("follow-up: the scene's camera path still shows when the follow-up leaves the camera",
              len(viewport_marks.camera_path()) == 2, str(viewport_marks.camera_path()))

        client.chat_llm = FakeLLM([])
        chat_run.start(context, "make it night")
        _chat_drive()
        body = client.chat_llm.messages[0][1]["content"]
        check("follow-up: earlier prompts are sent most recent first",
              body.index("- add windows to buildings") < body.index("- a street at dusk"), body[:240])

        cam = scene.camera
        start, end = scene.frame_start, scene.frame_end
        move = _scene_in(client.chat_llm.messages[0])["camera"].get("move_m")
        client.chat_llm = FakeLLM([code_reply("# Ten seconds\nscene.frame_end = scene.frame_start + 239"),
                                   text_reply("Longer.")])
        chat_run.start(context, "make the shot ten seconds long")
        _chat_drive()
        frames = sorted({round(k.co[0]) for fc in compat.object_fcurves(cam) if fc.data_path == "location"
                         for k in fc.keyframe_points})
        tool = [m["content"] for m in client.chat_llm.messages[1] if m["role"] == "tool"][0]
        seen = _scene_in(client.chat_llm.messages[2])["camera"]
        check("camera move: a follow-up that changes the frame range keeps a moving camera, stretched to the range",
              move and move >= 30 and scene.frame_end == start + 239 and frames == [start, start + 239]
              and seen["move_m"] == move and "The camera's move now spans the new frame range" in tool,
              "%s %s-%s %s %s" % (move, start, end, frames, seen))
        client.chat_llm = FakeLLM([code_reply("# Pull back\ncam = scene.camera\ncam.location = (0, -30, 4)\n"
                                              "cam.keyframe_insert(\"location\", frame=scene.frame_start)\n"
                                              "cam.keyframe_insert(\"location\", frame=scene.frame_end)"),
                                   text_reply("Pulled back.")])
        chat_run.start(context, "show more of the street")
        _chat_drive()
        sent = client.chat_llm.messages
        tool = [m["content"] for m in sent[1] if m["role"] == "tool"][0]
        camera_body = next(b[1]["content"] for b in sent if b[0]["content"] == chat_loop.system_text(
            chat_loop.FOLLOW_UP_INSTRUCTIONS["camera"], bpy.app.version))
        check("camera move: a step that keys one position at both frames is told it stopped the move, and the "
              "camera stage gets the problem",
              "Your step stopped the camera move" in tool
              and "The camera does not move although the scene had a camera move" in camera_body
              and _scene_in(sent[2])["camera"]["move_m"] == 0.0, tool[-300:])

        check("follow-up: New scene is offered after a finished run", bpy.ops.eachlabs.chat_new_scene.poll())
        result = bpy.ops.eachlabs.chat_new_scene()
        check("follow-up: New scene deletes nothing and clears the bar", result == {"FINISHED"}
              and chat_collections() == first and not chat_run.continues(scene) and chat_run.STATE.status == "idle")
        client.chat_llm = FakeLLM(STREET + [text_reply("x"), text_reply("y")])
        chat_run.start(context, "a harbour")
        _chat_drive()
        after = chat_collections()
        check("follow-up: after New scene the next prompt builds a new collection",
              len(after) == 2 and first[0] in after
              and client.chat_llm.messages[0][0]["content"] == chat_loop.system_text(chat_loop.INSTRUCTIONS["layout"],
                                                                                   bpy.app.version)
              and _scene_in(client.chat_llm.messages[0])["other_objects"] == len(first[0].all_objects),
              str([c.name for c in after]))

        newest = next(c for c in after if c != first[0])
        for obj in list(newest.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for child in list(newest.children_recursive):
            bpy.data.collections.remove(child)
        bpy.data.collections.remove(newest)
        check("follow-up: a deleted collection ends that build", not chat_run.continues(scene))
        client.chat_llm = FakeLLM(STREET + [text_reply("x"), text_reply("y")])
        chat_run.start(context, "a market")
        _chat_drive()
        check("follow-up: ... and the next prompt changes the earlier build still in the scene",
              client.chat_llm.messages[0][0]["content"] == chat_loop.system_text(
                  chat_loop.FOLLOW_UP_INSTRUCTIONS["layout"], bpy.app.version)
              and chat_collections() == first and chat_run.continues(scene), str(chat_collections()))
    chat_run.cancel(drop_build=True)
    chat_run.reset_view()
    for coll in chat_collections():
        for obj in list(coll.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for child in list(coll.children_recursive):
            bpy.data.collections.remove(child)
        bpy.data.collections.remove(coll)
    bpy.data.scenes.remove(scene)
