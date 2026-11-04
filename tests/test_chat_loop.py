import json
import threading
import time
import unittest
from unittest import mock

from eachlabs import chat_loop
from eachlabs.api_client import ApiError
from eachlabs.chat import model_calls
from eachlabs.chat_loop import Executor, Limits, RunResult, run


def tool_msg(*calls):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c%d" % i, "type": "function",
         "function": {"name": n, "arguments": a if isinstance(a, str) else json.dumps(a)}}
        for i, (n, a) in enumerate(calls)]}}]}


def text_msg(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


GROUND = ("run_python", {"code": "# ground\nbpy.data.objects.new('Ground', None)"})
ROW = ("run_python", {"code": "# a row of boxes\nfor i in range(3):\n    pass"})
TEXTS = [text_msg(t) for t in "abcde"]


def every(rounds):
    """The same round budget for every stage."""
    return {stage: rounds for stage in chat_loop.STAGES}


def steps_in(body):
    """The step summaries a stage's user message carries."""
    start = body.index("```json\n") + 8
    return json.loads(body[start:body.index("\n```", start)])


class Rig:
    def __init__(self, responses=None, loop=None, execute=None):
        self.calls = []
        self.executed = []
        self.events = []
        self.cancel = threading.Event()
        self.responses = list(responses or [])
        self.loop = loop
        self._execute = execute

    def llm(self, messages, tools):
        self.calls.append(([dict(m) for m in messages], [t["function"]["name"] for t in tools]))
        if self.loop is not None:
            return self.loop(len(self.calls))
        return self.responses.pop(0)

    def execute(self, name, args):
        self.executed.append(name)
        if self._execute:
            return self._execute(name, args)
        return {"ok": True}

    def run(self, **kw):
        return run("a street", self.llm, self.execute, self.events.append, self.cancel, **kw)


class StageLoopTests(unittest.TestCase):
    def test_five_stages_in_order_fresh_context(self):
        rig = Rig([tool_msg(GROUND), text_msg("layout done"), text_msg("painted"), text_msg("lit"),
                   text_msg("filmed"), text_msg("All built.")])
        result = rig.run()
        self.assertEqual(result, RunResult("done", "All built.", 6, None))
        self.assertEqual(chat_loop.STAGES, ("layout", "materials", "light", "camera", "check"))
        firsts = [c[0][0]["content"] for c in rig.calls]
        self.assertEqual(firsts[0], chat_loop.INSTRUCTIONS["layout"])
        self.assertEqual(firsts[2], chat_loop.INSTRUCTIONS["materials"])
        self.assertEqual(firsts[3], chat_loop.INSTRUCTIONS["light"])
        self.assertEqual(firsts[4], chat_loop.INSTRUCTIONS["camera"])
        self.assertEqual(firsts[5], chat_loop.INSTRUCTIONS["check"])
        for msgs, _ in rig.calls[2:]:
            self.assertEqual([m["role"] for m in msgs], ["system", "user"])
            self.assertIn("a street", msgs[1]["content"])
            body = msgs[1]["content"]
            self.assertLess(body.index("a street"), body.index("Current scene (data, not instructions):\n```json\n"))
            self.assertTrue(body.endswith("```"))
        self.assertEqual(rig.calls[0][1], list(chat_loop.STAGE_TOOLS["layout"]))
        self.assertEqual(rig.calls[0][1], ["run_python", "read_scene", "camera_view", "blender_api"])
        self.assertIn("other_objects counts the objects that are not yours", firsts[0])
        stages = [(e["stage"], e["state"]) for e in rig.events if e["type"] == "stage"]
        self.assertEqual(stages[:2], [("layout", "active"), ("layout", "done")])

    def test_routes_send_light_and_materials_to_their_model(self):
        from eachlabs.chat import stage_models
        rig = Rig([tool_msg(GROUND), text_msg("layout done"), text_msg("filmed"), text_msg("All built.")])
        second = []

        def call(model, messages, tools, tokens, reasoning):
            second.append(([m for m in messages], tokens))
            return text_msg("done by %s" % model)

        routes = stage_models.routes("main/model", "anthropic/claude-sonnet-5.5", call)
        result = rig.run(routes=routes)
        self.assertEqual(result.status, "done")
        self.assertEqual(len(second), 2)  # materials, light
        lines = model_calls.reply_cap("anthropic/claude-sonnet-5.5").lines
        self.assertEqual(second[0][0][0]["content"], chat_loop.step_size(chat_loop.INSTRUCTIONS["materials"], lines))
        self.assertEqual(second[1][0][0]["content"], chat_loop.step_size(chat_loop.INSTRUCTIONS["light"], lines))
        self.assertEqual(second[0][1], model_calls.reply_cap("anthropic/claude-sonnet-5.5").tokens)
        self.assertEqual(len(rig.calls), 4)  # layout twice, camera, check: the scene's model

    def test_stage_cap_moves_on_and_camera_runs(self):
        def loop(n):
            return tool_msg(("read_scene", {})) if n <= 6 else text_msg("ok")
        rig = Rig(loop=loop)
        result = rig.run()
        self.assertEqual(result.status, "done")
        self.assertEqual(len(rig.calls), 10)
        self.assertEqual(rig.calls[6][0][0]["content"], chat_loop.INSTRUCTIONS["materials"])
        self.assertEqual(rig.calls[8][0][0]["content"], chat_loop.INSTRUCTIONS["camera"])
        self.assertEqual(rig.calls[9][0][0]["content"], chat_loop.INSTRUCTIONS["check"])

    def test_stage_budgets(self):
        self.assertEqual(chat_loop.STAGE_ROUNDS, {"layout": 4, "materials": 3, "light": 3, "camera": 3, "check": 2})
        self.assertEqual(chat_loop.TOTAL_ROUNDS, 15)
        self.assertEqual(Limits().total_rounds, 15)
        rig = Rig(loop=lambda n: tool_msg(("read_scene", {})))
        result = rig.run()
        self.assertEqual(result.status, "done")
        per_stage = {}
        for messages, _ in rig.calls:
            stage = next(s for s in chat_loop.STAGES if messages[0]["content"] == chat_loop.INSTRUCTIONS[s])
            per_stage[stage] = per_stage.get(stage, 0) + 1
        self.assertEqual(per_stage, chat_loop.STAGE_ROUNDS)

    def test_rounds_for(self):
        self.assertEqual(Limits().rounds_for("layout"), 4)
        self.assertEqual(Limits(stage_rounds=every(2)).rounds_for("layout"), 2)
        self.assertEqual(set(chat_loop.STAGE_TOOLS), set(chat_loop.STAGES) | {chat_loop.COMPLETE, chat_loop.EDIT,
                                                                               chat_loop.FIX})
        self.assertEqual(Limits().rounds_for(chat_loop.EDIT), 3)
        self.assertEqual(Limits(stage_rounds={"camera": 5}).rounds_for("camera"), 5)
        self.assertEqual(Limits(stage_rounds={"camera": 5}).rounds_for("check"), 2)
        self.assertEqual(Limits().rounds_for(chat_loop.COMPLETE), 2)

    def test_total_cap_ends_as_done(self):
        rig = Rig(loop=lambda n: tool_msg(("read_scene", {})))
        result = rig.run(limits=Limits(total_rounds=16, stage_rounds=every(10)))
        self.assertEqual(result, RunResult("done", "\n".join([
            "Stopped after 16 rounds. What was built is kept.", "Light: skipped, the round limit was reached.",
            "Camera: skipped, the round limit was reached."]), 16, None))
        self.assertEqual(len(rig.calls), 16)
        self.assertEqual(rig.calls[-1][0][0]["content"], chat_loop.INSTRUCTIONS["check"])
        self.assertEqual(rig.calls[-1][1], [])  # the check's one round goes without tools

    def test_a_cap_below_the_stage_shares_ends_with_the_checks_reply(self):
        # Ten rounds against fifteen stage rounds: the camera stage is cut, and the last round is the check's.
        def loop(n):
            return text_msg("A small street.") if n == 10 else tool_msg(GROUND)
        rig = Rig(loop=loop)
        result = rig.run(limits=Limits(total_rounds=10))
        self.assertEqual(result, RunResult("done", "A small street.\nCamera: skipped, the round limit was reached.",
                                           10, None))
        stages = [(e["stage"], e["state"]) for e in rig.events if e["type"] == "stage"]
        self.assertEqual([s for s, state in stages if state == "active"], ["layout", "materials", "light", "check"])

    def test_an_edit_runs_one_short_stage_and_ends_with_its_reply(self):
        rig = Rig(loop=lambda n: tool_msg(GROUND))
        result = rig.run(stages=(chat_loop.EDIT,), earlier=("a street",))
        self.assertEqual(len(rig.calls), 3)
        self.assertEqual({c[0][0]["content"] for c in rig.calls}, {chat_loop.INSTRUCTIONS[chat_loop.EDIT]})
        self.assertIn("change only the target", chat_loop.INSTRUCTIONS[chat_loop.EDIT])
        self.assertEqual(rig.calls[-1][1], [])  # its last round goes without tools
        self.assertEqual(rig.calls[-1][0][-1], {"role": "user", "content": chat_loop.LAST_EDIT_ROUND})
        stages = [(e["stage"], e["state"]) for e in rig.events if e["type"] == "stage"]
        self.assertEqual(stages, [("edit", "active"), ("edit", "done")])
        rig = Rig([tool_msg(GROUND), text_msg("The house is red now.")])
        result = rig.run(stages=(chat_loop.EDIT,), earlier=("a street",))
        self.assertEqual(result, RunResult("done", "The house is red now.", 2, None))

    def test_only_the_materials_stage_offers_textures_and_says_how_many(self):
        rig = Rig(loop=lambda n: text_msg("ok"))
        rig.run(textures=4)
        offered = {c[0][0]["content"].split("This stage: ")[1].split(".")[0]: c[1] for c in rig.calls}
        self.assertEqual(offered["the materials"], ["run_python", "read_scene", "camera_view", "blender_api", "generate_texture"])
        self.assertEqual(offered["the layout"], ["run_python", "read_scene", "camera_view", "blender_api"])
        materials = next(c[0][0]["content"] for c in rig.calls if "This stage: the materials" in c[0][0]["content"])
        self.assertIn("at most 4 more in this scene", materials)
        rig = Rig(loop=lambda n: text_msg("ok"))
        rig.run()
        self.assertTrue(all("generate_texture" not in c[1] for c in rig.calls))

    def test_the_concept_picture_goes_to_the_layout_and_materials_stages(self):
        rig = Rig(loop=lambda n: text_msg("ok"))
        picture = "data:image/jpeg;base64,AAAA"
        rig.run(concept=picture)
        with_picture = []
        for messages, _tools in rig.calls:
            stage = messages[0]["content"].split("This stage: ")[1].split(".")[0]
            images = [part for m in messages if isinstance(m["content"], list) for part in m["content"]
                      if part.get("type") == "image_url"]
            if images:
                with_picture.append(stage)
                self.assertEqual(images[0]["image_url"]["url"], picture)
                self.assertEqual(messages[2]["content"][0]["text"], chat_loop.CONCEPT_NOTE)
        self.assertEqual(with_picture, ["the layout", "the materials"])

    def test_the_debug_log_leaves_pictures_out(self):
        record = {"messages": [{"content": [{"image_url": {"url": "data:image/jpeg;base64," + "A" * 50}}]}]}
        self.assertEqual(chat_loop._without_images(record)["messages"][0]["content"][0]["image_url"]["url"],
                         "[image, 73 characters]")

    def test_total_cap_between_stages_ends_as_done(self):
        rig = Rig(loop=lambda n: tool_msg(("read_scene", {})))
        result = rig.run(limits=Limits(total_rounds=5, stage_rounds=every(2)))
        self.assertEqual(result.message.splitlines()[0], "Stopped after 5 rounds. What was built is kept.")
        stages = [(e["stage"], e["state"]) for e in rig.events if e["type"] == "stage"]
        self.assertEqual(stages, [("layout", "active"), ("layout", "done"), ("materials", "active"),
                                  ("materials", "done"), ("check", "active"), ("check", "done")])
        self.assertEqual(result.message.splitlines()[1:], ["Light: skipped, the round limit was reached.",
                                                           "Camera: skipped, the round limit was reached."])

    def test_three_failures_end_run(self):
        def boom(name, args):
            if name == "run_python":
                raise RuntimeError("no room")
            return {}
        rig = Rig(loop=lambda n: tool_msg(ROW), execute=boom)
        result = rig.run()
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.message, "Stopped: run_python kept failing: no room")
        self.assertEqual(result.failed_stage, "layout")
        self.assertEqual(len(rig.calls), 3)
        self.assertIn(("layout", "failed"),
                      [(e["stage"], e["state"]) for e in rig.events if e["type"] == "stage"])

    def test_a_stuck_stage_is_left_partly_done_and_the_run_goes_on(self):
        def stuck_light(name, args):
            if name == "run_python" and "look" in args["code"]:
                return {"ok": False, "error": 'TypeError: bpy_struct: item.attr = val: enum "Medium High Contrast" '
                                              "not found in ('None', 'AgX - Punchy', 'AgX - Medium High Contrast')"}
            return {"ok": True}
        look = ("run_python", {"code": "# the look\nscene.view_settings.look = 'Medium High Contrast'"})
        rig = Rig([tool_msg(GROUND), text_msg("laid out"), text_msg("painted"), tool_msg(look), tool_msg(look),
                   tool_msg(look), text_msg("filmed"), text_msg("A town at dusk.")], execute=stuck_light)
        result = rig.run(limits=Limits(stage_rounds=every(3), total_rounds=20))
        self.assertEqual(result.status, "done")
        self.assertEqual(result.message, "A town at dusk.\nLight: partly done, run_python kept failing: TypeError: "
                                         "bpy_struct: item.attr = val: enum \"Medium High Contrast\" not found in "
                                         "('None', 'AgX - Punchy', 'AgX - Medium High Contrast').")
        states = [(e["stage"], e["state"]) for e in rig.events if e["type"] == "stage" and e["state"] != "active"]
        self.assertEqual(states, [("layout", "done"), ("materials", "done"), ("light", "partial"),
                                  ("camera", "done"), ("check", "done")])
        told = [m["content"] for m in rig.calls[4][0] if m["role"] == "tool"][-1]
        self.assertIn("Use one of these values exactly: 'None', 'AgX - Punchy', 'AgX - Medium High Contrast'.", told)

    def test_two_stuck_stages_in_a_row_stop_the_run(self):
        def boom(name, args):
            if name == "run_python" and "fail" in args["code"]:
                raise RuntimeError("no room")
            return {"ok": True}
        bad = ("run_python", {"code": "# fail"})
        rig = Rig([tool_msg(GROUND), text_msg("laid out")] + [tool_msg(bad)] * 6, execute=boom)
        result = rig.run(limits=Limits(stage_rounds=every(3), total_rounds=20))
        self.assertEqual((result.status, result.failed_stage), ("stopped", "light"))
        self.assertEqual(result.message, "Stopped: run_python kept failing: no room")

    def test_bare_meshes_after_the_materials_stage_get_one_more_round(self):
        reads = []

        def scene(name, args):
            if name == "read_scene":
                reads.append(1)
                bare = ["Front shrub 00", "Front shrub 01"] if len(reads) <= 4 else []
                return {"objects": [], "lights": [{"name": "Sun"}], **({"no_material": bare} if bare else {})}
            return {"ok": True}
        rig = Rig(loop=lambda n: text_msg("ok"), execute=scene)
        rig.run(limits=Limits(stage_rounds=every(1), total_rounds=20))
        told = [m["content"] for c in rig.calls for m in c[0] if m["role"] == "user"
                and m["content"].startswith("These meshes of yours have no material")]
        self.assertEqual(told[:1], ["These meshes of yours have no material, so they render plain white: Front shrub 00,"
                                    " Front shrub 01. Give each a material that fits it now, in one run_python step: a "
                                    "loop over them by name."])
        materials_calls = [c for c in rig.calls if "This stage: the materials" in c[0][0]["content"]]
        self.assertEqual(len(materials_calls), 2)  # its one round and the extra one

    def test_enum_hint(self):
        self.assertEqual(chat_loop.enum_hint('enum "X" not found in (\'A\', \'B - C\')'),
                         "Use one of these values exactly: 'A', 'B - C'.")
        self.assertEqual(chat_loop.enum_hint("NameError: x"), "")
        self.assertEqual(chat_loop.enum_hint(None), "")
        self.assertIn('Under AgX a look\'s name starts with "AgX - "', chat_loop.INSTRUCTIONS["light"])

    def test_stop_run_ends_the_run_without_a_tool_result(self):
        def stop(name, args):
            if name == "run_python":
                raise chat_loop.StopRun("A step changed the settings.")
            return {}
        rig = Rig(loop=lambda n: tool_msg(ROW, GROUND), execute=stop)
        result = rig.run()
        self.assertEqual((result.status, result.message, result.failed_stage),
                         ("stopped", "A step changed the settings.", "layout"))
        self.assertEqual(len(rig.calls), 1)
        self.assertEqual(rig.executed, ["read_scene", "run_python"])  # the second call never runs
        tools = [e for e in rig.events if e["type"] == "tool"]
        self.assertEqual([(e["state"], e["detail"]) for e in tools],
                         [("running", ""), ("error", "A step changed the settings.")])
        self.assertIn(("layout", "failed"), [(e["stage"], e["state"]) for e in rig.events if e["type"] == "stage"])

    def test_success_resets_failure_count(self):
        state = {"n": 0}

        def flaky(name, args):
            if name == "run_python":
                state["n"] += 1
                if state["n"] != 3:
                    raise RuntimeError("x")
            return {}
        rig = Rig(loop=lambda n: tool_msg(ROW) if n <= 5 else text_msg("ok"), execute=flaky)
        self.assertEqual(rig.run(limits=Limits(stage_rounds=every(6), total_rounds=30)).status, "done")

    def test_bad_args_go_back_to_model(self):
        rig = Rig([tool_msg(("run_python", {"code": ""})), tool_msg(ROW)] + TEXTS)
        rig.run()
        tools = [m for m in rig.calls[1][0] if m["role"] == "tool"]
        self.assertTrue(tools[0]["content"].startswith("ERROR: run_python: code is required"))
        self.assertEqual(tools[0]["tool_call_id"], "c0")
        self.assertEqual(rig.executed.count("run_python"), 1)

    def test_invalid_json_and_unknown_tool(self):
        rig = Rig([tool_msg(("run_python", "{oops"), ("set_camera_move", {}))] + TEXTS)
        rig.run()
        tools = [m["content"] for m in rig.calls[1][0] if m["role"] == "tool"]
        self.assertEqual(tools[0], "ERROR: arguments were not valid JSON")
        self.assertEqual(tools[1], "ERROR: set_camera_move is not a tool; use run_python, read_scene, camera_view or blender_api")

    def test_http_error_ends_run(self):
        def llm_raises(n):
            raise ApiError("API key was rejected (HTTP 401).", 401)
        rig = Rig(loop=llm_raises)
        result = rig.run()
        self.assertEqual(result, RunResult("stopped", "API key was rejected (HTTP 401).", 1, "layout"))
        self.assertEqual(rig.events[-1], {"type": "stage", "stage": "layout", "state": "failed"})

    def test_any_model_call_error_ends_run_with_failed_stage(self):
        def llm_raises(n):
            raise ValueError("boom")
        rig = Rig(loop=llm_raises)
        result = rig.run()
        self.assertEqual(result, RunResult("stopped", "The model call failed: boom", 1, "layout"))
        self.assertEqual(rig.events[-1], {"type": "stage", "stage": "layout", "state": "failed"})
        self.assertIn({"type": "thinking", "since": None}, rig.events)

    def test_rate_limit_shows_busy(self):
        def llm_raises(n):
            raise ApiError("Rate limit exceeded. Please retry after a short delay. (HTTP 400)", 400)
        result = Rig(loop=llm_raises).run()
        self.assertEqual(result.message, chat_loop.BUSY)
        self.assertEqual(result.failed_stage, "layout")

    def test_filtered_tool_calls_send_no_empty_list(self):
        bad = {"choices": [{"message": {"role": "assistant", "content": None,
                                        "tool_calls": [{"function": {"name": "read_scene"}}]}}]}
        rig = Rig([bad] + TEXTS)
        rig.run()
        assistant = [m for m in rig.calls[1][0] if m["role"] == "assistant"]
        self.assertEqual(assistant, [{"role": "assistant", "content": ""}])

    def test_temp_override_line_only_before_python_3_12(self):
        for races, follow_up in ((True, False), (True, True), (False, False), (False, True)):
            with self.subTest(races=races, follow_up=follow_up), \
                    mock.patch.object(chat_loop.thread_safety, "override_races", return_value=races):
                rig = Rig([text_msg(t) for t in "abcde"])
                rig.run(earlier=["a road"] if follow_up else ())
                table = chat_loop.FOLLOW_UP_INSTRUCTIONS if follow_up else chat_loop.INSTRUCTIONS
                firsts = [c[0][0]["content"] for c in rig.calls]
                self.assertEqual(len(firsts), len(chat_loop.STAGES))
                for stage, system in zip(chat_loop.STAGES, firsts):
                    if races:
                        self.assertEqual(system.count(chat_loop.OVERRIDE_RULE), 1)
                        self.assertEqual(system.replace(chat_loop.OVERRIDE_RULE, ""), table[stage])
                        self.assertTrue(system.endswith(chat_loop._CLOSE))
                        for name in ("object.quick_fur", "quick_explode", "quick_smoke", "quick_liquid"):
                            self.assertIn(name, system)
                    else:
                        self.assertEqual(system, table[stage])
                        self.assertNotIn("temp_override", system)
                        self.assertNotIn("quick_", system)

    def test_instructions_name_the_refused_imports_and_literal_attribute_names(self):
        for text in list(chat_loop.INSTRUCTIONS.values()) + list(chat_loop.FOLLOW_UP_INSTRUCTIONS.values()):
            self.assertIn("including re, collections, itertools, statistics and bpy_extras", text)
            self.assertIn('need the attribute name as a plain string, like setattr(obj, "location", v)', text)

    def test_version_notes_follow_the_blender_version(self):
        for stage in chat_loop.STAGES:
            five = chat_loop.system_text(chat_loop.INSTRUCTIONS[stage], (5, 2, 3))
            four = chat_loop.system_text(chat_loop.INSTRUCTIONS[stage], (4, 2, 23))
            self.assertEqual(five, chat_loop.system_text(chat_loop.INSTRUCTIONS[stage]))
            self.assertIn("This is Blender 5.", five)
            self.assertIn('"BLENDER_EEVEE"', five)
            self.assertNotIn("Blender 4", five)
            self.assertIn("This is Blender 4.", four)
            self.assertIn("obj.animation_data.action.fcurves", four)
            self.assertIn('"BLENDER_EEVEE_NEXT"', four)
            self.assertNotIn("This is Blender 5", four)
            for text in (four, five):
                self.assertIn("A world has no diffuse_color", text)
                self.assertIn('world.node_tree.nodes.get("Background")', text)

    def test_the_run_sends_the_notes_for_its_version(self):
        rig = Rig(list(TEXTS))
        rig.run(blender=(4, 2, 23))
        self.assertTrue(all("This is Blender 4." in c[0][0]["content"] for c in rig.calls))

    def test_instructions_ask_for_detail_and_real_lights(self):
        for table in (chat_loop.INSTRUCTIONS, chat_loop.FOLLOW_UP_INSTRUCTIONS):
            self.assertIn("senior 3D environment artist", table["layout"])
            self.assertIn("the person's lights are not yours and do not count", table["light"])
            self.assertIn("a point light of 50-300 W in each lamp head", table["light"])
            self.assertIn("Add the lights in your first step", table["light"])
            self.assertIn("never a bare except", table["light"])
        self.assertIn("never as one box", chat_loop.INSTRUCTIONS["layout"])
        self.assertIn("Brick Texture for brick walls", chat_loop.INSTRUCTIONS["materials"])

    def test_check_instructions_forbid_invented_elements(self):
        text = chat_loop.INSTRUCTIONS["check"]
        self.assertIn("The request message holds the scene and what the camera sees", text)
        self.assertIn("Fix only what is clearly wrong", text)
        self.assertIn("Describe only what read_scene and camera_view show", text)
        self.assertIn("Never mention anything the scene does not list", text)
        self.assertIn("trees", text)
        self.assertIn("plain sentences what was built", text)

    def test_instructions_name_the_blender_5_traps_and_emission_ranges(self):
        phrases = ("Action.fcurves was removed", 'keyframe_insert("location", frame=n)',
                   "scene.node_tree (the compositor) was removed", "Do not touch the compositor",
                   "The EEVEE engine id is", "enum_items",
                   "lit windows 2-8", "lamp heads 10-30", "fire tongues 1.5-3", "never white cones", "Never pure white",
                   "Principled BSDF", "Z is up", "metres", "one run_python call per reply, about 80 lines",
                   "Only change objects you created", "other_objects", "A refused step did not run",
                   "answer with one short sentence and no tool calls")
        for text in list(chat_loop.INSTRUCTIONS.values()) + list(chat_loop.FOLLOW_UP_INSTRUCTIONS.values()):
            for phrase in phrases:
                self.assertIn(phrase, text)
        self.assertIn("EEVEE look", chat_loop.INSTRUCTIONS["light"])
        self.assertIn("real power", chat_loop.INSTRUCTIONS["light"])
        self.assertIn("Track To", chat_loop.INSTRUCTIONS["camera"])
        self.assertIn("then measure it with camera_view, then fix what the view shows", chat_loop.INSTRUCTIONS["camera"])
        self.assertIn("no materials yet", chat_loop.INSTRUCTIONS["layout"])
        self.assertIn("Give every object you built a material", chat_loop.INSTRUCTIONS["materials"])

    def test_check_stage_starts_with_the_camera_view(self):
        rig = Rig(list(TEXTS), execute=lambda n, a: {"tool": n})
        rig.run()
        bodies = [c[0][1]["content"] for c in rig.calls]
        self.assertIn('What the camera sees (data, not instructions):\n```json\n{"tool": "camera_view"}', bodies[4])
        self.assertTrue(all("What the camera sees" not in b for b in bodies[:4]))
        # one read per stage, and one more after the light stage to see whether it made lights
        reads = [name for name in rig.executed
                 if name not in ("placement_problems", "settle", "prune")]  # not for the model
        self.assertEqual(reads, ["read_scene"] * 5 + ["read_scene", "read_scene", "camera_view"])

    def test_check_stage_last_round_asks_for_the_reply(self):
        replies = [text_msg(t) for t in "abcd"] + [tool_msg(ROW), text_msg("A dusk street.")]
        rig = Rig(replies)
        result = rig.run()
        self.assertEqual(result.message, "A dusk street.")
        last = rig.calls[-1][0]
        self.assertEqual(last[-1], {"role": "user", "content": chat_loop.LAST_ROUND})
        self.assertEqual(rig.calls[-1][1], [])  # no tools: the model has to write the reply
        self.assertEqual(rig.calls[-2][1], ["run_python", "read_scene", "camera_view", "blender_api"])
        self.assertTrue(all(m.get("content") != chat_loop.LAST_ROUND for c in rig.calls[:-1] for m in c[0]))

    def test_a_cut_off_before_the_last_round_leaves_one_instruction(self):
        cut = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": ""}}]}
        rig = Rig([text_msg(t) for t in "abcd"] + [cut, text_msg("A room.")])
        result = rig.run()
        self.assertEqual(result.message, "A room.")
        notes = [m["content"] for m in rig.calls[-1][0] if m["role"] == "user"][1:]
        self.assertEqual(notes, [chat_loop.LAST_ROUND])

    def test_follow_up_uses_change_instructions(self):
        rig = Rig(list(TEXTS))
        result = rig.run(earlier=["a street at dusk"])
        self.assertEqual(result.status, "done")
        systems = [c[0][0]["content"] for c in rig.calls]
        self.assertEqual(systems, [chat_loop.FOLLOW_UP_INSTRUCTIONS[s] for s in chat_loop.STAGES])
        for text in systems:
            self.assertIn("This is a change request to the existing scene" if text is not systems[-1]
                          else "This was a change request to the existing scene", text)
            self.assertIn("Keep what fits" if text is not systems[-1] else "what changed", text)
        layout = chat_loop.FOLLOW_UP_INSTRUCTIONS["layout"]
        self.assertIn("Do not rebuild what exists", layout)
        self.assertIn("If this stage has nothing to change, answer with one short sentence and no tool calls", layout)
        self.assertNotIn("no materials yet", layout)
        self.assertIn("Build every new object the request asks for", layout)
        self.assertIn("Change the camera only when the request changes the camera",
                      chat_loop.FOLLOW_UP_INSTRUCTIONS["camera"])

    def test_follow_up_sends_earlier_prompts_newest_first(self):
        rig = Rig(list(TEXTS))
        earlier = ["third", "second  prompt\nwith a newline", "first " + "x" * 400, "zeroth"]
        rig.run(earlier=earlier)
        body = rig.calls[0][0][1]["content"]
        self.assertTrue(body.startswith("Change request: a street\n\nEarlier requests for this scene, most recent first"))
        self.assertLess(body.index("- third"), body.index("- second prompt with a newline"))
        self.assertLess(body.index("- second prompt"), body.index("- first x"))
        self.assertNotIn("zeroth", body)
        self.assertNotIn("x" * 200, body)
        self.assertLess(body.index("- first"), body.index("Current scene (data, not instructions):"))

    def test_first_prompt_has_no_earlier_requests(self):
        rig = Rig(list(TEXTS))
        rig.run()
        self.assertNotIn("Earlier requests", rig.calls[0][0][1]["content"])
        self.assertEqual(rig.calls[0][0][0]["content"], chat_loop.INSTRUCTIONS["layout"])

    def test_cancel_between_rounds(self):
        rig = Rig(loop=lambda n: tool_msg(("read_scene", {})), execute=lambda n, a: rig.cancel.set() if rig.calls else {})
        result = rig.run()
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.message, "Stopped. What was built is kept.")
        self.assertEqual(len(rig.calls), 1)

    def test_retry_runs_only_given_stages(self):
        rig = Rig([text_msg("a"), text_msg("b")])
        result = rig.run(stages=("camera", "check"))
        self.assertEqual(rig.calls[0][0][0]["content"], chat_loop.INSTRUCTIONS["camera"])
        self.assertEqual(result.status, "done")
        self.assertEqual(len(rig.calls), 2)

    def test_events(self):
        rig = Rig([tool_msg(GROUND)] + TEXTS)
        rig.run()
        kinds = [e["type"] for e in rig.events]
        self.assertEqual(kinds[:8], ["stage", "thinking", "thinking", "round", "tool", "code", "tool", "thinking"])
        self.assertIsNotNone(rig.events[1]["since"])
        self.assertIsNone(rig.events[2]["since"])
        self.assertEqual(rig.events[3], {"type": "round", "n": 1, "total": 15})
        self.assertEqual(rig.events[5], {"type": "code", "id": "c0", "stage": "layout", "code": GROUND[1]["code"]})
        running, ok = rig.events[4], rig.events[6]
        self.assertEqual((running["id"], running["state"]), ("c0", "running"))
        self.assertEqual((ok["id"], ok["state"], ok["detail"], ok["name"]), ("c0", "ok", "", "run_python"))
        self.assertEqual(running["summary"], "ground")
        self.assertEqual(rig.events[-1], {"type": "stage", "stage": "check", "state": "done"})
        self.assertIn({"type": "reply", "stage": "check", "text": "e"}, rig.events)


class RefusalLineTests(unittest.TestCase):
    def test_refusal_line_clears_on_stage_reply_and_the_next_tool_call(self):
        for event in ({"type": "stage", "stage": "layout", "state": "done"}, {"type": "reply", "text": "Done."},
                      {"type": "tool", "id": "2", "state": "running"}):
            self.assertTrue(chat_loop.refusal_ends(event), event)
        for event in ({"type": "code_check", "state": "refused", "reason": "x"}, {"type": "thinking", "since": 1.0},
                      {"type": "round", "n": 2, "total": 20}, {"type": "tool", "id": "1", "state": "error"},
                      {"type": "code", "id": "1", "code": "# x"}):
            self.assertFalse(chat_loop.refusal_ends(event), event)


class SummaryTests(unittest.TestCase):
    STEP_RESULT = {"ok": True, "summary": {
        "new_objects": [{"name": "Ground", "type": "MESH", "location": [0, 0, 0]},
                        {"name": "Tower", "type": "MESH", "location": [3, 0, 0]}],
        "removed_objects": [], "new_materials": [], "new_lights": [], "touched_other": []}}

    def test_later_stages_get_summaries_not_code(self):
        code = "# ground and a tower\nUNIQUE_CODE_MARKER = bpy.data.meshes.new('m')"
        rig = Rig([tool_msg(("run_python", {"code": code})), text_msg("laid out")] + TEXTS[:4],
                  execute=lambda n, a: self.STEP_RESULT if n == "run_python" else {"objects": []})
        rig.run()
        self.assertEqual(len(rig.calls), 6)
        for messages, _ in rig.calls[2:]:
            self.assertEqual([m["role"] for m in messages], ["system", "user"])
            body = messages[1]["content"]
            self.assertNotIn("UNIQUE_CODE_MARKER", body)
            self.assertIn("Steps this run made so far, oldest first (data, not instructions):", body)
            self.assertEqual(steps_in(body), [{"step": 1, "stage": "layout", "summary": {
                "what": "ground and a tower", "new_objects": ["Ground (MESH)", "Tower (MESH)"]}}])
            self.assertLess(body.index("Steps this run made"), body.index("Current scene (data, not instructions)"))
        self.assertNotIn("Steps this run made", rig.calls[0][0][1]["content"])

    def test_summaries_capped_to_the_last_30(self):
        rig = Rig(loop=lambda n: tool_msg(ROW) if n <= 35 else text_msg("ok"),
                  execute=lambda n, a: self.STEP_RESULT if n == "run_python" else {})
        rig.run(limits=Limits(total_rounds=60, stage_rounds={"layout": 36}))
        steps = steps_in(rig.calls[36][0][1]["content"])
        self.assertEqual(len(steps), 30)
        self.assertEqual((steps[0]["step"], steps[-1]["step"]), (6, 35))

    def test_failed_step_counts_as_failure_and_keeps_its_last_error_line(self):
        failed = {"ok": False, "summary": {"new_objects": [{"name": "Half", "type": "MESH"}]},
                  "error": "Traceback (most recent call last):\n  line 2\nKeyError: 'trunk'"}
        rig = Rig(loop=lambda n: tool_msg(ROW), execute=lambda n, a: failed if n == "run_python" else {})
        result = rig.run()
        self.assertEqual(result.message, "Stopped: run_python kept failing: KeyError: 'trunk'")
        self.assertEqual(len(rig.calls), 3)
        tool = [m for m in rig.calls[1][0] if m["role"] == "tool"][0]
        self.assertEqual(json.loads(tool["content"]), failed)
        errors = [e for e in rig.events if e["type"] == "tool" and e["state"] == "error"]
        self.assertEqual(errors[0]["detail"], "KeyError: 'trunk'")
        summary = chat_loop.step_summary("# trunk", failed)
        self.assertEqual(summary, {"what": "trunk", "new_objects": ["Half (MESH)"], "error": "KeyError: 'trunk'"})

    def test_step_summary_caps_lists_and_keeps_world_and_camera(self):
        result = {"ok": True, "summary": {"new_objects": [{"name": "o%d" % i, "type": "MESH"} for i in range(20)],
                                          "touched_other": 2, "world": {"name": "w"},
                                          "frame_range": [1, 120]}}
        summary = chat_loop.step_summary("x = 1", result)
        self.assertEqual(len(summary["new_objects"]), 13)
        self.assertEqual(summary["new_objects"][-1], "+8 more")
        self.assertEqual(summary["touched_other"], 2)
        self.assertEqual((summary["world"], summary["frame_range"]), ({"name": "w"}, [1, 120]))
        self.assertNotIn("what", summary)

    def test_debug_log_writes_each_call_with_secrets_redacted(self):
        import os
        import tempfile
        secret = "el-test-credential-1234"
        rig = Rig([tool_msg(ROW), text_msg("a " + secret)] + TEXTS[:4],
                  execute=lambda n, a: {"ok": True, "output": "key " + secret})
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "chat.jsonl")
            with mock.patch.dict(os.environ, {chat_loop.LOG_ENV: path}):
                rig.run(secrets=[secret])
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        records = [json.loads(line) for line in text.splitlines()]
        calls = [r for r in records if not r.get("end") and "settled" not in r and "replaced" not in r]
        self.assertEqual(len(calls), len(rig.calls))
        self.assertEqual(calls[0]["stage"], "layout")
        self.assertIn("reply", calls[0])
        self.assertTrue(any(r.get("end") for r in records))
        self.assertNotIn(secret, text)
        self.assertIn("[redacted]", text)

    def test_debug_log_is_off_without_the_variable(self):
        import os
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("builtins.open") as opened:
            chat_loop.debug_log({"x": 1})
        opened.assert_not_called()

    def test_secrets_never_reach_the_model(self):
        secret = "el-test-credential-9876"
        leaky = {"ok": True, "summary": {"new_objects": [{"name": "obj " + secret, "type": "MESH"}]},
                 "output": "key " + secret}

        def execute(name, args):
            if name == "run_python":
                return leaky
            if name == "camera_view":
                raise RuntimeError("failed near " + secret)
            return {"objects": [{"name": secret}]}
        rig = Rig([tool_msg(ROW), tool_msg(("camera_view", {})), text_msg("a")] + TEXTS[:4], execute=execute)
        rig.run(secrets=[secret])
        self.assertEqual(len(rig.calls), 7)
        sent = json.dumps([c[0] for c in rig.calls])
        self.assertNotIn(secret, sent)
        self.assertIn("obj [redacted]", sent)
        self.assertIn("failed near [redacted]", sent)
        self.assertNotIn(secret, json.dumps(rig.events))


class RetryTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(model_calls, "RETRY_AFTER", 0.01)
        patcher.start()
        self.addCleanup(patcher.stop)

    def failing(self, statuses, then):
        """An llm that raises ApiError with each status in turn, then answers from ``then``."""
        statuses, then, calls = list(statuses), list(then), []

        def llm(messages, tools):
            calls.append([dict(m) for m in messages])
            if statuses:
                status = statuses.pop(0)
                raise ApiError("Eachlabs did not answer in time; try again (HTTP %d)" % status, status)
            return then.pop(0)
        return llm, calls

    def test_a_502_503_or_504_is_sent_once_more_with_the_same_messages(self):
        for status in (502, 503, 504):
            llm, calls = self.failing([status], TEXTS)
            result = run("a street", llm, lambda n, a: {}, lambda e: None, threading.Event())
            self.assertEqual(result.status, "done")
            self.assertEqual(result.rounds, 5)
            self.assertEqual(len(calls), 6)
            self.assertEqual(calls[0], calls[1])

    def test_a_second_failure_stops_the_stage(self):
        llm, calls = self.failing([504, 504], TEXTS)
        result = run("a street", llm, lambda n, a: {}, lambda e: None, threading.Event())
        self.assertEqual((result.status, result.failed_stage, len(calls)), ("stopped", "layout", 2))
        self.assertIn("HTTP 504", result.message)

    def test_other_errors_are_not_retried(self):
        llm, calls = self.failing([500], TEXTS)
        result = run("a street", llm, lambda n, a: {}, lambda e: None, threading.Event())
        self.assertEqual((result.status, len(calls)), ("stopped", 1))

    def test_stop_during_the_wait_cancels(self):
        cancel = threading.Event()
        llm, calls = self.failing([504], TEXTS)

        def stopping(messages, tools):
            cancel.set()
            return llm(messages, tools)
        with mock.patch.object(model_calls, "RETRY_AFTER", 5.0):
            started = time.monotonic()
            result = run("a street", stopping, lambda n, a: {}, lambda e: None, cancel)
        self.assertEqual(result.status, "cancelled")
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(len(calls), 1)

    def test_a_reply_cut_off_before_any_call_keeps_the_stage_going(self):
        cut = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": ""}}]}
        rig = Rig([cut, tool_msg(GROUND), text_msg("layout done")] + TEXTS[:4])
        result = rig.run()
        self.assertEqual(result.status, "done")
        self.assertEqual(rig.calls[1][0][-1], {"role": "user", "content": chat_loop.CUT_OFF_REPLY})
        self.assertEqual(rig.executed.count("run_python"), 1)
        self.assertEqual(result.rounds, 7)

    def test_a_cut_off_tool_call_tells_the_model_to_split_the_step(self):
        cut = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": None,
               "tool_calls": [{"id": "c0", "type": "function",
                               "function": {"name": "run_python", "arguments": '{"code": "# half'}}]}}]}
        rig = Rig([cut] + TEXTS)
        rig.run()
        tool = [m for m in rig.calls[1][0] if m["role"] == "tool"][0]["content"]
        self.assertEqual(tool, "ERROR: " + chat_loop.CUT_OFF)
        self.assertNotIn("run_python", rig.executed)

    def test_a_call_that_used_every_token_counts_as_cut_off(self):
        # The endpoint reported tool_calls for a call the cap had cut off.
        cut = {"usage": {"completion_tokens": chat_loop.MAX_TOKENS},
               "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                            "tool_calls": [{"id": "c0", "type": "function",
                                            "function": {"name": "run_python", "arguments": '{"code": "# half'}}]}}]}
        rig = Rig([cut] + TEXTS)
        rig.run()
        tool = [m for m in rig.calls[1][0] if m["role"] == "tool"][0]["content"]
        self.assertEqual(tool, "ERROR: " + chat_loop.CUT_OFF)


class QuickStageTests(unittest.TestCase):
    def test_check_uses_the_quick_model(self):
        rig = Rig(list(TEXTS))
        quick = []

        def quick_llm(messages, tools):
            quick.append(messages[0]["content"])
            return rig.llm(messages, tools)
        rig_run = run("a street", rig.llm, rig.execute, rig.events.append, rig.cancel, quick_llm=quick_llm)
        self.assertEqual(rig_run.status, "done")
        self.assertEqual(quick, [chat_loop.INSTRUCTIONS["check"]])
        self.assertEqual(len(rig.calls), 5)

    def test_after_a_cut_off_the_stage_goes_on_without_reasoning(self):
        cut = {"usage": {"completion_tokens": chat_loop.MAX_TOKENS},
               "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": ""}}]}
        rig = Rig([cut, tool_msg(GROUND), text_msg("layout done")] + TEXTS[:4])
        quick = []

        def quick_llm(messages, tools):
            quick.append(len(rig.calls))
            return rig.llm(messages, tools)
        result = run("a street", rig.llm, rig.execute, rig.events.append, rig.cancel, quick_llm=quick_llm)
        self.assertEqual(result.status, "done")
        self.assertEqual(rig.executed.count("run_python"), 1)
        # The layout's two rounds after the cut-off, then the check stage; materials, light and camera keep it.
        self.assertEqual(quick, [1, 2, 6])

    def test_a_cut_off_tool_call_also_turns_reasoning_off(self):
        cut = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": None,
               "tool_calls": [{"id": "c0", "type": "function",
                               "function": {"name": "run_python", "arguments": '{"code": "# half'}}]}}]}
        rig = Rig([cut, tool_msg(GROUND), text_msg("layout done")] + TEXTS[:4])
        quick = []

        def quick_llm(messages, tools):
            quick.append(len(rig.calls))
            return rig.llm(messages, tools)
        run("a street", rig.llm, rig.execute, rig.events.append, rig.cancel, quick_llm=quick_llm)
        self.assertEqual(quick[:2], [1, 2])


class LightCheckTests(unittest.TestCase):
    @staticmethod
    def scene(lights):
        return lambda n, a: {"objects": [], "lights": lights} if n == "read_scene" else {"ok": True}

    def test_a_light_stage_without_lights_gets_one_more_round(self):
        rig = Rig(list(TEXTS[:3]) + [tool_msg(ROW), text_msg("lit")] + list(TEXTS[3:]), execute=self.scene([]))
        result = rig.run()
        self.assertEqual(result.status, "done")
        light = [c for c in rig.calls if c[0][0]["content"] == chat_loop.INSTRUCTIONS["light"]]
        self.assertEqual(len(light), 3)  # "c" ends the stage; the note brings the step and then "lit"
        self.assertEqual(light[1][0][-1], {"role": "user", "content": chat_loop.NO_LIGHTS})
        self.assertEqual(light[1][0][-2], {"role": "assistant", "content": "c"})

    def test_the_extra_round_is_given_once_and_taken_from_the_check_stage(self):
        rig = Rig(loop=lambda n: tool_msg(ROW), execute=self.scene([]))
        rig.run()
        stages = [next(s for s in chat_loop.STAGES if c[0][0]["content"] == chat_loop.INSTRUCTIONS[s])
                  for c in rig.calls]
        counts = {s: stages.count(s) for s in chat_loop.STAGES}
        rounds = chat_loop.STAGE_ROUNDS
        self.assertEqual(counts["light"], rounds["light"] + 1)
        self.assertEqual(counts["check"], rounds["check"] - 1)
        self.assertEqual(len(rig.calls), chat_loop.TOTAL_ROUNDS)

    def test_no_extra_round_when_the_scene_has_lights(self):
        rig = Rig(list(TEXTS), execute=self.scene([{"name": "Lamp", "type": "POINT"}]))
        rig.run()
        self.assertEqual(len(rig.calls), 5)
        self.assertTrue(all(m.get("content") != chat_loop.NO_LIGHTS for c in rig.calls for m in c[0]))

    def test_check_instructions_name_dark_frames_and_time_of_day(self):
        for table in (chat_loop.INSTRUCTIONS, chat_loop.FOLLOW_UP_INSTRUCTIONS):
            self.assertIn("no lights of your own or a black or nearly black frame", table["check"])
            self.assertIn("a light source named in the request with no visible glowing shape", table["check"])
            self.assertIn("meshes of yours with no material", table["check"])
            self.assertIn("something that is not yours covering more than 10% of the frame", table["check"])
            self.assertIn("a camera outside the room of an interior (camera_enclosed false)", table["check"])
            self.assertIn("the subject out of view or under 15% of the last frame", table["check"])
            self.assertIn("never describe what a step was meant to build", table["check"])
            self.assertIn("Night: the world background strength stays at about 0.05 or less", table["light"])
            self.assertIn("Dusk: the world background strength at about 0.1-0.3", table["light"])
            self.assertIn("about 0.05 or less at night and 0.1-0.3 at dusk, not only its colour", table["check"])
            self.assertIn("a visible glowing shape for every light source the request names", table["light"])
            self.assertIn("light that does not match the time of day in the request (dusk, night, day)",
                          table["check"])
        self.assertIn("give every mesh you built that has none one of them in a single loop", chat_loop.INSTRUCTIONS["materials"])
        for table in (chat_loop.INSTRUCTIONS, chat_loop.FOLLOW_UP_INSTRUCTIONS):
            self.assertIn("first build the camera and its move with run_python", table["camera"])
            self.assertIn("camera_enclosed is true", table["camera"])
            self.assertIn("not_yours_cover_pct stays under 10", table["camera"])


class WithoutReasoningTests(unittest.TestCase):
    def test_a_400_sends_the_call_again_without_the_parameter_for_the_rest_of_the_run(self):
        sent = []

        def call(messages, tools, reasoning):
            sent.append(reasoning)
            if reasoning is False:
                raise ApiError("unknown field reasoning (HTTP 400)", 400)
            return text_msg("ok")
        quick = chat_loop.WithoutReasoning(call)
        self.assertEqual(quick([], []), text_msg("ok"))
        self.assertEqual(quick([], []), text_msg("ok"))
        self.assertEqual(sent, [False, True, True])

    def test_anthropic_models_never_get_the_request(self):
        self.assertFalse(chat_loop.reasoning_optional("anthropic/claude-opus-5.5"))
        self.assertFalse(chat_loop.reasoning_optional(" Anthropic/claude-sonnet-5.5"))
        for model in ("openai/gpt-6-sol", "deepseek/deepseek-v4.1-flash", "vendor/x", "", None):
            self.assertTrue(chat_loop.reasoning_optional(model), model)
        sent = []
        quick = chat_loop.WithoutReasoning(lambda m, t, reasoning: sent.append(reasoning) or text_msg("ok"),
                                           accepted=chat_loop.reasoning_optional("anthropic/claude-opus-5.5"))
        quick([], [])
        quick([], [])
        self.assertEqual(sent, [True, True])  # no wasted 400 call

    def test_an_endpoint_that_takes_it_keeps_getting_it(self):
        sent = []
        quick = chat_loop.WithoutReasoning(lambda m, t, reasoning: sent.append(reasoning) or text_msg("ok"))
        quick([], [])
        quick([], [])
        self.assertEqual(sent, [False, False])

    def test_other_errors_are_not_taken_for_a_refused_parameter(self):
        for exc in (ApiError("Rate limit exceeded (HTTP 400)", 400), ApiError("gone (HTTP 504)", 504)):
            sent = []

            def call(messages, tools, reasoning, exc=exc):
                sent.append(reasoning)
                raise exc
            quick = chat_loop.WithoutReasoning(call)
            with self.assertRaises(ApiError):
                quick([], [])
            self.assertEqual((sent, quick.accepted), ([False], True))


class ReviewRetryTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(model_calls, "RETRY_AFTER", 0.01)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def llm(statuses):
        statuses, calls = list(statuses), []

        def call(messages, tools):
            calls.append(1)
            if statuses:
                status = statuses.pop(0)
                raise ApiError("failed (HTTP %d)" % status, status)
            return text_msg('{"allow": true, "reason": ""}')
        return call, calls

    def test_a_504_is_sent_once_more(self):
        from eachlabs import code_review
        call, calls = self.llm([504])
        allowed, _reason = code_review.review("x = 1", chat_loop.retried(call, threading.Event()), [], "")
        self.assertTrue(allowed)
        self.assertEqual(len(calls), 2)

    def test_a_second_failure_refuses_and_other_errors_are_not_retried(self):
        from eachlabs import code_review
        for statuses, expected in (([502, 503], 2), ([500], 1)):
            call, calls = self.llm(statuses)
            allowed, reason = code_review.review("x = 1", chat_loop.retried(call, threading.Event()), [], "")
            self.assertFalse(allowed)
            self.assertIn("Code check could not run", reason)
            self.assertEqual(len(calls), expected)

    def test_stop_during_the_wait_ends_without_a_second_call(self):
        cancel = threading.Event()
        cancel.set()
        call, calls = self.llm([504])
        with self.assertRaises(RuntimeError):
            chat_loop.retried(call, cancel)([], [])
        self.assertEqual(len(calls), 1)


class CodeAsTextTests(unittest.TestCase):
    def test_code_sent_as_text_keeps_the_stage_going(self):
        code = text_msg("# the camera\n```python\nimport bpy\ncam = bpy.data.cameras.new('c')\n```")
        rig = Rig([text_msg(t) for t in "abc"] + [code, tool_msg(ROW), text_msg("filmed"), text_msg("A room.")])
        result = rig.run()
        self.assertEqual(result.message, "A room.")
        camera = [c for c in rig.calls if c[0][0]["content"] == chat_loop.INSTRUCTIONS["camera"]]
        self.assertEqual(camera[1][0][-1], {"role": "user", "content": chat_loop.CODE_AS_TEXT})
        self.assertIn("run_python", rig.executed)

    def test_code_as_text_beside_a_view_call_is_named_too(self):
        code = {"choices": [{"message": {"role": "assistant", "content": "```python\nimport bpy\n```",
                                         "tool_calls": [{"id": "v", "type": "function",
                                                         "function": {"name": "camera_view", "arguments": "{}"}}]}}]}
        rig = Rig([text_msg(t) for t in "abc"] + [code, tool_msg(ROW), text_msg("A room.")])
        rig.run()
        camera = [c for c in rig.calls if c[0][0]["content"] == chat_loop.INSTRUCTIONS["camera"]]
        self.assertEqual(camera[1][0][-1], {"role": "user", "content": chat_loop.CODE_AS_TEXT})
        self.assertEqual(camera[1][0][-2]["role"], "tool")

    def test_a_plain_reply_still_ends_the_stage(self):
        self.assertFalse(chat_loop._looks_like_code("Built a camera at eye height with a slow push-in."))
        self.assertTrue(chat_loop._looks_like_code("import bpy\nx = 1"))


class ViewProblemTests(unittest.TestCase):
    VIEW = {"frames": [{"frame": 1, "not_yours_cover_pct": 35.9, "camera_enclosed": False,
                        "toward_target": {"first_hit": "(not yours)"}},
                       {"frame": 96, "not_yours_cover_pct": 4.0, "camera_enclosed": True,
                        "toward_target": {"first_hit": "Fireplace"}}]}

    def test_the_check_stage_is_told_what_the_view_shows_wrong(self):
        rig = Rig(list(TEXTS), execute=lambda n, a: self.VIEW if n == "camera_view" else {"lights": [{}]})
        rig.run()
        body = rig.calls[4][0][1]["content"]
        self.assertIn("Clearly wrong in what the camera sees; fix these first:", body)
        self.assertIn("At frame 1, objects that are not yours cover 35.9% of the frame", body)
        self.assertIn("At frame 1, an object that is not yours stands between the camera", body)
        self.assertIn("At frame 1, the camera is not inside walls of yours", body)
        self.assertNotIn("At frame 96", body)

    def test_a_good_view_adds_nothing(self):
        good = {"frames": [self.VIEW["frames"][1]]}
        self.assertEqual(chat_loop.view_problems(json.dumps(good)), [])
        self.assertEqual(chat_loop.view_problems("ERROR: no camera"), [])

    def test_a_subject_lost_or_hidden_during_the_move_is_named(self):
        view = {"subject": "Cabin", "frames": [
            {"frame": 1, "subject": {"in_frame": True, "coverage_pct": 30.0}},
            {"frame": 192, "subject": {"in_frame": True, "coverage_pct": 25.0}}],
            "during_move": [{"frame": 48, "subject": {"in_frame": True, "coverage_pct": 12.0}},
                            {"frame": 96, "subject": {"in_frame": False, "coverage_pct": 0.0}},
                            {"frame": 144, "subject": {"in_frame": True, "coverage_pct": 9.0,
                                                       "hidden_by": "Shore_Pine_004"}}]}
        problems = chat_loop.view_problems(json.dumps(view))
        self.assertEqual(len(problems), 2)
        self.assertIn("At frame 96, the subject Cabin is out of the frame", problems[0])
        self.assertIn("At frame 144, Shore_Pine_004 hides the subject Cabin", problems[1])
        view["during_move"][1]["subject"] = {"in_frame": True, "coverage_pct": 1.0}  # under SUBJECT_MIN_PCT
        self.assertIn("almost gone", chat_loop.view_problems(json.dumps(view))[0])

    def test_the_rules_teach_water_and_the_shadow_budget(self):
        rules = chat_loop.RULES
        self.assertIn('obj["walkable"] = False', rules)
        self.assertIn("on_not_walkable", rules)
        light = chat_loop.INSTRUCTIONS["light"]
        self.assertIn("light.use_shadow = False", light)
        self.assertIn("during_move", chat_loop.INSTRUCTIONS["camera"])
        self.assertIn("rebuild it in place", chat_loop.INSTRUCTIONS[chat_loop.EDIT])


class CameraMoveTests(unittest.TestCase):
    @staticmethod
    def scene(move):
        return json.dumps({"lights": [{}], "camera": {"yours": True, "move_m": move}})

    def test_a_move_that_stopped_is_a_problem(self):
        problems = chat_loop.camera_problems(self.scene(1.4), self.scene(0.0))
        self.assertEqual(len(problems), 1)
        self.assertIn("The camera does not move although the scene had a camera move of 1.4 m", problems[0])

    def test_no_problem_while_it_moves_or_when_it_never_moved(self):
        for start, now in ((1.4, 1.4), (1.4, 0.3), (0.0, 0.0), (0.04, 0.0)):
            self.assertEqual(chat_loop.camera_problems(self.scene(start), self.scene(now)), [], (start, now))
        self.assertEqual(chat_loop.camera_problems("ERROR: gone", self.scene(0.0)), [])
        self.assertEqual(chat_loop.camera_problems(json.dumps({"camera": None}), self.scene(0.0)), [])

    def test_the_camera_and_check_stages_are_told_once_a_step_stopped_the_move(self):
        moves = iter([1.4, 1.4, 1.4, 0.0])  # layout, materials, light, then the camera stage reads a still camera

        def execute(name, args):
            if name == "read_scene":
                return json.loads(self.scene(next(moves, 0.0)))
            return {"frames": []}
        rig = Rig(list(TEXTS), execute=execute)
        rig.run(earlier=["a car"])
        bodies = [call[0][1]["content"] for call in rig.calls]
        told = [i for i, body in enumerate(bodies) if "The camera does not move although" in body]
        self.assertEqual(told, [3, 4])

    def test_the_rules_ask_to_keep_the_move(self):
        self.assertIn("the camera does not move although the scene has a camera move", chat_loop.INSTRUCTIONS["check"])
        for stage in ("camera", "check"):
            self.assertIn("shift both of its location keys by the same offset",
                          chat_loop.FOLLOW_UP_INSTRUCTIONS[stage])


class HardeningTests(unittest.TestCase):
    def test_all_instructions_end_with_closing_phrase(self):
        for text in list(chat_loop.INSTRUCTIONS.values()) + list(chat_loop.FOLLOW_UP_INSTRUCTIONS.values()):
            self.assertTrue(text.endswith("As soon as this stage's work is done, answer with one short sentence and "
                                          "no tool calls: that ends the stage."))

    def test_malformed_tool_calls(self):
        bad = {"choices": [{"message": {"role": "assistant", "content": None,
                                        "tool_calls": [{"id": "x", "function": {}}, "junk", {"function": {}}]}}]}
        rig = Rig([bad] + TEXTS)
        rig.run()
        tools = [m for m in rig.calls[1][0] if m["role"] == "tool"]
        self.assertEqual([(t["tool_call_id"], t["content"]) for t in tools], [("x", "ERROR: malformed tool call")])

    def test_three_malformed_stop_run(self):
        bad = {"choices": [{"message": {"role": "assistant", "content": None,
                                        "tool_calls": [{"id": "x", "function": {}}]}}]}
        result = Rig(loop=lambda n: bad).run()
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.message, "Stopped: malformed kept failing: malformed tool call")

    def test_empty_exception_message_uses_type_name(self):
        def boom(name, args):
            raise KeyError()
        rig = Rig([tool_msg(GROUND)] + TEXTS, execute=boom)
        rig.run()
        tools = [m["content"] for m in rig.calls[1][0] if m["role"] == "tool"]
        self.assertEqual(tools, ["ERROR: KeyError"])

    def test_cancel_closes_active_stage(self):
        rig = Rig(loop=lambda n: tool_msg(("read_scene", {})), execute=lambda n, a: rig.cancel.set() if rig.calls else {})
        rig.run()
        self.assertEqual(rig.events[-1], {"type": "stage", "stage": "layout", "state": "cancelled"})

    def test_total_cap_closes_active_stage_as_done(self):
        rig = Rig(loop=lambda n: tool_msg(("read_scene", {})))
        rig.run(limits=Limits(total_rounds=16, stage_rounds=every(10)))
        stages = [(e["stage"], e["state"]) for e in rig.events if e["type"] == "stage"]
        self.assertEqual(stages[-3:], [("materials", "done"), ("check", "active"), ("check", "done")])

    def test_code_event_only_for_valid_run_python(self):
        rig = Rig([tool_msg(("read_scene", {}), ("run_python", {}), GROUND)] + TEXTS)
        rig.run()
        codes = [e for e in rig.events if e["type"] == "code"]
        self.assertEqual([e["code"] for e in codes], [GROUND[1]["code"]])


class CapTests(unittest.TestCase):
    def test_calls_per_reply_capped(self):
        rig = Rig([tool_msg(*[("read_scene", {})] * 12)] + TEXTS)
        rig.run()
        self.assertEqual(rig.executed.count("read_scene"), 15)  # 8 calls, a read per stage, the light and paint checks
        msgs = [m["content"] for m in rig.calls[1][0] if m["role"] == "tool"]
        over = "ERROR: only 8 tool calls are run per reply; send the rest in your next reply"
        self.assertEqual(msgs.count(over), 4)
        self.assertEqual(len(msgs), 12)

    def test_limits_positional_order(self):
        self.assertEqual(Limits(16, every(4), 3, 15.0).max_calls_per_reply, 8)


class ExecutorTests(unittest.TestCase):
    def test_executor_waits_for_main_thread(self):
        def call_soon(fn):
            threading.Thread(target=lambda: (time.sleep(0.02), fn())).start()
        ex = Executor(call_soon, execute=lambda n, a: {"name": n, "args": a})
        self.assertEqual(ex("run_python", {"code": "x"}), {"name": "run_python", "args": {"code": "x"}})

    def test_timed_out_job_never_executes(self):
        jobs, calls = [], []
        ex = Executor(jobs.append, timeout=0.02, execute=lambda n, a: calls.append(n))
        with self.assertRaises(TimeoutError):
            ex("run_python", {})
        jobs[0]()
        self.assertEqual(calls, [])

    def test_executor_reraises_execute_error(self):
        def bad(n, a):
            raise ValueError("nope")
        ex = Executor(lambda fn: fn(), execute=bad)
        with self.assertRaises(ValueError):
            ex("x", {})

    def test_never_run_times_out_as_tool_error(self):
        ex = Executor(lambda fn: None, timeout=0.05, execute=lambda n, a: {})
        with self.assertRaises(TimeoutError) as cm:
            ex("x", {})
        self.assertEqual(str(cm.exception), "Blender did not answer in 0.05 s")

        def silent(name, args):
            raise TimeoutError("Blender did not answer in 30 s")
        rig = Rig([tool_msg(GROUND)] + TEXTS, execute=silent)
        rig.run()
        tools = [m["content"] for m in rig.calls[1][0] if m["role"] == "tool"]
        self.assertEqual(tools, ["ERROR: Blender did not answer in 30 s"])


class ReplyCapTests(unittest.TestCase):
    def test_anthropic_models_get_3000_tokens_and_shorter_steps_and_others_5000(self):
        self.assertEqual(chat_loop.reply_cap("anthropic/claude-opus-5.5"), chat_loop.ReplyCap(3000, 50))
        self.assertEqual(chat_loop.reply_cap(" Anthropic/claude-sonnet-5.5"), chat_loop.ReplyCap(3000, 50))
        for model in ("openai/gpt-6-sol", "deepseek/deepseek-v4.1-flash", "vendor/unknown", "", None):
            with self.subTest(model):
                self.assertEqual(chat_loop.reply_cap(model), chat_loop.ReplyCap(5000, 80))
        self.assertEqual(chat_loop.DEFAULT_CAP, chat_loop.ReplyCap(chat_loop.MAX_TOKENS, chat_loop.STEP_LINES))

    def test_the_instructions_and_the_cut_off_notes_ask_for_the_caps_step_size(self):
        cap = chat_loop.ReplyCap(3000, 50)
        cut = {"usage": {"completion_tokens": 3000},
               "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": ""}}]}
        half = {"usage": {"completion_tokens": 3000},
                "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                             "tool_calls": [{"id": "c0", "type": "function",
                                             "function": {"name": "run_python", "arguments": '{"code": "# h'}}]}}]}
        rig = Rig([cut, half, text_msg("layout done")] + TEXTS[:4])
        rig.run(cap=cap)
        system = rig.calls[0][0][0]["content"]
        self.assertIn("one run_python call per reply, about 50 lines or fewer", system)
        self.assertNotIn("80 lines", system)
        self.assertEqual(rig.calls[1][0][-1]["content"], chat_loop.CUT_OFF_REPLY.replace("80", "50"))
        tool = [m for m in rig.calls[2][0] if m["role"] == "tool"][0]["content"]
        self.assertEqual(tool, "ERROR: " + chat_loop.CUT_OFF.replace("80", "50"))
        self.assertNotIn("run_python", rig.executed)

    def test_a_reply_under_the_cap_is_not_cut_off(self):
        reply = {"usage": {"completion_tokens": 4000},
                 "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "x"}}]}
        self.assertFalse(chat_loop._cut_off(reply, 5000))
        self.assertTrue(chat_loop._cut_off(reply, 3000))


CAR = ("run_python", {"code": "# the code version of the car\nbpy.data.objects.new('Car', None)"})


class GenerationTests(unittest.TestCase):
    def test_the_layout_stage_gets_the_code_version_rule_and_no_extra_tool(self):
        generation = chat_loop.Generation(brief="3D objects: car (large).", notes=lambda: [])
        rig = Rig([tool_msg(CAR), text_msg("laid out"), text_msg("a"), text_msg("b"), text_msg("c"),
                   text_msg("A street.")])
        result = rig.run(generation=generation)
        self.assertEqual(result.status, "done")
        tools = [names for _msgs, names in rig.calls]
        self.assertTrue(all("generate_object" not in t for t in tools))  # the add-on orders the 3D models
        layout_system, layout_user = rig.calls[0][0][0]["content"], rig.calls[0][0][1]["content"]
        self.assertIn(chat_loop.GENERATE_RULE, layout_system)
        self.assertTrue(layout_user.endswith("3D objects: car (large)."))
        later_system, later_user = rig.calls[2][0][0]["content"], rig.calls[2][0][1]["content"]
        self.assertNotIn(chat_loop.GENERATE_RULE, later_system)
        self.assertIn(chat_loop.GENERATED_RULE, later_system)
        self.assertNotIn("3D objects: car", later_user)
        self.assertIn("already has a real 3D model ordered", chat_loop.GENERATE_RULE)
        self.assertIn("the root named exactly as listed", chat_loop.GENERATE_RULE)
        # The stage loop never waits for 3D models: the run waits after the check stage (chat_run).
        self.assertEqual([e for e in rig.events if e.get("type") == "objects_wait"], [])

    def test_without_generation_nothing_changes(self):
        rig = Rig([tool_msg(CAR), text_msg("laid out")] + TEXTS)
        rig.run()
        self.assertEqual(rig.calls[0][0][0]["content"], chat_loop.INSTRUCTIONS["layout"])

    def test_a_failed_object_is_told_once_and_the_check_stage_gets_a_round_for_it(self):
        failures = [["The 3D model of red car could not be made (timeout). Build it now with run_python."]]
        generation = chat_loop.Generation(notes=lambda: failures.pop() if failures else [])
        rig = Rig(loop=lambda n: tool_msg(GROUND) if n > 4 else text_msg("ok"))
        rig.run(generation=generation, limits=Limits(stage_rounds=every(2), total_rounds=40))
        first = rig.calls[0][0][1]["content"]
        self.assertIn("fix these first:\n- The 3D model of red car could not be made", first)
        self.assertTrue(all("could not be made" not in c[0][1]["content"] for c in rig.calls[1:]))
        check_rounds = [c for c in rig.calls if c[0][0]["content"].startswith(chat_loop._HEAD + "This stage: check")]
        self.assertEqual(len(check_rounds), 2)

        failures[:] = [["The 3D model of red car could not be made (timeout)."]]
        late = chat_loop.Generation(notes=lambda: failures.pop() if failures and len(rig2.calls) >= 8 else [])
        rig2 = Rig(loop=lambda n: tool_msg(GROUND))
        rig2.run(generation=late, limits=Limits(stage_rounds=every(2), total_rounds=40))
        check_rounds = [c for c in rig2.calls if c[0][0]["content"].startswith(chat_loop._HEAD + "This stage: check")]
        self.assertEqual(len(check_rounds), 3)  # 2 + 1 for the object to build in code
        self.assertIn("could not be made", check_rounds[0][0][1]["content"])


class FixStageTests(unittest.TestCase):
    def rig(self, measured):
        """``measured``: what placement_problems answers, one dict per call, then nothing."""
        answers = list(measured)

        def execute(name, args):
            if name == "placement_problems":
                return answers.pop(0) if answers else {}
            return {"ok": True}
        return Rig(loop=lambda n: text_msg("A camp by the woods."), execute=execute)

    def stages_of(self, rig):
        return [e["stage"] for e in rig.events if e.get("type") == "stage" and e["state"] == "active"]

    def test_measured_problems_after_the_layout_get_a_fix_stage(self):
        rig = self.rig([{"nothing_below": ["Bandit camp"], "zones": [{"name": "Zone camp", "size": [20, 20]}]}])
        result = rig.run()
        self.assertEqual(self.stages_of(rig)[:2], ["layout", "fix"])
        fix = [c for c in rig.calls if "This stage: fix what the add-on measured" in c[0][0]["content"]][0]
        self.assertIn('"nothing_below": ["Bandit camp"]', fix[0][1]["content"])
        self.assertNotIn("Zone camp", fix[0][1]["content"])  # a zone with nothing wrong is not a problem
        self.assertNotIn("Still to fix", result.message)
        self.assertIn("Fixed: the bandit camp standing on nothing.", result.message)  # measured as gone after the fix

    def test_problems_left_at_the_end_are_named_in_the_reply(self):
        left = {"crossing": [{"thing": "Village wall", "crosses": "House 3", "where": [1, 2, 0]}]}
        rig = self.rig([left] * 10)
        result = rig.run()
        self.assertEqual(self.stages_of(rig).count("fix"), 2)  # after the layout and before the check
        self.assertTrue(result.message.endswith("Still to fix: the village wall passing through other things."),
                        result.message)

    def test_the_problems_line_names_each_kind_in_plain_words(self):
        line = chat_loop.problems_line({
            "nothing_below": ["Camp"], "sunk_into": [{"thing": "Cat", "into": "Chair", "depth_m": 0.2}],
            "hidden_parts": [{"part": "Clock", "inside": "Roof", "share": 0.8}],
            "outside_ground": [{"thing": "Tents", "parts": ["Tent 1"], "count": 1}],
            "zones": [{"name": "Zone village", "outside": ["House 9"], "overlaps": ["Zone camp"]}]})
        self.assertEqual(line, "Still to fix: the camp standing on nothing; the cat sinking into what is under it "
                               "and 3 more.")
        self.assertEqual(chat_loop.problems_line({}), "")

    def test_a_fix_stage_reports_only_what_it_verified(self):
        from eachlabs.chat import problems
        before = {"nothing_below": ["Camp"], "sunk_into": [{"thing": "Cat", "into": "Seat"}]}
        after = {"sunk_into": [{"thing": "Cat", "into": "Seat"}]}
        self.assertEqual(problems.verified_line(before, after), "Fixed: the camp standing on nothing.")
        self.assertEqual(problems.verified_line(before, before), "")

    def test_the_reply_names_whole_things_and_counts_them_never_their_parts(self):
        from eachlabs.chat import problems
        before = {"duplicates": [{"copy": "Guest %d / 0%d Right finger 4" % (n, n), "copy_of": "Guest %d / 0%d Right "
                                  "finger 1" % (n, n)} for n in (6, 9, 3, 10)],
                  "floats_above": [{"thing": "Window", "gap_m": 0.7, "over": "Walls"}],
                  "pierces": [{"thing": "Dragon / Left wing", "through": "Dragon / Body"}]}
        self.assertEqual(problems.verified_line(before, {}),
                         "Fixed: the window floating; parts poking through on the dragon and 1 more.")
        self.assertEqual(problems.person_text(problems._tagged({"duplicates": before["duplicates"]})),
                         "doubled parts on 4 guests")


class CompleteStageTests(unittest.TestCase):
    def rig(self, missing_after):
        """``missing_after``: what missing_items answers, one list per call."""
        answers = list(missing_after)

        def execute(name, args):
            if name == "missing_items":
                return answers.pop(0) if answers else []
            return {"ok": True}
        return Rig(loop=lambda n: text_msg("A house with a garage." if n > 1 else "built"), execute=execute)

    def stages_of(self, rig):
        return [e["stage"] for e in rig.events if e.get("type") == "stage" and e["state"] == "active"]

    def test_a_complete_stage_that_builds_some_goes_again_for_the_rest(self):
        rig = self.rig([["a", "b", "c"], ["c"], []])  # after layout, after the first and the second complete stage
        rig.run(generation=chat_loop.Generation(complete=True))
        self.assertEqual(self.stages_of(rig)[:3], ["layout", "complete", "complete"])

    def test_complete_stages_stop_when_they_build_nothing_more(self):
        rig = self.rig([["a", "b"], ["a", "b"]] + [["a", "b"]] * 4)
        rig.run(generation=chat_loop.Generation(complete=True))
        self.assertEqual(self.stages_of(rig).count("complete"), 2)  # once after the layout, once after the check

    def test_missing_things_get_a_stage_after_the_layout_and_after_the_check(self):
        # after layout: house missing; after that complete stage: the garage, no fewer, so no second one; at check
        # start: still missing; after check: still missing
        rig = self.rig([['"House" (the code version of a 3D object)'], ["garage (named after it)"],
                        ["garage (named after it)"], ["garage (named after it)"]])
        result = rig.run(generation=chat_loop.Generation(complete=True))
        self.assertEqual(self.stages_of(rig), ["layout", "complete", "materials", "light", "camera", "check",
                                               "complete"])
        complete = [c for c in rig.calls if c[0][0]["content"].startswith(chat_loop._HEAD + "This stage: build what")]
        self.assertIn("not in the scene yet; build them now: \"House\"", complete[0][0][1]["content"])
        check = [c for c in rig.calls if "This stage: check" in c[0][0]["content"]][0]
        self.assertIn("garage (named after it). Never describe them as built", check[0][1]["content"])
        self.assertEqual(result.message, "A house with a garage.")  # the complete stage's text is not the reply

    def test_nothing_missing_adds_no_stage(self):
        rig = self.rig([])
        rig.run(generation=chat_loop.Generation(complete=True))
        self.assertEqual(self.stages_of(rig), list(chat_loop.STAGES))
        rig = self.rig([["x"], ["x"], ["x"]])
        rig.run(generation=chat_loop.Generation())  # complete off: no check at all
        self.assertEqual(self.stages_of(rig), list(chat_loop.STAGES))

    def test_the_check_stages_reply_stays_when_the_cap_ends_the_run(self):
        rig = self.rig([[], [], ["garage (named after it)"]])
        result = rig.run(generation=chat_loop.Generation(complete=True),
                         limits=Limits(stage_rounds=every(1), total_rounds=5))
        self.assertEqual((result.status, result.message), ("done", "A house with a garage."))

    def test_extra_rounds_build_what_is_missing_after_the_cap(self):
        rig = self.rig([[], [], ["garage (named after it)"], []])  # after layout, at check start, after the check
        rig.run(generation=chat_loop.Generation(complete=True),
                limits=Limits(stage_rounds=every(1), total_rounds=5, extra_rounds=2))
        self.assertEqual(self.stages_of(rig)[-1], "complete")

    def test_the_complete_stage_stays_within_the_total_cap(self):
        rig = self.rig([["x"]] * 5)
        rig.loop = lambda n: tool_msg(GROUND)
        result = rig.run(generation=chat_loop.Generation(complete=True),
                         limits=Limits(stage_rounds=every(1), total_rounds=6, extra_rounds=0))
        self.assertLessEqual(len(rig.calls), 6)
        self.assertEqual(result.status, "done")
        complete_calls = [c for c in rig.calls if "build what is missing" in c[0][0]["content"]]
        self.assertLessEqual(len(complete_calls), chat_loop.COMPLETE_ROUNDS)


class VisualCheckTests(unittest.TestCase):
    FRAME = "data:image/png;base64,iVBORw0KGgo="

    def render(self, frames=(1,), overview=False):
        renders = []

        def execute(name, args):
            if name == "render_frames":
                renders.append(args)
                return {"images": [self.FRAME] * len(frames), "frames": list(frames), "seconds": [0.5] * len(frames),
                        "overview": overview}
            return {"ok": True}
        return renders, execute

    @staticmethod
    def stage_of(messages):
        return next(s for s in chat_loop.STAGES if messages[0]["content"] == chat_loop.INSTRUCTIONS[s])

    @staticmethod
    def pictures(messages):
        return [m for m in messages if isinstance(m["content"], list)
                and any(p.get("type") == "image_url" for p in m["content"])]

    def test_layout_light_and_camera_look_after_their_work_and_the_check_looks_first(self):
        renders, execute = self.render()
        rig = Rig(loop=lambda n: text_msg("ok"), execute=execute)
        visual = chat_loop.Visual(pause=0)
        result = rig.run(visual=visual)
        self.assertEqual(result.status, "done")
        self.assertEqual(renders, [{"moves": False}, {"moves": False}, {"moves": True}, {"moves": True}])
        self.assertEqual(visual.renders, 4)
        seen = [self.stage_of(m) for m, _tools in rig.calls if self.pictures(m)]
        # the layout, light and camera stages each get one more round with the picture; the check starts with it
        self.assertEqual(seen, ["layout", "light", "camera", "check"])
        layout = [m for m, _ in rig.calls if self.stage_of(m) == "layout"]
        self.assertEqual(len(layout), 2)
        self.assertEqual(self.pictures(layout[0]), [])
        self.assertEqual(layout[1][-2], {"role": "assistant", "content": "ok"})

    def test_an_edit_looks_through_the_camera_once_its_work_is_done_and_may_fix_what_it_shows(self):
        renders, execute = self.render()
        replies = [tool_msg(GROUND), text_msg("Painted."), tool_msg(GROUND), text_msg("The stripes show now.")]
        rig = Rig(replies, execute=execute)
        result = rig.run(stages=(chat_loop.EDIT,), earlier=("a street",), visual=chat_loop.Visual(pause=0),
                         limits=Limits(total_rounds=chat_loop.EDIT_ROUNDS + chat_loop.EDIT_LOOK_ROUNDS))
        self.assertEqual(result.status, "done")
        self.assertEqual(result.message, "The stripes show now.")
        self.assertEqual(renders, [{"moves": False}])
        looked = [m for m, tools in rig.calls if self.pictures(m)]
        self.assertEqual(len(looked), 2)  # the round after the picture still offers tools, and so does the next
        self.assertIn("on a side the camera does not see", json.dumps(self.pictures(looked[0])[-1]))
        self.assertNotEqual(rig.calls[2][1], [])

    def test_the_message_is_one_line_and_the_picture(self):
        message = chat_loop.look_message({"images": [self.FRAME], "frames": [1], "overview": False})
        self.assertEqual(message["content"], [{"type": "text", "text": chat_loop.LOOK},
                                              {"type": "image_url", "image_url": {"url": self.FRAME}}])
        self.assertTrue(chat_loop.LOOK.startswith("This is what the camera sees now. Fix anything clearly wrong: "))
        renders, execute = self.render()
        rig = Rig(loop=lambda n: text_msg("ok"), execute=execute)
        rig.run(visual=chat_loop.Visual(pause=0))
        sent = [self.pictures(m)[0] for m, _ in rig.calls if self.pictures(m)]
        layout = chat_loop.look_message({"images": [self.FRAME], "frames": [1]}, "layout")
        self.assertEqual(sent[0], {"role": "user", "content": layout["content"]})  # the add-on's mark is not sent
        self.assertEqual(sent[1], {"role": "user", "content": message["content"]})  # the light stage: the line only
        self.assertEqual(layout["content"][0]["text"], chat_loop.LOOK + "\n" + chat_loop.LOOK_NOTES["layout"])

    def test_a_camera_move_shows_two_frames_with_their_numbers(self):
        message = chat_loop.look_message({"images": [self.FRAME, self.FRAME], "frames": [1, 120]})
        self.assertEqual([p.get("text") for p in message["content"] if p["type"] == "text"],
                         [chat_loop.LOOK, "Frame 1:", "Frame 120:"])
        self.assertEqual(sum(p["type"] == "image_url" for p in message["content"]), 2)
        overview = chat_loop.look_message({"images": [self.FRAME], "overview": True})
        self.assertEqual(overview["content"][0]["text"], chat_loop.LOOK + "\n" + chat_loop.LOOK_OVERVIEW)

    def test_at_most_one_render_per_stage(self):
        renders, execute = self.render()
        # every round writes a step, so each stage uses its whole budget and its extra round
        rig = Rig(loop=lambda n: tool_msg(GROUND), execute=execute)
        rig.run(visual=chat_loop.Visual(pause=0), limits=Limits(total_rounds=40))
        self.assertEqual(len(renders), 4)
        self.assertTrue(all(len(self.pictures(m)) <= 1 for m, _ in rig.calls))
        rounds = {}
        for messages, _tools in rig.calls:
            rounds[self.stage_of(messages)] = rounds.get(self.stage_of(messages), 0) + 1
        self.assertEqual(rounds["layout"], chat_loop.STAGE_ROUNDS["layout"] + 1)
        self.assertEqual(rounds["materials"], chat_loop.STAGE_ROUNDS["materials"])
        self.assertEqual(rounds["check"], chat_loop.STAGE_ROUNDS["check"])

    def test_no_render_without_a_round_to_use_it_and_none_when_off(self):
        renders, execute = self.render()
        rig = Rig(loop=lambda n: tool_msg(GROUND), execute=execute)
        rig.run(visual=chat_loop.Visual(pause=0), limits=Limits(total_rounds=4))  # the cap leaves no extra round
        self.assertEqual(renders, [])
        renders, execute = self.render()
        rig = Rig(loop=lambda n: text_msg("ok"), execute=execute)
        rig.run()
        self.assertEqual(renders, [])

    def test_a_failed_render_is_skipped(self):
        rig = Rig(loop=lambda n: text_msg("ok"),
                  execute=lambda name, args: {"images": [], "reason": "nothing to see yet"})
        result = rig.run(visual=chat_loop.Visual(pause=0))
        self.assertEqual(result.status, "done")
        self.assertEqual(len(rig.calls), 5)
        events = [e["state"] for e in rig.events if e["type"] == "looking"]
        self.assertEqual(events, [True, False] * 4)

    def test_a_400_on_a_picture_sends_it_again_without_and_turns_the_check_off(self):
        renders, execute = self.render()
        sent = []

        def llm(messages, tools):
            sent.append(messages)
            if any(isinstance(m["content"], list) for m in messages):
                raise ApiError("image input is not supported (HTTP 400)", 400)
            return text_msg("ok")
        visual = chat_loop.Visual(pause=0)
        result = run("a street", llm, execute, lambda e: None, threading.Event(), visual=visual,
                     concept="data:image/jpeg;base64,AAAA")
        self.assertEqual(result.status, "done")
        self.assertFalse(visual.accepted)
        self.assertEqual(renders, [])  # the concept was refused first, so no render follows
        self.assertEqual(sum(any(isinstance(m["content"], list) for m in ms) for ms in sent), 1)
        self.assertEqual([m["role"] for m in sent[1]], ["system", "user"])  # the concept message is dropped

        renders, execute = self.render()
        sent.clear()
        visual = chat_loop.Visual(pause=0)
        run("a street", llm, execute, lambda e: None, threading.Event(), visual=visual)
        self.assertEqual(len(renders), 1)  # the layout's; the 400 turned the rest off
        self.assertEqual(sent[2][-1], {"role": "user", "content": chat_loop.NO_PICTURE})
        self.assertFalse(visual.accepted)

    def test_stop_while_the_bar_says_looking_renders_nothing(self):
        renders, execute = self.render()
        cancel = threading.Event()

        def post(event):  # Stop is pressed as the bar starts to say it
            if event.get("type") == "looking" and event["state"]:
                cancel.set()
        started = time.monotonic()
        result = run("a street", lambda m, t: text_msg("ok"), execute, post, cancel, visual=chat_loop.Visual(pause=5))
        self.assertEqual((result.status, renders), ("cancelled", []))
        self.assertLess(time.monotonic() - started, 1.0)

    def test_other_400s_still_fail_the_call(self):
        renders, execute = self.render()

        def llm(messages, tools):
            raise ApiError("bad request (HTTP 400)", 400)
        result = run("a street", llm, execute, lambda e: None, threading.Event(), visual=chat_loop.Visual(pause=0))
        self.assertEqual(result.status, "stopped")


if __name__ == "__main__":
    unittest.main()
