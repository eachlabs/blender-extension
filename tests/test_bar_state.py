import types
import unittest

from eachlabs.ui import bar, bar_state, tokens
from eachlabs.ui.text_field import TextField

STAGES = ("layout", "materials", "light", "camera", "check")


def chat(**kw):
    values = dict(prompt="", stages={}, status="idle", thinking_since=None, round=0, total=20, tools=[], reply="",
                  error="", cost=None, cost_text="", running=False, failed_stage=None, history=[], changed=[],
                  code_check_on=False, code_check_state="", code_check_reason="", attempt="", code_steps=[],
                  unchanged=False)
    values.update(kw)
    return types.SimpleNamespace(**values)


def state(c, focused=False, now=100.0, **kw):
    return bar_state.from_chat(c, TextField([], mac=False), focused, now, **kw)


class FromChatTest(unittest.TestCase):
    def test_idle_and_typing(self):
        self.assertEqual(state(chat()).mode, "idle")
        s = state(chat(), focused=True)
        self.assertEqual((s.mode, s.focused, s.actions, s.send_enabled), ("typing", True, [], True))

    def test_waiting_counts_seconds_from_thinking_since(self):
        s = state(chat(running=True, status="running", thinking_since=80.0, round=3,
                       stages={"layout": "active"}), now=97.5)
        self.assertEqual(s.mode, "waiting")
        self.assertAlmostEqual(s.thinking_seconds, 17.5)
        self.assertEqual((s.round, s.total), (4, 20))  # the round being waited for
        self.assertEqual(s.stages, {"layout": "active"})

    def test_building_shows_the_last_tool(self):
        tools = [{"id": "1", "name": "run_python", "summary": "Ground and two buildings", "state": "ok", "detail": ""},
                 {"id": "2", "name": "run_python", "summary": "Street lamps", "state": "running", "detail": ""}]
        s = state(chat(running=True, status="running", round=5, tools=tools))
        self.assertEqual((s.mode, s.round, s.status), ("building", 5, "Street lamps…"))
        s = state(chat(running=True, status="running", round=0, reply="Ground and one row."))
        self.assertEqual((s.round, s.status), (1, "Ground and one row."))

    def test_final_render_states_each_show_a_next_step(self):
        done = {s: "done" for s in STAGES}
        rendering = state(chat(status="done", stages=done, reply="Built it.", final_render="rendering"))
        self.assertNotIn("final", rendering.actions)  # one at a time; its own window has Esc
        self.assertEqual(rendering.reply, "Built it.\n" + tokens.FINAL_RENDERING)
        saved = state(chat(status="done", stages=done, reply="Built it.", final_render="saved",
                           final_path="/tmp/cabin-final.png", final_seconds=190.0))
        self.assertIn("final", saved.actions)
        self.assertIn("saved in 3 min 10 s: cabin-final.png", saved.reply)
        for name, text in (("cancelled", "stopped"), ("failed", "failed: no GPU")):
            s = state(chat(status="done", stages=done, reply="", final_render=name, final_error="no GPU"))
            self.assertIn("final", s.actions)
            self.assertIn(text, s.reply)
            self.assertFalse(s.reply.startswith("\n"))

    def test_final_render_settings(self):
        from eachlabs.chat import final_settings

        self.assertEqual(final_settings.fstop(0.6), 2.8)  # a dog: soft background
        self.assertEqual(final_settings.fstop(3.0), 6.0)
        self.assertEqual(final_settings.fstop(12.0), 11.0)  # a house stays sharp
        taken = {"/w/cabin-final.png", "/w/cabin-final-2.png"}
        self.assertEqual(final_settings.output_path("/w/cabin.blend", "/r", taken.__contains__), "/w/cabin-final-3.png")
        self.assertEqual(final_settings.output_path("", "/r", taken.__contains__), "/r/untitled-final.png")
        self.assertEqual(final_settings.seconds_text(42.4), "42 s")

    def test_done_offers_play_frame_and_undo(self):
        done = {s: "done" for s in STAGES}
        s = state(chat(status="done", stages=done, reply="Built it.", cost_text="7 ROUNDS · $0.004",
                       changed=["layout", "light", "camera"]))
        self.assertEqual((s.mode, s.reply, s.cost_text), ("done", "Built it.", "7 ROUNDS · $0.004"))
        self.assertEqual((s.actions, s.undo_stage), (["play", "frame", "final", "undo", "new"], "camera"))

    def test_done_hides_advanced_tools_unless_they_are_on(self):
        done = {s: "done" for s in STAGES}
        c = chat(status="done", stages=done, changed=["layout", "light", "camera"], code_steps=[{"code": "x"}])
        self.assertEqual(state(c, advanced=False).actions, ["play", "frame", "undo"])
        self.assertEqual(state(c, advanced=True).actions, ["play", "frame", "final", "undo", "code", "new"])

    def test_done_with_missing_things_offers_to_build_them(self):
        done = {s: "done" for s in STAGES}
        s = state(chat(status="done", stages=done, changed=["layout"], missing=["church", "bandit camp"]))
        self.assertEqual(s.actions, ["play", "frame", "final", "missing", "undo", "new"])
        self.assertEqual(bar.action_label("missing", s.stages), "Build the missing things")
        self.assertEqual(s.missing_label, "Build the missing things (about 8 rounds)")

    def test_an_edit_kept_from_other_objects_offers_to_let_it(self):
        done = {"edit": "done"}
        s = state(chat(status="done", stages=done, changed=[], blocked=["Boundary masonry north", "House 2"]))
        self.assertIn("widen", s.actions)
        self.assertEqual(bar.action_label("widen", s.stages, widen=s.widen_label),
                         "Also let it change Boundary masonry north and 1 more")

    def test_a_plan_over_the_round_limit_offers_three_choices(self):
        plan = types.SimpleNamespace(items=[], looks="", looks_only=False, rounds_needed=46, rounds_limit=36,
                                     note="This request needs about 46 rounds (about $1.61). Your limit is 36, so "
                                          "some things may not be built.",
                                     summary_3d=lambda: "", summary_code=lambda: "Built in code: 20 things")
        s = state(chat(running=True, status="running", plan=plan, plan_waiting=True))
        self.assertEqual(s.mode, "plan")
        self.assertEqual(s.actions, ["plan_limit", "plan_raise", "plan_cancel"])
        self.assertEqual(bar.action_label("plan_limit", {}), "Build within my limit")
        self.assertEqual(bar.action_label("plan_raise", {}, raise_label=s.raise_label), "Use 46 for this run")
        self.assertIn("Your limit is 36", s.plan_note)

    def test_a_plan_within_the_limit_keeps_build_and_cancel(self):
        plan = types.SimpleNamespace(items=[], looks="Looks: up to 1 texture", looks_only=True, rounds_needed=0,
                                     note="")
        s = state(chat(running=True, status="running", plan=plan, plan_waiting=True))
        self.assertEqual(s.actions, ["plan_build", "plan_cancel"])

    def test_the_missing_button_says_about_how_many_rounds(self):
        s = state(chat(status="done", stages={"layout": "done"}, missing=["church", "bandit camp"]))
        self.assertEqual(bar.action_label("missing", s.stages, missing_label=s.missing_label),
                         "Build the missing things (about 8 rounds)")

    def test_a_removal_offers_to_remove_what_still_matches(self):
        s = state(chat(status="done", stages={"edit": "done"}, changed=[], blocked=["Perimeter wall"], removal=True))
        self.assertEqual(bar.action_label("widen", s.stages, widen=s.widen_label), "Also remove Perimeter wall")

    def test_the_sent_prompt_is_shown_and_the_field_stays_empty(self):
        running = state(chat(running=True, status="running", round=3, attempt="a village by a lake"))
        self.assertEqual((running.asked, running.field.text), ("a village by a lake", ""))
        done = state(chat(status="done", stages={"layout": "done"}, attempt="a village by a lake"), asked_open=True)
        self.assertEqual((done.asked, done.asked_open), ("a village by a lake", True))
        self.assertEqual(state(chat(status="idle", attempt="a village by a lake")).asked, "")

    def test_undo_names_the_last_stage_that_changed_the_scene(self):
        done = {s: "done" for s in STAGES}
        s = state(chat(status="done", stages=done, changed=["layout", "camera"]))
        self.assertEqual(s.undo_stage, "camera")  # check changed nothing
        undone = dict(done, camera="todo")
        s = state(chat(status="done", stages=undone, changed=["layout", "camera"]))
        self.assertEqual((s.actions, s.undo_stage), (["play", "frame", "final", "undo", "new"], "layout"))

    def test_has_scene_is_passed_through(self):
        self.assertFalse(state(chat()).has_scene)
        self.assertTrue(state(chat(status="done"), has_scene=True).has_scene)
        self.assertTrue(state(chat(), has_scene=True).has_scene)

    def test_undoable_given_overrides_changed(self):
        done = {s: "done" for s in STAGES}
        s = state(chat(status="done", stages=done, changed=["layout", "camera"]), undoable=[])
        self.assertEqual((s.actions, s.undo_stage), (["play", "frame", "final", "new"], ""))
        s = state(chat(status="done", stages=done, changed=["layout", "camera"]), undoable=["layout"])
        self.assertEqual(s.undo_stage, "layout")

    def test_no_undo_when_no_stage_changed_anything(self):
        s = state(chat(status="done", stages={k: "done" for k in STAGES}, changed=[]))
        self.assertEqual((s.actions, s.undo_stage), (["play", "frame", "final", "new"], ""))

    def test_stopped_stage_offers_retry_and_new_scene(self):
        stages = {"layout": "done", "materials": "done", "light": "done", "camera": "failed", "check": "todo"}
        s = state(chat(status="stopped", stages=stages, error="Camera stage stopped.", failed_stage="camera"))
        self.assertEqual((s.mode, s.error, s.actions), ("stopped", "Camera stage stopped.", ["retry", "new"]))

    def test_cancelled_reads_as_stopped(self):
        s = state(chat(status="cancelled", stages={"layout": "cancelled"}))
        self.assertEqual((s.mode, s.error, s.actions), ("stopped", "Stopped. What was built is kept.",
                                                        ["new", "keep"]))

    def test_a_stop_while_a_3d_run_goes_says_it_may_still_be_billed(self):
        s = state(chat(status="cancelled", stages={"layout": "cancelled"}, billed=True))
        self.assertEqual((s.mode, s.error), ("stopped", "Stopped — a 3D run already started may still be billed."))
        self.assertEqual(s.note, "")  # said once
        rows = [{"kind": "object", "name": "car", "state": "failed", "cost": None}]
        done = state(chat(status="done", stages=PARTLY, reply="A street.", billed=True, objects=rows))
        self.assertEqual(done.note, "Stopped — a 3D run already started may still be billed. · 3D: car built in code")
        self.assertEqual(state(chat(status="done", stages=PARTLY, reply="A street.", objects=rows)).note,
                         "3D: car built in code")

    def test_key_messages_open_preferences_and_disable_send(self):
        for c in (chat(error="Add your Eachlabs API key to start."),
                  chat(status="stopped", failed_stage="layout", stages={"layout": "failed"},
                       error="Invalid or missing API key (HTTP 401)")):
            s = state(c)
            self.assertEqual((s.mode, s.error, s.actions, s.send_enabled, s.stages),
                             ("error", c.error if "Add" in c.error else "API key was rejected (HTTP 401).",
                              ["prefs"], False, {}))

    def test_key_message_clears_once_the_key_changed(self):
        s = state(chat(error="API key was rejected (HTTP 401)."), key_changed=True)
        self.assertEqual((s.mode, s.error, s.send_enabled), ("idle", "", True))

    def test_other_refusal_keeps_send(self):
        s = state(chat(status="idle", error="The model call failed: timed out", attempt="a street"))
        self.assertEqual((s.mode, s.send_enabled, s.actions, s.stages), ("error", True, ["retry"], {}))

    def test_network_reads_open_preferences(self):
        self.assertEqual(bar.action_label("network", {}, ""), "Open preferences")

    def test_caret_and_spinner_pass_through(self):
        s = state(chat(), focused=True, caret_on=False, spinner_phase=0.25)
        self.assertEqual((s.caret_on, s.spinner_phase), (False, 0.25))


STEP = {"id": "c1", "stage": "layout", "code": "# ground", "state": "ok", "detail": ""}
PARTLY = {"layout": "done", "materials": "done", "light": "active", "camera": "todo", "check": "todo"}


class NextStepTest(unittest.TestCase):
    """Every state that is not running offers a next step; one test per row of the table."""

    def test_done(self):
        done = {k: "done" for k in STAGES}
        s = state(chat(status="done", stages=done, changed=["layout", "camera"], code_steps=[STEP]))
        self.assertEqual(s.actions, ["play", "frame", "final", "undo", "code", "new"])
        s = state(chat(status="done", stages=done, changed=[], code_steps=[]))
        self.assertEqual(s.actions, ["play", "frame", "final", "new"])

    def test_done_with_nothing_changed_says_so_and_offers_retry(self):
        done = {k: "done" for k in STAGES}
        reply = "The scene still shows only the car."
        s = state(chat(status="done", stages=done, unchanged=True, reply=reply, cost_text="15 ROUNDS"))
        self.assertEqual((s.mode, s.error, s.reply, s.cost_text), ("done", bar_state.T.NOTHING_CHANGED, reply,
                                                                   "15 ROUNDS"))
        self.assertEqual(s.error, "Nothing in the scene changed. Try again or reword the request.")
        self.assertEqual(s.actions, ["retry", "new"])
        # Steps that ran and changed nothing (only printed) keep Show code.
        s = state(chat(status="done", stages=done, unchanged=True, code_steps=[STEP], changed=["layout"]))
        self.assertEqual(s.actions, ["retry", "undo", "code", "new"])
        s = state(chat(status="done", stages=done, unchanged=True))
        self.assertEqual((s.error, s.actions), (bar_state.T.NOTHING_CHANGED, ["retry", "new"]))
        s = state(chat(status="done", stages=done, code_steps=[STEP], changed=["layout"]))
        self.assertEqual((s.error, s.actions[0]), ("", "play"))  # a run that changed the scene

    def test_round_limit_reads_as_done(self):
        s = state(chat(status="done", stages=PARTLY, changed=["layout"], code_steps=[STEP],
                       reply="Stopped after 20 rounds. What was built is kept."))
        self.assertEqual((s.mode, s.actions), ("done", ["play", "frame", "final", "undo", "code", "new"]))

    def test_stopped_by_you(self):
        stages = dict(PARTLY, light="cancelled")
        s = state(chat(status="cancelled", stages=stages, changed=["layout", "materials"], code_steps=[STEP]))
        self.assertEqual((s.mode, s.actions, s.undo_stage), ("stopped", ["undo", "code", "new", "keep"], "materials"))
        s = state(chat(status="cancelled", stages={"layout": "cancelled"}))
        self.assertEqual(s.actions, ["new", "keep"])

    def test_stopped_after_a_failed_stage(self):
        stages = dict(PARTLY, light="failed")
        s = state(chat(status="stopped", stages=stages, failed_stage="light", changed=["layout", "materials"],
                       code_steps=[STEP], error="Stopped: run_python kept failing: boom"))
        self.assertEqual((s.mode, s.actions), ("stopped", ["retry", "undo", "code", "new"]))
        s = state(chat(status="stopped", stages={"layout": "failed"}, failed_stage="layout",
                       error="The model is busy, try again in a moment."))
        self.assertEqual(s.actions, ["retry", "new"])

    def test_stopped_by_code_check(self):
        stages = dict(PARTLY, light="failed")
        s = state(chat(status="stopped", stages=stages, failed_stage="light", changed=["layout"], code_steps=[STEP],
                       error="Code check stopped the run: it reads a file"))
        self.assertEqual((s.mode, s.actions), ("stopped", ["retry", "code", "new"]))
        self.assertEqual(s.error, "Code check stopped the run: it reads a file. "
                                  "You can turn Code check off in the Eachlabs tab.")

    def test_stopped_because_a_step_changed_the_settings(self):
        stages = dict(PARTLY, light="failed")
        s = state(chat(status="stopped", stages=stages, failed_stage="light", changed=["layout"], code_steps=[STEP],
                       error=bar_state.T.SETTINGS_CHANGED))
        self.assertEqual((s.mode, s.error, s.actions), ("stopped", bar_state.T.SETTINGS_CHANGED, ["code", "new"]))

    def test_hidden_tools_keep_new_scene_when_it_is_the_only_way_on(self):
        stages = dict(PARTLY, light="failed")
        s = state(chat(status="stopped", stages=stages, failed_stage="light", changed=["layout"], code_steps=[STEP],
                       error=bar_state.T.SETTINGS_CHANGED), advanced=False)
        self.assertEqual(s.actions, ["new"])
        found = state(chat(status="found", reply="The well is selected."), advanced=False)
        self.assertEqual(found.actions, ["frame"])

    def test_other_error(self):
        s = state(chat(status="idle", error="The model call failed: timed out", attempt="a street",
                       code_steps=[STEP]), has_scene=True)
        self.assertEqual((s.mode, s.actions, s.send_enabled), ("error", ["retry", "code", "new"], True))
        s = state(chat(status="stopped", error="worker broke", attempt="a street"))
        self.assertEqual((s.mode, s.actions), ("error", ["retry"]))

    def test_empty_prompt_is_not_an_error_state(self):
        empty = "Describe the scene you imagine first."
        s = state(chat(status="idle", error=empty), focused=True)
        self.assertEqual((s.mode, s.error, s.actions, s.send_enabled), ("typing", "", [], True))
        done = {k: "done" for k in STAGES}
        s = state(chat(status="done", stages=done, changed=["layout"], code_steps=[STEP], error=empty))
        self.assertEqual((s.mode, s.error, s.actions), ("done", "", ["play", "frame", "final", "undo", "code", "new"]))

    def test_online_access_off_offers_preferences_not_retry(self):
        off = "Online access is off. Enable it in Preferences > System > Network > Allow Online Access."
        s = state(chat(status="idle", error=off, attempt="a street"))
        self.assertEqual((s.mode, s.error, s.actions, s.send_enabled), ("error", off, ["network"], True))
        s = state(chat(status="idle", error=off, attempt="a street", code_steps=[STEP]), has_scene=True)
        self.assertEqual(s.actions, ["network", "code", "new"])
        s = state(chat(status="idle", error="", attempt="a street"))  # online access on again: Enter works
        self.assertEqual((s.mode, s.send_enabled), ("idle", True))
        offline = "Blender was started with --offline-mode. Restart without it to use Eachlabs."
        s = state(chat(status="idle", error=offline, attempt="a street"))
        self.assertEqual((s.mode, s.actions), ("error", []))  # only a restart helps

    def test_chat_that_could_not_start_offers_retry_and_new_scene(self):
        failed = "The chat could not start. Try again."
        s = state(chat(status="idle", error=failed, attempt="a street"))
        self.assertEqual((s.mode, s.error, s.actions), ("error", failed, ["retry"]))
        s = state(chat(status="idle", error=failed, attempt="a street"), has_scene=True)
        self.assertEqual(s.actions, ["retry", "new"])

    def test_key_error(self):
        s = state(chat(error="Add your Eachlabs API key to start.", attempt="a street", code_steps=[STEP]),
                  has_scene=True)
        self.assertEqual((s.mode, s.actions), ("error", ["prefs"]))
        s = state(chat(error="Add your Eachlabs API key to start."), key_changed=True)
        self.assertEqual((s.mode, s.actions), ("idle", []))

    def test_consent_gate(self):
        self.assertTrue(bar_state.consent_shown(True, allowed=False))
        self.assertFalse(bar_state.consent_shown(True, allowed=True))  # agreed: the card never shows
        self.assertFalse(bar_state.consent_shown(False, allowed=False))  # nothing asked yet
        self.assertFalse(bar_state.consent_after_send(True, started=True))  # a started run closes it
        self.assertTrue(bar_state.consent_after_send(True, started=False))  # a refused start that asked keeps it
        self.assertFalse(bar_state.consent_after_send(False, started=False))

    def test_consent_card(self):
        s = state(chat(status="done", stages={"layout": "done"}, reply="x"), focused=True, consent=True)
        self.assertEqual((s.mode, s.actions, s.stages), ("consent", ["consent_plain", "consent_cancel"], {}))
        self.assertEqual(bar.action_label("consent_plain", {}), "Build")
        s = state(chat(running=True, status="running"), consent=True)
        self.assertEqual(s.mode, "building")

    def test_building_and_waiting(self):
        s = state(chat(running=True, status="running", round=3, code_check_on=True))
        self.assertEqual((s.mode, s.actions, s.code_check), ("building", [], True))
        s = state(chat(running=True, status="running", round=3, thinking_since=99.0))
        self.assertEqual((s.mode, s.actions, s.code_check), ("waiting", [], False))

    def test_code_check_checking_line(self):
        s = state(chat(running=True, status="running", round=4, code_check_on=True, code_check_state="checking"))
        self.assertEqual((s.mode, s.status, s.error), ("building", "Code check: reading the step before it runs…", ""))

    def test_code_check_refused_line_with_show_code_and_stop(self):
        c = chat(running=True, status="running", round=4, stages=PARTLY, code_check_on=True,
                 code_check_state="refused", code_check_reason="it tried to read a file outside Blender.",
                 thinking_since=99.0)  # the line stays while the model rewrites the step
        s = state(c)
        self.assertEqual((s.mode, s.round, s.actions, s.code_check), ("building", 4, ["code", "halt"], True))
        self.assertEqual(s.error, "Code check stopped a step: it tried to read a file outside Blender. "
                                  "The chat is rewriting it without that.")

    def test_there_is_no_show_cube_action(self):
        self.assertNotIn("cube", bar_state._HIT_ORDER)
        self.assertNotIn("cube", bar._ACTION_LABELS)

    def test_every_action_has_a_hit_order(self):
        for name in ("play", "frame", "undo", "code", "new", "retry", "keep", "prefs", "network", "halt", "consent_check",
                     "consent_plain", "consent_cancel"):
            self.assertIn(name, bar_state._HIT_ORDER)


class PlacementTest(unittest.TestCase):
    def test_width_is_640_or_region_minus_32(self):
        self.assertEqual(bar_state.bar_width(1280), 640)
        self.assertEqual(bar_state.bar_width(600), 568)
        self.assertEqual(bar_state.bar_width(100), bar_state.MIN_WIDTH)

    def test_bar_is_centred_and_36_px_above_the_bottom(self):
        # Image 1424 x 248 at scale 2, bar at (72, 56) size 1280 x 104 (top-down image px).
        x, y = bar_state.image_origin((1424, 248), (72, 56, 1280, 104), 2000, 2)
        self.assertEqual(x + 72, (2000 - 1280) // 2)
        bar_bottom_from_image_bottom = 248 - (56 + 104)
        self.assertEqual(y + bar_bottom_from_image_bottom, 72)

    def test_centred_in_the_width_the_sidebar_and_toolbar_leave(self):
        _, y0 = bar_state.image_origin((1424, 248), (72, 56, 1280, 104), 2000, 2)
        _, y1 = bar_state.image_origin((1424, 248), (72, 56, 1280, 104), 2000, 2, bottom=167)
        self.assertEqual(y1 - y0, 167)  # above an asset shelf
        x, _ = bar_state.image_origin((1424, 248), (72, 56, 1280, 104), 2000, 2, left=100, right=500)
        self.assertEqual(x + 72, 100 + (2000 - 600 - 1280) // 2)

    def test_region_point_to_image_point_flips_y(self):
        origin = (100, -20)
        self.assertEqual(bar_state.to_image(100, -20 + 248, origin, 248), (0, 0))
        self.assertEqual(bar_state.to_image(110, -20, origin, 248), (10, 248))

    def test_round_trip_hits_the_drawn_rect(self):
        frame_size, rect = (1424, 248), (72, 56, 1280, 104)
        origin = bar_state.image_origin(frame_size, rect, 2000, 2)
        hits = {"bar": rect, "send": (1280, 90, 72, 72), "field": (140, 90, 900, 72)}
        # The send button's centre, in region pixels with y up.
        mx = origin[0] + 1280 + 36
        my = origin[1] + 248 - (90 + 36)
        self.assertEqual(bar_state.hit(hits, *bar_state.to_image(mx, my, origin, 248)), "send")
        self.assertEqual(bar_state.hit(hits, *bar_state.to_image(origin[0] + 100, my, origin, 248)), "bar")
        self.assertIsNone(bar_state.hit(hits, *bar_state.to_image(origin[0] + 10, my, origin, 248)))



class QualityPickerTest(unittest.TestCase):
    def test_the_pill_names_the_mode_and_an_unknown_one_reads_as_prototype(self):
        names = {"PROTOTYPE": "Prototype", "ADVANCED": "Final (experimental)", "FAST": "Prototype"}
        for mode, name in names.items():
            with self.subTest(mode):
                self.assertEqual(bar_state.quality_name(mode), name)
                self.assertEqual(state(chat(), quality=mode).quality_label, name)
        self.assertEqual(state(chat()).quality_label, "")  # no mode given: no pill

    def test_menu_lists_both_modes_with_hints_and_marks_the_current_one(self):
        items = bar_state.quality_menu("ADVANCED")
        self.assertEqual([(n, c) for n, _h, c in items], [("Prototype", False), ("Final (experimental)", True)])
        self.assertEqual([h for _n, h, _c in items], [
            "Quick drafts · fewer rounds, GPT-6.1 Terra · about $1 a room", "Full detail · more rounds, detail and reference pictures"])
        self.assertEqual([c for _n, _h, c in bar_state.quality_menu("FAST")], [True, False])

    def test_a_menu_item_chooses_its_mode(self):
        self.assertEqual([bar_state.picked("quality_%d" % i) for i in range(2)], ["PROTOTYPE", "ADVANCED"])
        self.assertIsNone(bar_state.picked("quality_2"))
        for other in ("quality", "send", "bar", None):
            self.assertIsNone(bar_state.picked(other))

    def test_the_menu_opens_in_every_state_but_a_run_and_the_consent_card(self):
        done = {s: "done" for s in STAGES}
        for c in (chat(), chat(status="done", stages=done, reply="Built it."),
                  chat(error="API key was rejected (HTTP 401).")):
            s = state(c, quality="PROTOTYPE", menu=True)
            self.assertEqual((len(s.quality_menu), s.quality_enabled), (len(tokens.QUALITIES), True))
        running = state(chat(running=True, status="running", round=2), quality="PROTOTYPE", menu=True)
        self.assertEqual((running.quality_menu, running.quality_enabled, running.quality_label), ([], False, "Prototype"))
        consent = state(chat(), quality="PROTOTYPE", menu=True, consent=True)
        self.assertEqual((consent.mode, consent.quality_menu), ("consent", []))
        self.assertEqual(state(chat(), quality="PROTOTYPE").quality_menu, [])

    def test_the_selected_thing_shows_on_assets_and_characters_only(self):
        from eachlabs.ui import bar_state

        self.assertEqual(state(chat(), tab="asset", thing="Barrel").thing, "Barrel")
        self.assertEqual(state(chat(), tab="character", thing="Cat").thing, "Cat")
        self.assertEqual(state(chat(), tab="scene", thing="Barrel").thing, "")
        self.assertEqual(bar_state.thing_label(["Barrel"]), "Barrel")
        self.assertEqual(bar_state.thing_label(["Barrel", "Crate", "Lamp"]), "Barrel and 2 more")
        self.assertEqual(bar_state.thing_label([]), "")

    def test_the_tab_shows_and_is_off_while_a_run_goes(self):
        idle = state(chat(), tab="asset")
        self.assertEqual((idle.tab, idle.tabs_enabled), ("asset", True))
        running = state(chat(running=True, status="running", round=2), tab="character")
        self.assertEqual((running.tab, running.tabs_enabled), ("character", False))
        self.assertEqual(state(chat()).tab, "")

    def test_the_plan_waits_with_build_and_cancel(self):
        from eachlabs import plan3d

        plan = plan3d.parse('{"objects_3d": [{"name": "car", "description": "red car"}], "code": ["road"]}', 4)
        s = state(chat(running=True, status="running", plan=plan, plan_waiting=True,
                       stages={st: "todo" for st in STAGES}), quality="PROTOTYPE", menu=True)
        self.assertEqual((s.mode, s.actions, s.stages, s.send_enabled), ("plan", ["plan_build", "plan_cancel"], {},
                                                                          False))
        self.assertEqual(s.plan_chips, [(0, "Car", "3d", False)])  # the road has parts: no chip, always code
        self.assertEqual(s.plan_3d, "3D: car · 1 × $0.45 = $0.45 · about 3 min one by one")
        self.assertEqual(s.quality_menu, [])  # no model menu over the plan
        self.assertFalse(s.quality_enabled)

    def test_a_looks_only_plan_shows_only_its_looks_line_with_build_and_cancel(self):
        from eachlabs import plan3d

        plan = plan3d.looks_plan(True, 0, 0.15)
        s = state(chat(running=True, status="running", plan=plan, plan_waiting=True,
                       stages={st: "todo" for st in STAGES}))
        self.assertEqual((s.mode, s.actions, s.send_enabled), ("plan", ["plan_build", "plan_cancel"], False))
        self.assertEqual((s.plan_3d, s.plan_code, s.plan_chips), ("", "", []))
        self.assertEqual((s.plan_looks, s.plan_note), ("Looks: a concept picture · $0.15", bar_state.T.LOOKS_HINT))

    def test_only_solid_pieces_get_a_chip(self):
        from eachlabs import plan3d

        plan = plan3d.parse('{"objects_3d": [{"name": "statue", "description": "bronze statue"}], '
                            '"code": ["road", {"name": "rock", "solid": true}]}', 2)
        self.assertTrue(plan.toggle(2))
        self.assertEqual(bar_state.plan_fields(plan)[2], [(0, "Statue", "3d", False), (2, "Rock", "3d", False)])
        self.assertFalse(plan.toggle(1))

    def test_a_partly_done_stage_offers_retry_on_the_done_bar(self):
        stages = {"layout": "done", "materials": "done", "light": "partial", "camera": "done", "check": "done"}
        s = state(chat(status="done", reply="A town.", stages=stages, failed_stage="light", code_steps=[{}]))
        self.assertEqual(s.mode, "done")
        self.assertEqual(s.actions[:4], ["play", "frame", "final", "retry"])
        self.assertEqual(bar.action_label("retry", s.stages), "Retry light stage")
        whole = state(chat(status="done", reply="A town.", stages={st: "done" for st in STAGES}))
        self.assertNotIn("retry", whole.actions)
        frame_partial = bar.render(s, 640, 1)
        frame_done = bar.render(bar.BarState(**{**vars(s), "stages": {**stages, "light": "done"}}), 640, 1)
        self.assertNotEqual(frame_partial.rgba, frame_done.rgba)  # the half dot is drawn

    def test_planning_shows_a_status_line(self):
        s = state(chat(running=True, status="running", planning=True, stages={st: "todo" for st in STAGES}))
        self.assertEqual((s.mode, s.status), ("building", "Planning the scene…"))

    ROWS = [{"name": "car", "state": "running", "seconds": 130.4, "cached": False, "cost": None},
            {"name": "tree", "state": "ready", "seconds": 1, "cached": True, "cost": 0.0},
            {"name": "lamp", "state": "failed", "seconds": 360, "cached": False, "cost": None, "error": "timeout"}]

    def test_a_line_per_3d_job_while_the_run_goes(self):
        s = state(chat(running=True, status="running", round=3, objects=self.ROWS,
                       tools=[{"id": "1", "name": "run_python", "summary": "Road", "state": "ok", "detail": ""}]))
        self.assertEqual(s.objects, ["Generating the car… 2:10", "Bringing in the tree from the cache…",
                                     "The lamp stays built in code: its 3D model was not made."])
        waiting = state(chat(running=True, status="running", round=3, objects=self.ROWS, objects_wait=True,
                             tools=[{"id": "1", "name": "run_python", "summary": "Road", "state": "ok",
                                     "detail": ""}]))
        self.assertEqual(waiting.status, "Waiting for the 3D models to replace their code versions…")
        many = [dict(self.ROWS[0], name="thing %d" % i) for i in range(5)]
        self.assertEqual(bar_state.object_lines(many)[-1], "+3 more 3D objects")

    def test_the_bar_says_when_the_chat_looks_at_the_frame(self):
        tools = [{"id": "1", "name": "run_python", "summary": "Road", "state": "ok", "detail": ""}]
        s = state(chat(running=True, status="running", round=3, looking=True, tools=tools))
        self.assertEqual(s.objects, ["Looking at the frame…"])
        s = state(chat(running=True, status="running", round=3, looking=False, tools=tools))
        self.assertEqual(s.objects, [])

    def test_the_queue_is_named_after_the_running_job(self):
        rows = [{"name": "house", "state": "queued", "priority": (1, 1)},
                {"name": "car", "state": "running", "seconds": 80, "priority": (0, 0)},
                {"name": "garage", "state": "queued", "priority": (1, 2)}]
        self.assertEqual(bar_state.object_lines(rows), ["Generating the car… 1:20 · then: house, garage"])
        waiting = [dict(r, state="queued") for r in rows]
        self.assertEqual(bar_state.object_lines(waiting), ["Waiting to generate: car, house, garage"])

    def test_textures_have_their_own_lines(self):
        rows = [{"name": "car", "state": "running", "seconds": 80},
                {"kind": "texture", "name": "Brick paint", "state": "running", "seconds": 12},
                {"kind": "texture", "name": "Floor", "state": "queued"},
                {"kind": "texture", "name": "Roof", "state": "failed"}]
        self.assertEqual(bar_state.object_lines(rows), [
            "Generating the car… 1:20", "Drawing the Brick paint texture… 0:12",
            "The Roof texture was not made; it keeps its own colour."])
        done = [{"kind": "texture", "name": "Brick paint", "state": "done", "cost": 0.15},
                {"kind": "texture", "name": "Roof", "state": "failed"}]
        self.assertEqual(bar_state.objects_note(done), "Textures: Brick paint $0.15 · Roof not made")

    def test_after_the_run_the_note_has_the_real_figures(self):
        rows = [dict(self.ROWS[0], state="done", cost=0.45), dict(self.ROWS[1], state="done"), self.ROWS[2]]
        s = state(chat(status="done", reply="A street.", objects=rows, stages={st: "done" for st in STAGES}))
        self.assertEqual(s.note, "3D: car $0.45 · tree cached, free · lamp built in code")

    def test_plan_hits_win_over_the_bar(self):
        hits = {"bar": (0, 0, 100, 100), "plan_item_2": (0, 0, 40, 20), "plan_build": (0, 60, 40, 20)}
        self.assertEqual(bar_state.hit(hits, 5, 5), "plan_item_2")
        self.assertEqual(bar_state.hit(hits, 5, 65), "plan_build")

    def test_menu_items_and_the_pill_win_over_the_bar(self):
        hits = {"bar": (0, 0, 100, 100), "quality_1": (0, 0, 100, 20), "quality": (60, 80, 20, 20),
                "field": (0, 80, 60, 20)}
        self.assertEqual(bar_state.hit(hits, 5, 5), "quality_1")
        self.assertEqual(bar_state.hit(hits, 65, 85), "quality")
        self.assertEqual(bar_state.hit(hits, 5, 50), "bar")


if __name__ == "__main__":
    unittest.main()


class FreeAssetsNote(unittest.TestCase):
    def test_names_and_credit(self):
        from eachlabs.ui import bar_state
        self.assertEqual(bar_state.free_note(["Rogland Clear Night", "Oak Wood Planks"]),
                         "Free: Rogland Clear Night, Oak Wood Planks (Poly Haven, CC0)")
        self.assertIn("+2 more", bar_state.free_note(list("abcdef")))


def done_state(**kw):
    return state(chat(status="done", reply="A room.", cost_text="34 ROUNDS · $0.38", **kw))


def state_with_video(video, progress=0, **kw):
    values = dict(video=video, video_job="job1", video_message="", video_seconds=0, video_progress=progress)
    values.update(kw)
    return done_state(**values)


class VideoTest(unittest.TestCase):
    def test_the_done_card_has_no_make_video_pill(self):  # the Video tab makes videos
        self.assertFalse([a for a in done_state().actions if a.startswith("video")])

    def test_video_lines(self):
        lines = {
            "rendering": (dict(progress=40), "Video: recording the camera move… 40%"),
            "photos": (dict(video_message="2 of 3"), "Video: making the look (2 of 3)…"),
            "generating": (dict(video_seconds=80), "Video: Seedance 2.5 is making it… 1:20"),
            "done": ({}, "Video: in the Video Sequencer"),
            "stopped": ({}, "Video stopped; it may still be billed"),
            "failed": (dict(video_message="the provider said no"), "Video failed: the provider said no"),
        }
        for video, (kw, line) in lines.items():
            with self.subTest(video):
                s = state_with_video(video, **kw)
                self.assertEqual(bar_state.video_line(types.SimpleNamespace(**dict(
                    dict(video=video, video_job="job1", video_message="", video_seconds=0, video_progress=0),
                    **{("video_progress" if k == "progress" else k): v for k, v in kw.items()}))), line)
                self.assertTrue(s.reply.endswith(line), s.reply)
        self.assertEqual(bar_state.video_line(types.SimpleNamespace(video="photos", video_message="")),
                         "Video: making the look…")  # uploading, before the photos are counted
        self.assertEqual(bar_state.video_line(chat()), "")

    def test_actions_per_state(self):
        for video in ("rendering", "photos", "generating"):
            with self.subTest(video):
                s = state_with_video(video)
                self.assertIn("video_stop", s.actions)
        for video in ("failed", "stopped"):
            with self.subTest(video):
                s = state_with_video(video)
                self.assertEqual([a for a in s.actions if a.startswith("video")], ["video_retry"])
        s = state_with_video("done")
        self.assertEqual([a for a in s.actions if a.startswith("video")], ["video_open", "video_file"])
        self.assertEqual([bar.action_label(a, s.stages) for a in ("video_open", "video_file")],
                         ["Open Sequencer", "Show file"])
        self.assertNotIn("video_retry", state_with_video("failed", video_job="").actions)  # nothing to retry

    def test_folded_line_shows_video(self):
        from eachlabs.ui import status_rows

        self.assertIn("VIDEO 40%", status_rows._folded_line(state_with_video("rendering", 40)))
        self.assertIn("VIDEO 1:20", status_rows._folded_line(state_with_video("generating", video_seconds=80)))
        self.assertIn("VIDEO READY", status_rows._folded_line(state_with_video("done")))
        self.assertNotIn("VIDEO", status_rows._folded_line(done_state()))

    def test_failed_video_keeps_card_open(self):
        self.assertFalse(bar_state.foldable(state_with_video("failed")))
        self.assertTrue(bar_state.foldable(state_with_video("generating")))

    def test_new_run_moves_video_to_status_line(self):
        def running(**kw):
            values = dict(running=True, status="running", stages={"layout": "active"}, round=1,
                          tools=[{"name": "run_python", "summary": "building", "state": "running"}],
                          video_job="job1", video_message="", video_seconds=0, video_progress=0)
            values.update(kw)
            return state(chat(**values))

        s = running(video="generating", video_seconds=80)
        self.assertEqual(s.mode, "building")
        self.assertEqual(s.objects[-1], "Video: Seedance 2.5 is making it… 1:20")
        self.assertEqual(running(video="done", thinking_since=90.0).objects, ["Video: in the Video Sequencer"])
        self.assertEqual(running(video="rendering", video_progress=40).objects,
                         ["Video: recording the camera move… 40%"])
        self.assertEqual(running(video="").objects, [])
        rows = [dict(name="car %d" % i, state="failed") for i in range(5)]
        s = running(video="generating", objects=rows)  # the 3D jobs' lines are capped; the video's line stays
        self.assertEqual(len(s.objects), bar_state.OBJECT_LINES + 1)
        self.assertTrue(s.objects[-1].startswith("Video: "), s.objects)
        self.assertEqual(running(video="generating").actions[:1], ["video_stop"])
        self.assertEqual(running(video="done", thinking_since=90.0).actions, ["video_open", "video_file"])
        failed = running(video="failed", video_message="no")
        self.assertEqual(failed.actions, [])  # Retry renders: it comes back after the run
        self.assertEqual(failed.objects, ["Video failed: no · Retry when the chat finishes."])
        self.assertEqual(running(video="stopped").objects,
                         ["Video stopped; it may still be billed · Retry when the chat finishes."])
        self.assertNotIn("Retry when", state_with_video("failed").reply)  # the done card offers Retry itself
        refused = running(video="generating", code_check_state="refused")
        self.assertEqual(refused.actions, ["video_stop", "code", "halt"])

    def test_every_state_keeps_the_video_and_its_stop(self):
        from eachlabs import plan3d

        line = "Video: Seedance 2.5 is making it… 1:20"
        video = dict(video="generating", video_job="job1", video_message="", video_seconds=80, video_progress=0)
        plan = plan3d.parse('{"objects_3d": [{"name": "car", "description": "red car"}], "code": ["road"]}', 4)
        cases = {
            "unchanged": (chat(status="done", reply="Nothing.", unchanged=True, **video), {}),
            "found": (chat(status="found", reply="Found: Kiosk", **video), {}),
            "stopped": (chat(status="stopped", failed_stage="light", error="It broke.", stages={"light": "failed"},
                             **video), {}),
            "error": (chat(error="The server answered HTTP 502.", attempt="a street", **video), {}),
            "cancelled": (chat(status="cancelled", **video), {}),
            "key error": (chat(error=bar_state.KEY_ERRORS[0], **video), {}),
            "consent": (chat(**video), dict(consent=True)),
            "idle": (chat(**video), {}),
        }
        for name, (c, kw) in cases.items():
            with self.subTest(name):
                s = state(c, **kw)
                self.assertIn(line, s.note.split("\n"), s.note)
                self.assertIn("video_stop", s.actions)
                self.assertEqual(s.video, "generating")
        s = state(chat(running=True, status="running", plan=plan, plan_waiting=True, **video))
        self.assertEqual(s.mode, "plan")
        self.assertTrue(s.plan_note.endswith("\n" + line), s.plan_note)
        self.assertEqual(s.actions, ["video_stop", "plan_build", "plan_cancel"])
        failed = state(chat(status="found", reply="Found", **dict(video, video="failed", video_message="no")))
        self.assertFalse(bar_state.foldable(failed))  # a failed video keeps any done card open
        self.assertIn("video_retry", failed.actions)
        done = state(chat(status="done", reply="A room.", **video))  # the done card has its own line: not twice
        self.assertEqual(done.reply.count(line), 1)
        self.assertNotIn(line, done.note)

    def test_video_actions_are_not_advanced(self):
        for name in ("video_stop", "video_retry", "video_open", "video_file", "video_make", "video_another"):
            self.assertNotIn(name, bar_state.ADVANCED_ACTIONS)
            self.assertIn(name, bar_state._HIT_ORDER)


class FoldTest(unittest.TestCase):
    def done(self, **kw):
        return state(chat(status="done", reply="A room.", cost_text="34 ROUNDS · 6 MIN · $0.38", **kw))

    def test_a_plain_done_card_may_fold(self):
        self.assertTrue(bar_state.foldable(self.done()))
        self.assertTrue(bar_state.foldable(self.done(failed_stage="detail")))  # Retry stage shows on the line

    def test_a_card_with_a_choice_or_no_run_never_folds(self):
        self.assertFalse(bar_state.foldable(self.done(unchanged=True)))  # nothing changed: Retry is the answer
        self.assertFalse(bar_state.foldable(self.done(blocked=["Wall"])))  # "Also let it change Wall"
        self.assertFalse(bar_state.foldable(self.done(missing=["lamp"])))  # "Build the missing things"
        menu = self.done()
        menu.camera_menu = [("Camera", "", True)]
        self.assertFalse(bar_state.foldable(menu))
        for c in (chat(), chat(running=True, status="running", stages={"layout": "active"}),
                  chat(status="stopped", failed_stage="light", stages={"light": "failed"}),
                  chat(error="API key was rejected (HTTP 401).")):
            self.assertFalse(bar_state.foldable(state(c)))

    def test_it_first_folds_four_seconds_after_the_card_shows_then_follows_the_mouse_at_once(self):
        after = tokens.FOLD_AFTER
        self.assertFalse(bar_state.folded(None, False, 1000.0))
        self.assertFalse(bar_state.folded(100.0, False, 100.0 + after - 0.1))
        self.assertTrue(bar_state.folded(100.0, False, 100.0 + after))
        self.assertFalse(bar_state.folded(100.0, True, 200.0))  # the mouse is on the bar: open
        self.assertTrue(bar_state.folded(100.0, False, 200.0))  # it left: folded at once, no new wait
        self.assertFalse(bar_state.folded(100.0, False, 101.0))  # left within the first 4 s: still open
