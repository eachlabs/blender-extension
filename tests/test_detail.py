import json
import threading
import time
import unittest
from unittest import mock

from eachlabs import chat_loop, code_check, detail
from eachlabs.api_client import ApiError


def tool_msg(code, id_="c0"):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": id_, "type": "function", "function": {"name": "run_python", "arguments": json.dumps({"code": code})}}]}}]}


def text_msg(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


SCENE = json.dumps({"objects": [
    {"name": "Car", "type": "EMPTY"}, {"name": "Car_Body", "type": "MESH", "parent": "Car"},
    {"name": "Church", "type": "EMPTY"}, {"name": "Ground", "type": "MESH"},
    {"name": "Tree 1 … Tree 5", "type": "EMPTY", "count": 5}]})


class Script:
    """An ``llm`` per object: each object's conversation gets its own list of replies."""

    def __init__(self, replies):
        self.replies = replies  # {object name: [reply, ...]}
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, messages, tools):
        name = messages[1]["content"].split('The object: "', 1)[1].split('"', 1)[0]
        with self.lock:
            self.calls.append((name, messages, tools))
            queue = self.replies[name]
            return queue.pop(0) if queue else text_msg("Done.")


class Rig:
    def __init__(self, replies, look=None, step=None):
        self.llm = Script(replies)
        self.events = []
        self.executed = []
        self.look = look
        self.step = step
        self.measures = []  # what each detail_measure finds, in order; then nothing
        self.lock = threading.Lock()

    def execute(self, name, args):
        with self.lock:
            self.executed.append((name, dict(args)))
        if name == "detail_read":
            return {"objects": [{"name": args["object"], "type": "EMPTY"}]}
        if name == "detail_step":
            if self.step is not None:
                return self.step(args)
            return {"ok": True, "summary": {"new_objects": [args["object"] + "_Part"]}}
        if name == "detail_look":
            return self.look or {"images": []}
        if name == "chat_context":
            return {"collection": "Eachlabs", "objects": []}
        if name == "detail_measure":
            return self.measures.pop(0) if self.measures else {}
        raise AssertionError(name)

    def post(self, event):
        with self.lock:
            self.events.append(event)


class PickTest(unittest.TestCase):
    def test_only_scene_roots_are_picked_each_once(self):
        answer = json.dumps({"objects": [
            {"name": "Car", "level": "high", "parts": ["wheels", "", "mirrors"]},
            {"name": "Car_Body", "level": "high"},  # a part, not a root
            {"name": "Spaceship"},  # not in the scene
            {"name": "Car", "level": "medium"},  # twice
            {"name": "Church", "level": "huge"}]})
        targets = detail.parse_pick("Here it is: " + answer, ["Car", "Church", "Ground"])
        self.assertEqual([(t.name, t.level, t.parts) for t in targets],
                         [("Car", "high", ["wheels", "mirrors"]), ("Church", "medium", [])])
        self.assertEqual(len(detail.parse_pick(answer, ["Car", "Church"], limit=1)), 1)
        self.assertEqual(detail.parse_pick("no json", ["Car"]), [])

    def test_the_pick_message_carries_the_plan_and_every_choice(self):
        choices = [{"name": "Building %d" % i, "parts": 3, "size_m": 12.0} for i in range(100)]
        messages = detail.pick_messages("a street", SCENE, [("car", "high"), ("road", "low")], 4, choices)
        self.assertIn("At most 4 high or medium objects.", messages[0]["content"])
        self.assertIn("Never answer light.", messages[0]["content"])
        self.assertIn("The plan marked these as main objects: car (high), road (low).", messages[1]["content"])
        self.assertIn('"name": "Building 79"', messages[1]["content"])
        self.assertNotIn('"name": "Building 80"', messages[1]["content"])  # at most CHOICES_MAX
        with_light = detail.pick_messages("a street", SCENE, (), 4, choices, light_limit=3)
        self.assertIn("At most 4 high or medium objects and 3 light ones.", with_light[0]["content"])
        self.assertIn(detail.LIGHT_TEXT, with_light[0]["content"])

    def test_light_objects_have_their_own_limit_and_come_last(self):
        answer = json.dumps({"objects": [
            {"name": "Tree 1", "level": "light"}, {"name": "Bench", "level": "light"},
            {"name": "Rock", "level": "light"}, {"name": "Church", "level": "high"}, {"name": "Car", "level": "medium"}]})
        names = ["Tree 1", "Bench", "Rock", "Church", "Car"]
        targets = detail.parse_pick(answer, names, limit=1, light_limit=2)
        self.assertEqual([(t.name, t.level) for t in targets], [("Church", "high"), ("Tree 1", "light"),
                                                                 ("Bench", "light")])
        self.assertEqual([t.name for t in detail.parse_pick(answer, names, limit=6)], ["Church", "Car"])

    def test_a_medium_object_gets_one_round_less(self):
        self.assertEqual(detail.Target("A", "high").rounds(3), 3)
        self.assertEqual(detail.Target("A", "medium").rounds(3), 2)
        self.assertEqual(detail.Target("A", "medium").rounds(1), 1)
        self.assertEqual(detail.Target("A", detail.LIGHT).rounds(3, 1), 1)
        self.assertEqual(detail.Target("A", detail.LIGHT).rounds(3, 2), 2)

    def test_a_light_object_gets_no_close_up(self):
        settings = detail.Settings(look=True)
        self.assertTrue(detail.Target("A", "high").looks(settings))
        self.assertFalse(detail.Target("A", detail.LIGHT).looks(settings))
        self.assertFalse(detail.Target("A", "high").looks(detail.Settings(look=False)))


class InstructionsTest(unittest.TestCase):
    def test_parts_stay_with_the_object_and_shapes_are_explained(self):
        text = detail.system_text()
        self.assertIn("never one solid block", text)
        self.assertIn("attach(part, root)", text)
        self.assertIn("SUBSURF", text)
        self.assertIn("bmesh.ops.spin", text)
        self.assertIn("about 80 lines", text)
        self.assertIn("about 50 lines", detail.system_text(lines=50))

    def test_the_shape_examples_pass_the_code_filter(self):
        code = "\n".join([
            "import bpy, bmesh, math",
            "bm = bmesh.new()",
            "r, d, n = 0.3, 0.2, 4",
            "geom = bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=r, radius2=r, depth=d)",
            "f = bm.faces[0]",
            "bmesh.ops.inset_region(bm, faces=[f], thickness=0.06, depth=-0.04)",
            "ret = bmesh.ops.extrude_face_region(bm, geom=[f])",
            "bmesh.ops.translate(bm, vec=(0, 0, 0.1), verts=[v for v in ret['geom'] if isinstance(v, bmesh.types.BMVert)])",
            "verts = [bm.verts.new((1, 0, z)) for z in (0, 1)]",
            "edges = [bm.edges.new(verts)]",
            "bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=(0, 0, 1), angle=math.tau, steps=32)",
            "mesh = bpy.data.meshes.new('M')",
            "bm.to_mesh(mesh)",
            "obj = bpy.data.objects.new('M', mesh)",
            "sub = obj.modifiers.new('Smooth', 'SUBSURF')",
            "m = obj.modifiers.new('Mirror', 'MIRROR')",
            "m.use_clip = True",
            "a = obj.modifiers.new('Row', 'ARRAY')",
            "a.relative_offset_displace = (1.5, 0, 0)",
            "s = obj.modifiers.new('Shell', 'SOLIDIFY')",
            "cu = bpy.data.curves.new('Rail', 'CURVE')",
            "cu.dimensions = '3D'",
            "sp = cu.splines.new('POLY')",
            "sp.points.add(n - 1)",
            "sp.points[0].co = (0, 0, 0, 1)",
        ])
        code_check.check(code)  # raises Refused otherwise


class ImproveTest(unittest.TestCase):
    def run_targets(self, targets, replies, settings=None, look=None, step=None, visual=None, review=None):
        rig = Rig(replies, look, step)
        cancel = threading.Event()
        outcome = detail.run(targets, "a street", rig.llm, None, rig.execute, rig.post, cancel,
                             settings or detail.Settings(rounds=2, look=False), base_rounds=5, base_total=20,
                             review=review, visual=visual)
        return rig, outcome

    def test_every_step_names_its_object_and_the_summaries_come_back(self):
        rig, outcome = self.run_targets(
            [detail.Target("Car", "high", ["wheels"]), detail.Target("Church", "medium")],
            {"Car": [tool_msg("# wheels\nx = 1"), text_msg("Done")], "Church": [tool_msg("# windows\nx = 2")]})
        steps = [(a["object"], a["code"].splitlines()[0]) for n, a in rig.executed if n == "detail_step"]
        self.assertEqual(sorted(steps), [("Car", "# wheels"), ("Church", "# windows")])
        self.assertEqual(sorted(s["summary"]["what"] for s in outcome.steps), ["wheels", "windows"])
        self.assertTrue(all(s["stage"] == chat_loop.DETAIL for s in outcome.steps))
        self.assertEqual(outcome.rounds, 3)  # the car: a step and its answer; the church's one round
        self.assertEqual(outcome.lines, [])
        rounds = [e for e in rig.events if e["type"] == "round"]
        self.assertEqual([e["n"] for e in rounds], [6, 7, 8])
        self.assertEqual({e["total"] for e in rounds}, {20 + 2 + 1})
        first = rig.llm.calls[0][1]
        self.assertIn("Parts to add:", first[1]["content"])
        self.assertEqual([t["function"]["name"] for t in rig.llm.calls[0][2]], ["run_python"])

    def test_the_main_objects_go_to_their_own_model(self):
        from eachlabs.chat import stage_models

        main = Rig({"Car": [tool_msg("# wheels\nx = 1")]}, None, None)
        rig = Rig({"Church": [tool_msg("# windows\nx = 2")]}, None, None)
        route = stage_models.Route(main.llm, None, chat_loop.DEFAULT_CAP, "vendor/main")
        outcome = detail.run([detail.Target("Car", "high"), detail.Target("Church", "medium")], "a street",
                             rig.llm, None, rig.execute, rig.post, threading.Event(),
                             detail.Settings(rounds=1, look=False), main=route)
        self.assertEqual(len(main.llm.calls), 1)
        self.assertEqual(len(rig.llm.calls), 1)
        self.assertEqual({t["object"]: t["model"] for t in outcome.timings}, {"Car": "vendor/main", "Church": ""})

    def test_the_round_limit_leaves_out_what_it_cannot_hold(self):
        rig = Rig({"Car": [tool_msg("# body\nx = 1"), tool_msg("# wheels\nx = 2"), text_msg("Done")],
                   "Church": [tool_msg("# windows\nx = 3")]}, None, None)
        outcome = detail.run([detail.Target("Car"), detail.Target("Church")], "a street", rig.llm, None,
                             rig.execute, rig.post, threading.Event(), detail.Settings(rounds=2, look=False,
                                                                                         parallel=1), limit=2)
        self.assertEqual(outcome.rounds, 2)
        self.assertIn(detail.LIMIT_SKIPPED % "Church", outcome.lines)
        self.assertNotIn("Church", [a["object"] for n, a in rig.executed if n == "detail_step"])

    def test_the_round_limit_stops_an_object_mid_way(self):
        rig = Rig({"Car": [tool_msg("# body\nx = 1"), tool_msg("# wheels\nx = 2"), tool_msg("# glass\nx = 3")]},
                  None, None)
        outcome = detail.run([detail.Target("Car")], "a street", rig.llm, None, rig.execute, rig.post,
                             threading.Event(), detail.Settings(rounds=3, look=False), limit=3)
        self.assertLessEqual(outcome.rounds, 3)

    def test_the_close_up_gives_one_more_round(self):
        look = {"images": ["data:image/png;base64,AA", "data:image/png;base64,BB"]}
        visual = chat_loop.Visual()
        rig, outcome = self.run_targets([detail.Target("Car")], {"Car": [
            tool_msg("# body\nx = 1"), text_msg("Done"), tool_msg("# fix the wheels\nx = 2"), text_msg("Now done")]},
            settings=detail.Settings(rounds=3, look=True), look=look, visual=visual)
        self.assertIn(("detail_look", {"object": "Car"}), rig.executed)
        looked = [m for m in rig.llm.calls[2][1] if isinstance(m["content"], list)]
        self.assertEqual(len(looked), 1)
        self.assertNotIn("look", looked[0])  # the add-on's own mark is not sent
        self.assertEqual(looked[0]["content"][0]["text"], detail.LOOK)
        self.assertEqual(len(looked[0]["content"]), 3)
        self.assertEqual(visual.renders, 2)
        self.assertEqual(outcome.rounds, 3)  # the fix after the close-up is the last round
        self.assertIn("# fix the wheels", [a.get("code", "").splitlines()[0] for n, a in rig.executed if n == "detail_step"])

    def test_what_the_last_round_left_wrong_gets_one_fix_round(self):
        rig = Rig({"Shed": [tool_msg("# walls\nx = 1"), tool_msg("# move the handle\nx = 2")]})
        rig.measures = [{"gaps": [{"parts": ["Shed_Handle"], "gap_m": 0.095}],
                         "hidden": [{"part": "Shed_Clock", "inside": "Shed_Roof", "share": 0.8}]}]
        outcome = detail.run([detail.Target("Shed")], "a shed", rig.llm, None, rig.execute, rig.post,
                             threading.Event(), detail.Settings(rounds=1, look=False))
        asked = rig.llm.calls[-1][1][-1]["content"]
        self.assertTrue(asked.startswith(detail.MEASURED))
        self.assertIn('"Shed_Handle"', asked)
        self.assertIn('"Shed_Clock"', asked)
        self.assertEqual([a["code"].splitlines()[0] for n, a in rig.executed if n == "detail_step"],
                         ["# walls", "# move the handle"])
        self.assertEqual(sum(1 for n, _a in rig.executed if n == "detail_measure"), 1)  # measured once only
        self.assertEqual(outcome.rounds, 2)

    def test_nothing_measured_wrong_adds_no_round(self):
        rig, outcome = self.run_targets([detail.Target("Shed")], {"Shed": [tool_msg("# walls\nx = 1")]},
                                        settings=detail.Settings(rounds=1, look=False))
        self.assertEqual(outcome.rounds, 1)

    def test_the_close_up_names_the_measured_gaps(self):
        look = {"images": ["data:image/png;base64,AA"], "gaps": [{"parts": ["Chair_Wing_L"], "gap_m": 0.04}]}
        rig, _outcome = self.run_targets([detail.Target("Chair")], {"Chair": [
            text_msg("Done"), tool_msg("# close the wing gap\nx = 1"), text_msg("Now done")]},
            settings=detail.Settings(rounds=1, look=True), look=look, visual=chat_loop.Visual())
        looked = [m for m in rig.llm.calls[1][1] if isinstance(m["content"], list)]
        text = looked[0]["content"][0]["text"]
        self.assertTrue(text.startswith(detail.LOOK))
        self.assertIn('"Chair_Wing_L"', text)
        self.assertIn('"gap_m": 0.04', text)

    def test_a_light_object_runs_its_short_pass_without_a_close_up(self):
        look = {"images": ["data:image/png;base64,AA"]}
        rig, outcome = self.run_targets([detail.Target("Tree 1", detail.LIGHT)], {"Tree 1": [
            tool_msg("# branches\nx = 1"), tool_msg("# more\nx = 2")]},
            settings=detail.Settings(rounds=3, look=True, light_rounds=1), look=look, visual=chat_loop.Visual())
        self.assertNotIn("detail_look", [n for n, _a in rig.executed])
        self.assertEqual(outcome.rounds, 1)

    def test_a_reference_picture_is_sent_with_the_first_message(self):
        target = detail.Target("Car", reference="data:image/jpeg;base64,AA")
        rig, _outcome = self.run_targets([target], {"Car": [text_msg("Done")]})
        messages = rig.llm.calls[0][1]
        self.assertEqual(messages[2]["content"][0]["text"], detail.REFERENCE)
        self.assertEqual(messages[2]["content"][1]["image_url"]["url"], "data:image/jpeg;base64,AA")

    def test_the_judge_names_what_differs_from_the_reference_after_a_round(self):
        judged = []

        def judge(messages, tools):
            judged.append(messages)
            return text_msg("- the legs are too short: make them twice as long\n- no tail" if len(judged) == 1
                            else "MATCHES")
        rig = Rig({"Dog": [tool_msg("# body\nx = 1"), tool_msg("# legs\nx = 2"), text_msg("Done")]},
                  {"images": ["data:image/png;base64,BB"]}, None)
        target = detail.Target("Dog", "high", reference="data:image/jpeg;base64,AA")
        detail.run([target], "a dog", rig.llm, judge, rig.execute, rig.post, threading.Event(),
                   detail.Settings(rounds=3, look=False), visual=chat_loop.Visual())
        self.assertEqual(len(judged), 2)  # after each round with rounds left; the last round has none
        sent = judged[0][0]["content"]
        self.assertEqual([p["image_url"]["url"] for p in sent[1:]], ["data:image/jpeg;base64,AA",
                                                                     "data:image/png;base64,BB"])
        second = rig.llm.calls[1][1]
        self.assertIn("the legs are too short", second[-1]["content"])
        self.assertIn("Fix the biggest", second[-1]["content"])
        third = rig.llm.calls[2][1]
        self.assertEqual(third[-1]["role"], "tool")  # MATCHES adds no note

    def test_no_reference_means_no_comparison(self):
        rig = Rig({"Car": [tool_msg("# body\nx = 1"), text_msg("Done")]}, {"images": ["data:image/png;base64,BB"]},
                  None)
        detail.run([detail.Target("Car", "high")], "a car", rig.llm, lambda m, t: self.fail("judged"),
                   rig.execute, rig.post, threading.Event(), detail.Settings(rounds=3, look=False),
                   visual=chat_loop.Visual())
        self.assertNotIn("detail_look", [n for n, _a in rig.executed])

    def test_differences_are_short_lines(self):
        from eachlabs import detail_compare

        self.assertEqual(detail_compare.differences("MATCHES."), [])
        self.assertEqual(detail_compare.differences(""), [])
        self.assertEqual(detail_compare.differences("1. a\n- b\n\n* c\nd\ne\nf\ng")[:2], ["1. a", "b"])
        self.assertEqual(len(detail_compare.differences("\n".join("x%d" % i for i in range(9)))),
                         detail_compare.COMPARE_MAX)

    def test_failing_steps_end_only_that_object(self):
        def step(args):
            if args["object"] == "Car":
                return {"ok": False, "error": "Traceback\nNameError: name 'x' is not defined"}
            return {"ok": True, "summary": {}}
        rig, outcome = self.run_targets(
            [detail.Target("Car"), detail.Target("Church")],
            {"Car": [tool_msg("# a\n1"), tool_msg("# b\n2"), tool_msg("# c\n3")], "Church": [tool_msg("# w\n1")]},
            settings=detail.Settings(rounds=5, look=False, max_failures=2), step=step)
        self.assertEqual(outcome.lines, ["Car: partly done, its steps kept failing."])
        car_steps = [a for n, a in rig.executed if n == "detail_step" and a["object"] == "Car"]
        self.assertEqual(len(car_steps), 2)
        errors = [e for e in rig.events if e.get("type") == "tool" and e["state"] == "error"]
        self.assertEqual(errors[0]["detail"], "NameError: name 'x' is not defined")

    def test_a_failed_model_call_leaves_the_object_partly_done(self):
        rig = Rig({})

        def llm(messages, tools):
            raise ApiError("The model is overloaded.", status=500)
        outcome = detail.run([detail.Target("Car")], "a street", llm, None, rig.execute, rig.post, threading.Event(),
                             detail.Settings(rounds=2, look=False))
        self.assertEqual(outcome.lines, ["Car: partly done, The model is overloaded."])
        self.assertEqual(outcome.rounds, 1)

    def test_code_check_refusals_never_run_the_step(self):
        rig, outcome = self.run_targets([detail.Target("Car")], {"Car": [tool_msg("# a\nx = 1")]},
                                        review=lambda code, objects, collection: (False, "it deletes the ground."))
        self.assertNotIn("detail_step", [n for n, _a in rig.executed])
        refused = [m for _n, messages, _t in rig.llm.calls[1:] for m in messages if m.get("role") == "tool"]
        self.assertIn("Code check: it deletes the ground", refused[0]["content"])

    def test_secrets_never_reach_the_model(self):
        rig = Rig({"Car": [tool_msg("# a\nx = 1"), text_msg("Done")]},
                  step=lambda args: {"ok": True, "output": "key sk-123"})
        detail.run([detail.Target("Car")], "a street", rig.llm, None, rig.execute, rig.post, threading.Event(),
                   detail.Settings(rounds=2, look=False), secrets=("sk-123",))
        sent = json.dumps([m for _n, messages, _t in rig.llm.calls for m in messages])
        self.assertNotIn("sk-123", sent)
        self.assertIn(code_check.REDACTED, sent)

    def test_objects_run_side_by_side(self):
        started, both = [], threading.Event()

        def llm(messages, tools):
            name = messages[1]["content"].split('The object: "', 1)[1].split('"', 1)[0]
            started.append(name)
            if len(started) >= 2:
                both.set()
            both.wait(2)  # each call waits until the other one started
            return text_msg("Done")
        rig = Rig({})
        began = time.monotonic()
        detail.run([detail.Target("Car"), detail.Target("Church")], "a street", llm, None, rig.execute, rig.post,
                   threading.Event(), detail.Settings(rounds=1, parallel=2, look=False))
        self.assertTrue(both.is_set())
        self.assertLess(time.monotonic() - began, 1.5)

    def test_stop_ends_every_object(self):
        cancel = threading.Event()
        rig = Rig({})

        def llm(messages, tools):
            cancel.set()
            return tool_msg("# a\nx = 1")
        outcome = detail.run([detail.Target("Car"), detail.Target("Church")], "a street", llm, None, rig.execute,
                             rig.post, cancel, detail.Settings(rounds=3, parallel=1, look=False))
        self.assertTrue(outcome.cancelled)
        self.assertNotIn("detail_step", [n for n, _a in rig.executed])


class StageTest(unittest.TestCase):
    def test_the_detail_stage_runs_after_the_layout_with_rounds_on_top_of_the_cap(self):
        calls, events = [], []
        seen = {}

        def llm(messages, tools):
            calls.append(messages)
            return text_msg("Done.")

        def execute(name, args):
            return {"objects": []}

        def improve(scene, rounds, total):
            seen.update(rounds=rounds, total=total)
            return detail.Outcome(rounds=4, steps=[{"stage": chat_loop.DETAIL, "summary": {"what": "wheels"}}],
                                  lines=["Car: partly done, its steps kept failing."])
        limits = chat_loop.Limits(total_rounds=6, stage_rounds={s: 1 for s in chat_loop.STAGES})
        result = chat_loop.run("a street", llm, execute, events.append, threading.Event(), limits,
                               chat_loop.ORDER, detail=improve)
        stages = [(e["stage"], e["state"]) for e in events if e["type"] == "stage"]
        self.assertEqual(stages[:4], [("layout", "active"), ("layout", "done"), ("detail", "active"),
                                      ("detail", "partial")])
        self.assertEqual(seen, {"rounds": 1, "total": 6})
        self.assertEqual(result.rounds, 1 + 4 + 4)  # every stage still got its round
        self.assertIn("Car: partly done, its steps kept failing.", result.message)
        self.assertIn(chat_loop.DETAIL_LATER, calls[0][0]["content"])
        self.assertNotIn(chat_loop.DETAIL_LATER, calls[1][0]["content"])
        materials = calls[1][1]["content"]  # the materials stage hears what the detail stage did
        self.assertIn('"stage": "detail", "summary": {"what": "wheels"}', materials)

    def test_a_limited_detail_stage_spends_the_rounds_the_later_stages_could_add(self):
        def improve(scene, rounds, total):
            return detail.Outcome(rounds=5)
        limits = chat_loop.Limits(total_rounds=6, stage_rounds={s: 1 for s in chat_loop.STAGES}, extra_rounds=8,
                                  detail_rounds=8)
        with mock.patch.object(chat_loop, "replace", lambda value: value):  # the stage loop works on a copy
            chat_loop.run("a street", lambda m, t: text_msg("Done."), lambda n, a: {"objects": []}, lambda e: None,
                          threading.Event(), limits, chat_loop.ORDER, detail=improve)
        self.assertEqual(limits.extra_rounds, 3)

    def test_without_a_detail_function_the_stage_is_skipped(self):
        events = []
        chat_loop.run("a street", lambda m, t: text_msg("Done."), lambda n, a: {}, events.append, threading.Event(),
                      chat_loop.Limits(stage_rounds={s: 1 for s in chat_loop.STAGES}), chat_loop.ORDER)
        self.assertNotIn("detail", [e.get("stage") for e in events])

    def test_full_runs(self):
        self.assertTrue(chat_loop.is_full(chat_loop.ORDER))
        self.assertTrue(chat_loop.is_full(chat_loop.STAGES))
        self.assertFalse(chat_loop.is_full(chat_loop.ORDER[1:]))


if __name__ == "__main__":
    unittest.main()
