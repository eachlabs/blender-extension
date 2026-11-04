"""What the bar offers after each kind of run."""

import threading
import time
import types

import bpy

from eachlabs import chat_loop, compat, preferences
from tests.blender_fakes import FakeLLM, KIOSK_CODE, code_reply, offline_api, text_reply, tool_reply
from tests.smoke.chat_common import _HeldLLM, _chat_drive, _tick_until
from tests.smoke.common import _FakeLayout, check


def test_next_steps():
    """Consent, Show code, and the bar's next step after a round limit or a lost scene."""
    from eachlabs import chat_run, overlay, thread_safety
    from eachlabs.ui import bar_state

    prefs_cls = next(c for c in preferences.CLASSES if issubclass(c, bpy.types.AddonPreferences))
    prop = prefs_cls.bl_rna.properties["chat_code_consent"]
    check("consent: a saved preference, UNSET until the person answers",
          prop.default == "UNSET" and [i.identifier for i in prop.enum_items] == ["UNSET", "ALLOWED"])
    for answer, check_on in (("check", True), ("plain", False)):
        fake = types.SimpleNamespace(chat_code_consent="UNSET", chat_code_check=False)
        ctx = types.SimpleNamespace(preferences=types.SimpleNamespace(
            addons={"eachlabs": types.SimpleNamespace(preferences=fake)}, is_dirty=False))
        before = preferences.code_allowed(ctx)
        preferences.allow_code(ctx, code_check_on=answer == "check")
        check("consent: %s stores ALLOWED, Code check %s, preferences marked to save"
              % (answer, "on" if check_on else "unchanged"),
              not before and preferences.code_allowed(ctx) and fake.chat_code_consent == "ALLOWED"
              and fake.chat_code_check is check_on and ctx.preferences.is_dirty, repr(fake))

    log = []
    fake_self = types.SimpleNamespace(layout=_FakeLayout(log), api_key="k", show_advanced=False)
    panel_context = types.SimpleNamespace(
        preferences=types.SimpleNamespace(addons={}, system=types.SimpleNamespace(ui_scale=1.0)), region=None)
    prefs_cls.draw(fake_self, panel_context)
    labels = [t for kind, t in log if kind == "label"]
    shown = " ".join(labels)
    check("preferences: Code check's text shows wrapped under the switch",
          preferences.CODE_CHECK_TEXT in shown and not any(preferences.CODE_CHECK_TEXT == t for t in labels),
          repr(labels))
    for consent, button in (("UNSET", False), ("ALLOWED", True)):
        log = []
        fake_self = types.SimpleNamespace(layout=_FakeLayout(log), api_key="k", show_advanced=False,
                                          chat_code_consent=consent)
        prefs_cls.draw(fake_self, panel_context)
        check("preferences: %s shows %s" % (consent, "Ask before building again" if button else "the plain line"),
              (("operator", "eachlabs.ask_consent_again") in log) is button
              and (("label", preferences.CONSENT_UNSET_TEXT) in log) is not button, repr(log[-6:]))

    scene = bpy.data.scenes.new("eachlabs_next_steps")
    scene.render.fps, scene.render.fps_base = 24, 1.0
    prefs = types.SimpleNamespace(api_key="fake-key", base_url="https://api.eachlabs.ai", poll_interval=2.0,
                                  timeout_minutes=60, chat_model="m", chat_total_rounds=20, chat_max_failures=3,
                                  chat_step_seconds=20, chat_code_check=False, chat_code_consent="ALLOWED")
    context = types.SimpleNamespace(scene=scene, preferences=types.SimpleNamespace(
        addons={"eachlabs": types.SimpleNamespace(preferences=prefs)}))
    keyed = "# a lamp\nlabel = 'fake-key'\n" + KIOSK_CODE.split("\n", 1)[1]
    with offline_api() as client:
        client.balances = [10.0, 9.99]
        client.chat_llm = FakeLLM([code_reply(keyed), text_reply("Layout done.")])
        chat_run.start(context, "A kiosk")
        _chat_drive()
        text, _message = chat_run.show_code(bpy.context)
        body = text.as_string()
        check("show code: the run's steps go to the Eachlabs code text, one section per step, key redacted",
              text.name == "Eachlabs code" and "# ---- Step 1 \u00b7 Layout \u00b7 ran ----" in body
              and "fake-key" not in body and "[redacted]" in body and "Kiosk" in body, body[:300])
        state = bar_state.from_chat(chat_run.STATE, overlay.FIELD, False, time.monotonic(), has_scene=True)
        check("show code: done offers Show code before New scene", state.actions[-2:] == ["code", "new"],
              str(state.actions))

        prefs.chat_total_rounds = 2
        client.balances = []
        client.chat_llm = FakeLLM([code_reply(KIOSK_CODE)] + [tool_reply(("read_scene", {}))] * 3)
        chat_run.start(context, "more lamps")
        _chat_drive()
        st = chat_run.STATE
        state = bar_state.from_chat(st, overlay.FIELD, False, time.monotonic(), has_scene=chat_run.continues(scene))
        check("round limit: the run ends as done with its usual actions",
              st.status == "done" and st.reply.startswith("Stopped after 2 rounds. What was built is kept.\n"
                                                         "Materials: skipped, the round limit was reached.")
              and not st.unchanged and state.mode == "done" and state.actions[:2] == ["play", "frame"],
              "%s %r" % (st.status, st.reply))
        prefs.chat_total_rounds = 20
        client.chat_llm = FakeLLM([text_reply("ok")])
        follow = chat_run.continues(scene)
        chat_run.start(context, "keep going")
        earlier = list(chat_run._run.earlier)
        _chat_drive()
        check("round limit: a follow-up continues the scene", follow and earlier[:1] == ["more lamps"], str(earlier))
        st = chat_run.STATE
        state = bar_state.from_chat(st, overlay.FIELD, False, time.monotonic(), has_scene=True)
        check("nothing changed: a done run that built nothing says so and offers Retry, not only the reply",
              st.status == "done" and st.unchanged and state.mode == "done"
              and state.error == bar_state.T.NOTHING_CHANGED and state.actions[0] == "retry"
              and "play" not in state.actions and chat_run.EACHLABS_OT_chat_retry_stage.poll(bpy.context),
              "%s %s %s" % (st.status, st.unchanged, state.actions))
        body = chat_run.code_text()
        heads = [line for line in body.splitlines() if line.startswith("# ==== Prompt")]
        check("show code: every prompt of the scene has its own section, newest last",
              heads == ["# ==== Prompt 1: A kiosk ====", "# ==== Prompt 2: more lamps ====",
                        "# ==== Prompt 3: keep going ===="]
              and body.index("# ---- Step 1 \u00b7 Layout \u00b7 ran ----") < body.index(heads[1])
              and "Kiosk" in body and "fake-key" not in body, body[:400])

        prompts = list(chat_run._build.prompts)
        client.chat_llm = FakeLLM([tool_reply(("run_python", {"code": "# only looks\nprint(len(scene.objects))"}))])
        retried = chat_run.EACHLABS_OT_chat_retry_stage.execute(types.SimpleNamespace(report=print), context)
        earlier, stages = list(chat_run._run.earlier), chat_run.STATE.stages
        _chat_drive()
        st = chat_run.STATE
        state = bar_state.from_chat(st, overlay.FIELD, False, time.monotonic(), has_scene=True)
        check("nothing changed: Retry sends the prompt again to every stage of the same scene",
              retried == {"FINISHED"} and earlier == prompts[1:] and list(chat_run._build.prompts) == prompts
              and set(stages) - {"fix"} == set(chat_loop.STAGES),  # "more lamps" laid a second kiosk over the first
              "%s %s %s %s %s" % (retried, earlier, prompts, list(chat_run._build.prompts), list(stages)))
        check("nothing changed: a step that only printed changed nothing; the bar keeps Show code",
              st.status == "done" and st.unchanged and state.actions[:1] == ["retry"] and "code" in state.actions,
              "%s %s" % (st.unchanged, state.actions))

        coll = bpy.data.collections.get(chat_run._build.collection_name)
        held = _HeldLLM([], lambda: chat_run.STATE.status != "running")
        client.chat_llm = held
        chat_run.start(context, "another kiosk")
        held.held.wait(5)
        _tick_until(lambda: chat_run._run.had_collection, 1.0)
        for obj in list(coll.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for child in list(coll.children_recursive):
            bpy.data.collections.remove(child)
        bpy.data.collections.remove(coll)
        idle = _tick_until(lambda: chat_run.STATE.status == "idle")
        check("lost run: deleting the run's collection mid-run returns the bar to idle",
              idle and not chat_run.STATE.running and chat_run._build is None, chat_run.STATE.status)
        held.release.set()
        _chat_drive()

        other = bpy.data.scenes.new("eachlabs_lost_scene")
        lost_context = types.SimpleNamespace(scene=other, preferences=context.preferences)
        held = _HeldLLM([], lambda: chat_run.STATE.status != "running")
        client.chat_llm = held
        chat_run.start(lost_context, "a kiosk")
        held.held.wait(5)
        bpy.data.scenes.remove(other)
        idle = _tick_until(lambda: chat_run.STATE.status == "idle")
        state = bar_state.from_chat(chat_run.STATE, overlay.FIELD, False, time.monotonic())
        check("lost run: deleting the run's scene mid-run returns the bar to idle",
              idle and not chat_run.STATE.running and state.mode == "idle", chat_run.STATE.status)
        held.release.set()
        _chat_drive()

        prefs.chat_code_consent = "UNSET"
        reports, asked = [], []
        real_ask, real_online = chat_run.ask_consent, compat.online_problem
        op = type("Op", (), {"report": lambda self, kind, text: reports.append(text), "prompt": "a lamp",
                             "use_last": False, "asked": False, "code_check": False})()
        client.chat_llm = FakeLLM([code_reply(KIOSK_CODE)])
        try:
            compat.online_problem = lambda: "Online access is off."
            refused = chat_run.start(context, "a lamp")
            compat.online_problem = real_online
            offered = chat_run.EACHLABS_OT_chat_retry_stage.poll(context)
            chat_run.ask_consent = lambda prompt: asked.append(prompt) or True
            result = chat_run.EACHLABS_OT_chat_retry_stage.execute(op, context)
            check("consent: an offline refusal, online on, then Retry opens the card and runs nothing",
                  not refused and offered and result == {"CANCELLED"} and asked == ["a lamp"] and not reports
                  and not chat_run.STATE.running and client.chat_llm.calls == 0
                  and prefs.chat_code_consent == "UNSET", "%s %s %r %r" % (refused, offered, asked, reports))

            chat_run.ask_consent = None  # no bar drawn: every way in refuses with a plain error
            outcomes = {"start": chat_run.start(context, "a lamp") is False
                        and chat_run.STATE.error == chat_run.NO_CONSENT}
            outcomes["sidebar send"] = (chat_run.EACHLABS_OT_chat_send.execute(op, context) == {"CANCELLED"}
                                        and reports[-1:] == [chat_run.NO_CONSENT])
            chat_run.STATE.attempt = "a lamp"
            outcomes["retry"] = (chat_run.EACHLABS_OT_chat_retry_stage.execute(op, context) == {"CANCELLED"}
                                 and reports[-1:] == [chat_run.NO_CONSENT])
            real_checked, overlay.UI["mcp_checked"] = overlay.UI["mcp_checked"], True
            overlay.FIELD.clear()
            overlay.FIELD.paste("a lamp")
            outcomes["bar send"] = overlay.submit(context) is False and overlay.UI["consent"]
            overlay.UI["consent"], overlay.UI["mcp_checked"] = False, real_checked
            overlay.FIELD.clear()
            check("consent: while UNSET every way to start refuses and runs nothing",
                  all(outcomes.values()) and not chat_run.STATE.running and client.chat_llm.calls == 0
                  and prefs.chat_code_consent == "UNSET", repr(outcomes))

            prefs.chat_code_consent, asked[:] = "ALLOWED", []
            context.preferences.is_dirty = False
            result = preferences.EACHLABS_OT_ask_consent_again.execute(None, context)
            chat_run.ask_consent = lambda prompt: asked.append(prompt) or True
            started = chat_run.start(context, "a lamp")
            check("consent: Ask before building again resets it and the next start opens the card",
                  result == {"FINISHED"} and prefs.chat_code_consent == "UNSET" and context.preferences.is_dirty
                  and started is False and asked == ["a lamp"] and not chat_run.STATE.running
                  and client.chat_llm.calls == 0, "%s %s %r" % (result, prefs.chat_code_consent, asked))

            from eachlabs.ui import tokens
            asked[:] = []
            compat.online_problem = lambda: tokens.ONLINE_OFF
            refused = chat_run.start(context, "a lamp")
            state = bar_state.from_chat(chat_run.STATE, overlay.FIELD, False, time.monotonic())
            compat.online_problem = real_online
            started = chat_run.start(context, "a lamp")
            check("online: access off offers Open preferences (System), and once on the next start asks for consent",
                  refused is False and state.mode == "error" and state.actions == ["network"]
                  and overlay._ACTION_ARGS["network"] == {"section": "SYSTEM"} and started is False
                  and asked == ["a lamp"] and not chat_run.STATE.running and client.chat_llm.calls == 0,
                  "%s %s %r" % (state.mode, state.actions, asked))

            overlay.FIELD.clear()
            chat_run.STATE.error, real_checked = "", overlay.UI["mcp_checked"]
            overlay.UI["mcp_checked"] = True
            sent = overlay.submit(context)
            overlay.UI["mcp_checked"] = real_checked
            state = bar_state.from_chat(chat_run.STATE, overlay.FIELD, True, time.monotonic())
            check("empty prompt: Enter with an empty field does nothing and leaves no error",
                  sent is False and chat_run.STATE.error == "" and not overlay.UI["consent"]
                  and state.mode == "typing" and not chat_run.STATE.running, "%s %r" % (state.mode, chat_run.STATE.error))

            prefs.chat_code_consent = "ALLOWED"
            count = thread_safety._chat_threads
            real_start = threading.Thread.start

            def no_chat_thread(thread):
                if thread.name == "eachlabs-chat":
                    raise RuntimeError("can't start new thread")
                return real_start(thread)

            threading.Thread.start = no_chat_thread
            try:
                started = chat_run.start(context, "a bench")
            finally:
                threading.Thread.start = real_start
            st = chat_run.STATE
            state = bar_state.from_chat(st, overlay.FIELD, False, time.monotonic(), has_scene=chat_run.has_scene())
            check("start failure: no thread resets the run and offers Retry",
                  started is False and not st.running and st.status == "idle" and st.error == tokens.START_FAILED
                  and chat_run._run is None and thread_safety._chat_threads == count and state.mode == "error"
                  and state.actions[:1] == ["retry"] and client.chat_llm.calls == 0,
                  "%s %s %r %s %d" % (started, st.status, st.error, state.actions, thread_safety._chat_threads))
            client.chat_llm = FakeLLM([text_reply("ok")] * 5)
            started = chat_run.EACHLABS_OT_chat_retry_stage.execute(op, context) == {"FINISHED"}
            check("start failure: Retry then starts the same prompt",
                  started and chat_run.STATE.running and chat_run.STATE.prompt == "a bench", chat_run.STATE.error)
            _chat_drive()
        finally:
            chat_run.ask_consent, compat.online_problem = real_ask, real_online
    chat_run.cancel(drop_build=True)
    chat_run.reset_view()
    for coll in [c for c in bpy.data.collections if c.get("eachlabs_run")]:
        bpy.data.collections.remove(coll)
    bpy.data.scenes.remove(scene)
