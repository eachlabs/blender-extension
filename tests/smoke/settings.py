"""Preferences: waits and limits, Code check, hidden settings and confirmations."""

import os
import tempfile
import threading
import time
import types

import bpy

from eachlabs import chat_loop, compat, main_thread, mcp_client, panels, preferences
from tests.blender_fakes import CAMERA, CHECK, FakeLLM, STREET, code_reply, offline_api, text_reply
from tests.smoke.chat_common import _chat_drive
from tests.smoke.common import WORK, _FakeLayout, check


def _wait_mcp(timeout=10):
    end = time.time() + timeout
    while time.time() < end and preferences.mcp_status["text"] == "Checking MCP\u2026":
        main_thread.tick()
        time.sleep(0.02)


def test_chat_settings():
    wait = preferences.EachlabsPreferences.bl_rna.properties.get("objects_3d_wait_minutes")
    props = preferences.EachlabsPreferences.__annotations__["objects_3d_wait_minutes"].keywords
    check("3D wait limit: a preference, 20 minutes by default, 3 to 60",
          props["name"] == "3D wait limit (min)" and props["default"] == 20 and props["min"] == 3
          and props["max"] == 60, "%s %s" % (props, wait))
    fake = types.SimpleNamespace(objects_3d_limit=2, objects_3d_wait_minutes=7)
    real_get = preferences.get_preferences
    try:
        preferences.get_preferences = lambda context=None: fake
        set_limits = preferences.objects_3d_limits()
    finally:
        preferences.get_preferences = real_get
    check("3D wait limit: the preference sets each job's limit in seconds",
          set_limits == (2, 420.0) and preferences.objects_3d_limits()[1] == 1200.0, str(set_limits))
    waits = {"texture_wait_seconds": ("Texture wait (s)", 240, 30, 900),
             "concept_wait_seconds": ("Concept picture wait (s)", 120, 30, 600),
             "model_reply_wait_seconds": ("Model reply wait (s)", 120, 30, 600),
             "download_wait_seconds": ("Download wait (s)", 120, 30, 600)}
    for key, (label, default, low, high) in waits.items():
        props = preferences.EachlabsPreferences.__annotations__[key].keywords
        real = preferences.EachlabsPreferences.bl_rna.properties.get(key)
        check("%s: a preference, %d by default, %d to %d" % (label, default, low, high),
              (props["name"], props["default"], props["min"], props["max"]) == (label, default, low, high)
              and real is not None and real.default == default and real.hard_min == low and real.hard_max == high
              and props["description"].strip(), str(props))
        check("%s: the settings check covers it" % label, key in preferences.EachlabsPreferences.bl_rna.properties
              and key not in preferences.NOT_SETTINGS, key)
    fake = types.SimpleNamespace(texture_wait_seconds=61, concept_wait_seconds=62, model_reply_wait_seconds=63,
                                 download_wait_seconds=64)
    try:
        preferences.get_preferences = lambda context=None: fake
        set_waits = preferences.wait_limits()
        preferences.get_preferences = lambda context=None: types.SimpleNamespace()
        bare_waits = preferences.wait_limits()
        preferences.get_preferences = lambda context=None: None
        none_waits = preferences.wait_limits()
    finally:
        preferences.get_preferences = real_get
    check("wait limits: each preference sets its own number of seconds", set_waits == (61.0, 62.0, 63.0, 64.0),
          str(set_waits))
    check("wait limits: the module defaults when preferences are missing or unset",
          bare_waits == none_waits == (240.0, 120.0, 120.0, 120.0), "%s %s" % (bare_waits, none_waits))
    from eachlabs import chat_run

    stub = types.SimpleNamespace(
        textures_limit=3, build=types.SimpleNamespace(owns=lambda m: True, textures={}), jobs=[], request="",
        client=types.SimpleNamespace(api_key="k", base_url="https://api.invalid"), texture_seconds=111.0,
        concept_seconds=112.0, download_seconds=114.0, cancel=threading.Event(), secrets=(), concept_folder="",
        objects_timeout=1200.0)
    seen, added = {}, []
    real_draw, real_cache, real_rows, real_gen = (chat_run.generation.draw, chat_run.cache_folder, chat_run._objects_rows,
                                                  chat_run.GEN)
    material = bpy.data.materials.new("eachlabs_wait_check")
    try:
        chat_run.generation.draw = lambda *a, **kw: seen.update(kw) or (_ for _ in ()).throw(RuntimeError("stop"))
        chat_run.cache_folder = lambda: tempfile.mkdtemp()
        chat_run._objects_rows = lambda run: None
        chat_run.GEN = types.SimpleNamespace(add=added.append, emitter=lambda job_id: None)
        chat_run.queue_texture(stub, {"material": material.name, "description": "wait check brick"})
        chat_run._concept(stub, "a street", lambda event: None)
    finally:
        chat_run.generation.draw, chat_run.cache_folder, chat_run._objects_rows, chat_run.GEN = (
            real_draw, real_cache, real_rows, real_gen)
        bpy.data.materials.remove(material)
    spec = added[0].context.get("spec") if added else None
    check("texture wait and download wait reach the texture's job",
          spec is not None and (spec.timeout_s, spec.download_s) == (111.0, 114.0), str(spec))
    check("concept wait and download wait reach the concept picture",
          (seen.get("timeout_s"), seen.get("download_s")) == (112.0, 114.0), str(seen))
    limits = preferences.chat_limits(bpy.context)
    check("chat limits default to 15 rounds, the per-stage budgets and 3 failures",
          limits == chat_loop.Limits() and limits.total_rounds == 15 and limits.max_failures == 3
          and [limits.rounds_for(s) for s in chat_loop.STAGES] == [4, 3, 3, 3, 2], repr(limits))
    panel_context = types.SimpleNamespace(
        preferences=types.SimpleNamespace(addons={}, system=types.SimpleNamespace(ui_scale=1.0)), region=None)  # Background UI scale is 0.
    real_problem, real_check = compat.online_problem, mcp_client.check
    try:
        compat.online_problem = lambda: "Online access is off (test)."
        bpy.ops.eachlabs.check_mcp()
        check("check_mcp offline reports the offline message",
              preferences.mcp_status["ok"] is False and preferences.mcp_status["text"] == "Online access is off (test).",
              repr(preferences.mcp_status))
        compat.online_problem = lambda: None
        with offline_api():
            mcp_client.check = lambda base_url, api_key: (True, "MCP connected") if api_key == "fake-key" else (False, "no key")
            bpy.ops.eachlabs.check_mcp()
            check("check_mcp shows checking first", preferences.mcp_status["text"] == "Checking MCP\u2026",
                  repr(preferences.mcp_status))
            _wait_mcp()
            check("check_mcp ends with the check result",
                  preferences.mcp_status == {"ok": True, "text": "MCP connected"}, repr(preferences.mcp_status))
            log = []
            panels.draw_status(_FakeLayout(log), panel_context)
            check("panel draws the MCP line and refresh button",
                  ("label", "MCP connected") in log and ("operator", "eachlabs.check_mcp") in log, repr(log))
            preferences.mcp_status.update(ok=None, text="")
            log = []
            panels.draw_status(_FakeLayout(log), panel_context)
            check("panel shows MCP not checked", ("label", "MCP not checked") in log, repr(log))
    finally:
        compat.online_problem, mcp_client.check = real_problem, real_check
        preferences.mcp_status.update(ok=None, text="")


def test_code_check():
    from eachlabs import chat_run

    prefs_cls = next(c for c in preferences.CLASSES if issubclass(c, bpy.types.AddonPreferences))
    check("code check: Preferences property defaults to False",
          prefs_cls.bl_rna.properties["chat_code_check"].default is False
          and prefs_cls.bl_rna.properties["chat_code_check"].name == "Code check")
    check("code check: off without preferences", preferences.code_check(types.SimpleNamespace(
        preferences=types.SimpleNamespace(addons={}))) is False)

    panel_context = types.SimpleNamespace(
        preferences=types.SimpleNamespace(addons={}, system=types.SimpleNamespace(ui_scale=1.0)), region=None)
    real = preferences.get_preferences
    props = []

    class Layout(_FakeLayout):
        def prop(self, data, name, **kwargs):
            props.append(name)

    log = []
    try:
        preferences.get_preferences = lambda context=None: types.SimpleNamespace(
            chat_code_check=False, api_key="fake-key", base_url="https://api.eachlabs.ai", poll_interval=2.0,
            timeout_minutes=60)
        panels.draw_status(Layout(log), panel_context)
    finally:
        preferences.get_preferences = real
    check("code check: the sidebar shows the switch and its hint", "chat_code_check" in props
          and "Checks the chat's Blender Python before it runs." in " ".join(
              t for kind, t in log if kind == "label"), repr((props, log)))

    scene = bpy.data.scenes.new("eachlabs_code_check")
    scene.render.fps, scene.render.fps_base = 24, 1.0
    prefs = types.SimpleNamespace(api_key="fake-key", base_url="https://api.eachlabs.ai", poll_interval=2.0,
                                  timeout_minutes=60, chat_model="m", chat_total_rounds=20,
                                  chat_max_failures=3, chat_step_seconds=20, chat_code_check=True,
                                  chat_code_consent="ALLOWED")
    context = types.SimpleNamespace(scene=scene, preferences=types.SimpleNamespace(
        addons={"eachlabs": types.SimpleNamespace(preferences=prefs)}))
    refuse = text_reply('{"allow": false, "reason": "It would change your files."}')
    allow = text_reply('{"allow": true, "reason": ""}')
    first = "# first box\nobj = bpy.data.objects.new('CheckFirst', None)\nscene.collection.objects.link(obj)"
    second = "# second box\nobj = bpy.data.objects.new('CheckSecond', None)\nscene.collection.objects.link(obj)"
    with offline_api() as client:
        client.balances = [10.0, 9.99]
        client.chat_llm = FakeLLM([code_reply(first), refuse, code_reply(second), allow, text_reply("Layout done.")])
        chat_run.start(context, "Two empties")
        on = chat_run.STATE.code_check_on
        _chat_drive()
        names = {o.name for o in scene.objects}
        check("code check: a refused step does not run, the allowed one does",
              on and "CheckFirst" not in names and "CheckSecond" in names, repr(sorted(names)))
        told = [c for m in client.chat_llm.messages for x in m if x.get("role") == "tool"
                for c in [x["content"]] if "Code check" in c]
        check("code check: the model is told why",
              any(c.startswith("ERROR: Code check: It would change your files.") for c in told), repr(told))

        prefs.chat_code_check = False
        client.balances = [10.0, 9.99]
        client.chat_llm = FakeLLM([code_reply(first.replace("CheckFirst", "CheckThird")), text_reply("ok")])
        chat_run.start(context, "One more")
        off = chat_run.STATE.code_check_on
        _chat_drive()
        from eachlabs import code_review
        reviews = [m for m in client.chat_llm.messages if code_review.SYSTEM_PROMPT[:60] in str(m[0].get("content"))]
        check("code check: off makes no review call and the step runs", not off
              and "CheckThird" in {o.name for o in scene.objects} and not reviews,
              "%d calls, %d reviews" % (client.chat_llm.calls, len(reviews)))

        prefs.chat_code_check = True
        cube = bpy.data.objects.new("Cube", None)
        scene.collection.objects.link(cube)
        cube.location = (1, 2, 3)
        edit = "# move the cube\nbpy.data.objects['Cube'].location = (9, 9, 9)"
        client.balances = [10.0, 9.99]
        client.chat_llm = FakeLLM([code_reply(edit), refuse, text_reply("ok")])
        chat_run.start(context, "Move the cube")
        _chat_drive()
        review_msg = next((m[1]["content"] for m in client.chat_llm.messages
                           if m and "Code to review" in m[1].get("content", "")), "")
        names_line = next((ln for ln in review_msg.splitlines() if ln.startswith("What the assistant created")), "")
        check("code check: a step that edits a person's object is reviewed with the chat's names and refused",
              tuple(cube.location) == (1.0, 2.0, 3.0) and "CheckSecond" in names_line
              and '"Cube"' not in names_line and "Code check" in "".join(
                  x["content"] for m in client.chat_llm.messages for x in m if x.get("role") == "tool"),
              repr((tuple(cube.location), names_line)))


def test_confirmations():
    """Every action that removes, undoes or stops something asks first when it is invoked (a click), and the
    dialog's Cancel runs nothing; a script call (EXEC_DEFAULT) runs at once. Background Blender invokes no
    operator, so each ``invoke`` is called as a click would; tests/gui_check.py clicks the real dialog."""
    from eachlabs import chat_run, confirm, jobs, operators, pipeline
    from eachlabs.ui import tokens

    def invoke(cls, **props):
        """``cls.invoke`` as a click calls it; the dialog's answer is Cancel."""
        op = types.SimpleNamespace(bl_idname=cls.bl_idname, **props)
        return cls.invoke(op, bpy.context, None)

    seen = []
    real = confirm.ask
    confirm.ask = lambda operator, context, event, title, message, button: (
        seen.append((operator.bl_idname, title, message, button)) or {"CANCELLED"})  # the person pressed Cancel
    scene = bpy.data.scenes.new("eachlabs_confirm")
    window_scene = bpy.context.window.scene if bpy.context.window else None
    try:
        with offline_api() as client:
            client.chat_llm, client.balances = FakeLLM(STREET + CAMERA + CHECK), [5.0, 5.0]
            context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
            chat_run.new_scene()
            chat_run.start(context, "a street")
            _chat_drive()
            stages, build = dict(chat_run.STATE.stages), chat_run._build
            result = invoke(chat_run.EACHLABS_OT_chat_new_scene)
            check("confirm: New scene asks first, and Cancel keeps the scene the chat changes",
                  result == {"CANCELLED"} and seen[-1][1:] == tokens.CONFIRM_NEW_SCENE
                  and chat_run._build is build and chat_run.STATE.stages == stages, str(seen[-1:]))
            undoable = chat_run.undoable_stages()
            if undoable:
                result = invoke(chat_run.EACHLABS_OT_chat_undo_stage)
                check("confirm: Undo stage names the stage it undoes, and Cancel undoes nothing",
                      result == {"CANCELLED"} and seen[-1][1] == "Undo the %s stage?" % undoable[-1]
                      and chat_run.STATE.stages == stages, str(seen[-1:]))
            else:  # background mode has no undo steps: the dialog's text is checked directly
                check("confirm: Undo stage names the stage it undoes",
                      tokens.CONFIRM_UNDO_STAGE[0] % "camera" == "Undo the camera stage?")
        os.environ[preferences.USER_DIR_ENV] = os.path.join(WORK, "user")
        path = os.path.join(preferences.user_folder("3d-cache"), "kept.glb")
        with open(path, "wb") as fh:
            fh.write(b"x" * 64)
        result = invoke(preferences.EACHLABS_OT_clear_3d_cache)
        check("confirm: Clear generated files asks first, and Cancel deletes nothing",
              result == {"CANCELLED"} and seen[-1][1:] == tokens.CONFIRM_CLEAR_FILES and os.path.exists(path))
        result = bpy.ops.eachlabs.clear_3d_cache()
        check("confirm: a script call of Clear generated files runs at once", result == {"FINISHED"}
              and not os.path.exists(path))

        running = pipeline.REGISTRY.add(jobs.Job("confirm-run", "VIDEO", "Clip", "VIDEO"))
        running.state = jobs.RUNNING
        local = pipeline.REGISTRY.add(jobs.Job("confirm-local", "VIDEO", "Clip", "VIDEO"))
        local.state = jobs.RENDERING
        done = pipeline.REGISTRY.add(jobs.Job("confirm-done", "VIDEO", "Clip", "VIDEO"))
        done.state = jobs.DONE
        result = invoke(operators.EACHLABS_OT_cancel_job, job_id="confirm-run")
        check("confirm: stopping a job that runs on each::labs asks first and says the spend is not refunded",
              result == {"CANCELLED"} and seen[-1][1:] == tokens.CONFIRM_CANCEL_JOB
              and "not refunded" in seen[-1][2] and running.state == jobs.RUNNING)
        invoke(operators.EACHLABS_OT_cancel_job, job_id="confirm-local")
        check("confirm: stopping a job that only renders here says nothing is billed",
              seen[-1][1:] == tokens.CONFIRM_CANCEL_LOCAL and local.state == jobs.RENDERING)
        result = invoke(operators.EACHLABS_OT_clear_jobs)
        check("confirm: Clear finished asks first, and Cancel keeps the finished jobs",
              result == {"CANCELLED"} and seen[-1][1:] == tokens.CONFIRM_CLEAR_JOBS
              and pipeline.REGISTRY.get("confirm-done") is not None)
        for job in (running, local):
            job.state = jobs.CANCELLED
        result = bpy.ops.eachlabs.clear_jobs()
        check("confirm: a script call of Clear finished runs at once",
              result == {"FINISHED"} and pipeline.REGISTRY.get("confirm-done") is None)
        before = len(seen)
        stop = types.SimpleNamespace(bl_idname="eachlabs.chat_cancel", execute=lambda context: {"FINISHED"})
        check("confirm: Stop with nothing paid being made stops at once, without a dialog",
              not chat_run.paid_running() and chat_run.EACHLABS_OT_chat_cancel.invoke(stop, bpy.context, None)
              == {"FINISHED"} and len(seen) == before)
        check("confirm: every dialog says what happens and what stays, and has its own button",
              all(len(t) == 3 and t[0].endswith("?") and len(t[1]) > 40 and t[2] for t in (
                  tokens.CONFIRM_NEW_SCENE, tokens.CONFIRM_UNDO_STAGE, tokens.CONFIRM_STOP_PAID,
                  tokens.CONFIRM_CLEAR_FILES, tokens.CONFIRM_CANCEL_JOB, tokens.CONFIRM_CANCEL_LOCAL,
                  tokens.CONFIRM_CLEAR_JOBS)))
    finally:
        confirm.ask = real
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        if bpy.context.window and window_scene is not None:
            bpy.context.window.scene = window_scene
        bpy.data.scenes.remove(scene)


TEST_KEY = "test-only-key-0000"  # a fake key; nothing here goes online
PREFS_CODE = 'prefs = bpy.context.preferences.addons["eachlabs"].preferences\n'


class _FilterSkipped:
    """Test only: let steps through without the rule filter, to act like a step that got past it."""

    def __enter__(self):
        from eachlabs import code_check
        self.real = code_check.check
        code_check.check = lambda code: None

    def __exit__(self, *exc):
        from eachlabs import code_check
        code_check.check = self.real
        return False


def _settings(prefs):
    return {name: getattr(prefs, name) for name in preferences.setting_names(prefs)}


def test_hidden_settings():
    """The key is empty in the preferences while a step runs, and a step that changes a setting stops the run."""
    from eachlabs import chat_run, code_runner, scene_build
    from eachlabs.ui import bar_state, tokens
    from eachlabs.ui.text_field import TextField

    addon = bpy.context.preferences.addons.new()
    addon.module = "eachlabs"
    prefs = preferences.get_preferences(bpy.context)
    seen = bpy.app.driver_namespace
    scene = bpy.data.scenes.new("eachlabs_hidden")
    try:
        prefs.api_key, prefs.chat_code_check, prefs.chat_code_consent = TEST_KEY, True, "ALLOWED"
        before = _settings(prefs)
        names = set(before)
        check("hidden key: the settings list holds the key, the API address, Code check, consent and the limits",
              {"api_key", "base_url", "chat_code_check", "chat_code_consent", "chat_total_rounds",
               "chat_step_seconds", "chat_max_failures"} <= names and "bl_idname" not in names, str(sorted(names)))
        build = scene_build.SceneBuild(scene, "hidden01")
        with _FilterSkipped():
            seen.pop("eachlabs_seen", None)
            result = build.execute("run_python", {"code": PREFS_CODE + 'bpy.app.driver_namespace["eachlabs_seen"] = '
                                                  '(prefs.api_key, prefs.base_url)\nbpy.data.objects.new("e", None)'})
            check("hidden key: the step reads an empty key and the real address",
                  seen.get("eachlabs_seen") == ("", before["base_url"]), repr(seen.get("eachlabs_seen")))
            check("hidden key: after a normal step the key is back and no setting changed",
                  result.get("ok") and _settings(prefs) == before, str(result)[:200])
            result = code_runner.run(PREFS_CODE + 'bpy.app.driver_namespace["eachlabs_seen"] = prefs.api_key\n1 / 0',
                                     build)
            check("hidden key: back after a step that fails", not result.get("ok")
                  and "ZeroDivisionError" in result.get("error", "") and seen["eachlabs_seen"] == ""
                  and _settings(prefs) == before, str(result)[:200])
            result = code_runner.run(PREFS_CODE + 'bpy.app.driver_namespace["eachlabs_seen"] = prefs.api_key\n'
                                     'while True:\n    pass', build, limit_s=0.5)
            check("hidden key: back after a step that hits the time limit", "TimeoutError" in result.get("error", "")
                  and seen["eachlabs_seen"] == "" and _settings(prefs) == before, str(result)[:200])
            for label, code in (("changes the API address", 'prefs.base_url = "https://example.invalid"'),
                                ("turns Code check off", "prefs.chat_code_check = False"),
                                ("writes the key", 'prefs.api_key = "chosen-by-the-step"'),
                                ("raises the round limit", "prefs.chat_total_rounds = 16")):
                try:
                    code_runner.run(PREFS_CODE + code, build)
                    stopped = None
                except chat_loop.StopRun as exc:
                    stopped = str(exc)
                check("hidden key: a step that %s stops with the settings error, every setting back" % label,
                      stopped == tokens.SETTINGS_CHANGED and _settings(prefs) == before, repr(stopped))

            with offline_api() as client:
                context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
                normal = code_reply("# a post\n" + PREFS_CODE + 'bpy.app.driver_namespace["eachlabs_seen"] = '
                                    'prefs.api_key\nbpy.data.objects.new("eachlabs_post", None)')
                change = code_reply("# a switch\n" + PREFS_CODE + "prefs.chat_code_check = True")
                client.chat_llm = FakeLLM([normal, text_reply("A post."), change, text_reply("never asked")])
                client.balances = [1.0, 1.0]
                prefs.chat_code_check = False  # no review calls in this run; the step turns it on
                prefs.objects_3d, prefs.reference_pictures = "OFF", False  # no plan call either
                measured = chat_loop.placement_problems  # the bare empty would get a fix stage; not this test's
                chat_loop.placement_problems = lambda found: {}
                prefs.concept_picture, prefs.textures_limit = False, 0  # and no plan for the looks
                before = _settings(prefs)
                seen["eachlabs_seen"] = None
                started = chat_run.start(context, "a post, then a switch")
                ended = _chat_drive()
                chat_loop.placement_problems = measured
                state = chat_run.STATE
                check("hidden key: a chat run continues after a normal step and stops at the step that changes "
                      "a setting", started and ended and state.stages.get("layout") == "done"
                      and state.status == "stopped" and state.failed_stage == "materials"
                      and state.error == tokens.SETTINGS_CHANGED and seen["eachlabs_seen"] == "",
                      "%s %s %s %r" % (state.status, state.stages, state.error, seen["eachlabs_seen"]))
                check("hidden key: the model got no answer to that step and no further round",
                      client.chat_llm.calls == 3 and len(client.chat_llm.replies) == 1, str(client.chat_llm.calls))
                check("hidden key: every setting is back after the run", _settings(prefs) == before)
                bar = bar_state.from_chat(state, TextField([], mac=False), False, time.monotonic())
                check("hidden key: the bar offers Show code and New scene", bar.mode == "stopped"
                      and bar.actions == ["code", "new"], "%s %s" % (bar.mode, bar.actions))

                def stop():
                    seen["eachlabs_seen"] = prefs.api_key
                    chat_run.cancel()
                seen["eachlabs_stop"] = stop
                chat_run.new_scene()
                client.chat_llm = FakeLLM([code_reply(PREFS_CODE + 'bpy.app.driver_namespace["eachlabs_stop"]()')])
                client.balances = [1.0, 1.0]
                started = chat_run.start(context, "stop during a step")
                ended = _chat_drive()
                check("hidden key: back after Stop pressed during a step", started and ended
                      and chat_run.STATE.status == "cancelled" and seen["eachlabs_seen"] == ""
                      and _settings(prefs) == before, "%s %r" % (chat_run.STATE.status, seen["eachlabs_seen"]))
    finally:
        for name in ("eachlabs_seen", "eachlabs_stop"):
            seen.pop(name, None)
        chat_run.cancel(drop_build=True)
        chat_run.reset_view()
        bpy.data.scenes.remove(scene)
        bpy.context.preferences.addons.remove(addon)
