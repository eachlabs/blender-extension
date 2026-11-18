import threading
import unittest

from eachlabs.api_client import ApiError
from eachlabs.chat import eachsense_build
from eachlabs.chat.run_types import StopRun

CODE = "# Build a stall\nimport bpy\nbpy.ops.mesh.primitive_cube_add()"


class FakeClient:
    """each::sense as the add-on sees it: a scripted list of polls, and what the add-on sent back."""

    base_url, api_key = "https://api.test", "secret-key"

    def __init__(self, polls, capabilities=None):
        self.polls = list(polls)
        self.capabilities = capabilities if capabilities is not None else {"blender_scene": True}
        self.started, self.answers, self.cancelled, self.asked = None, [], 0, 0
        self.refuses = None  # set: the error the start ends with

    def eachsense_capabilities(self):
        self.asked += 1
        if isinstance(self.capabilities, Exception):
            raise self.capabilities
        return self.capabilities

    def start_scene(self, body):
        self.started = body
        if self.refuses is not None:
            raise self.refuses
        return {"run_id": "run-1", "status": "running", "session_id": "sess-1"}

    def get_scene(self, _run_id):
        poll = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
        if isinstance(poll, Exception):
            raise poll
        return poll

    def answer_scene_tool(self, run_id, seq, result=None, error=""):
        self.answers.append((seq, result, error))

    def cancel_scene(self, _run_id):
        self.cancelled += 1


def poll(step="", status="running", stages=(), tool=None, **extra):
    out = {"status": status, "step": step, "stages": [dict(s) for s in stages], **extra}
    if tool:
        out["tool"] = tool
    return out


def tool(seq, name, **args):
    return {"seq": seq, "name": name, "args": args, "version": 1}


def drive(client, execute=None, review=None, cancel=None, **kw):
    events = []
    ran = []

    def run_tool(name, args):
        ran.append(name)
        if execute is not None:
            return execute(name, args)
        return {"ok": True, "summary": {}} if name == "run_python" else {}

    result = eachsense_build.run(client, "A market square", run_tool, events.append, cancel or threading.Event(),
                                 review=review, sleep=lambda _s: None, clock=lambda: 1.0, **kw)
    return result, events, ran


class RunTest(unittest.TestCase):
    def test_a_build_runs_its_tools_here_and_reports_its_stages_as_the_bar_shows_them(self):
        client = FakeClient([
            poll("layout", tool=tool(1, "read_scene")),
            poll("layout: thinking"),
            poll("layout: Build a stall", tool=tool(2, "run_python", code=CODE)),
            poll("layout: thinking", stages=[{"name": "layout", "ok": True, "text": ""}]),
            poll("", status="done", stages=[{"name": "layout", "ok": True, "text": ""}], reply="A stall."),
        ])
        sessions = []
        result, events, ran = drive(client, stages=("layout",), scope="tag1", blender=(5, 3, 0), tier="final",
                                    on_session=sessions.append)

        self.assertEqual((result.status, result.message), ("done", "A stall."))
        self.assertEqual(client.started, {"instruction": "A market square", "surface": "blender", "scope": "tag1",
                                          "tier": "final", "blender_version": "5.3", "scopes": ["layout"]})
        self.assertEqual(sessions, ["sess-1"])
        self.assertEqual(ran, ["read_scene", "run_python"])
        self.assertEqual([a[0] for a in client.answers], [1, 2])
        kinds = [(e["type"], e.get("stage") or e.get("name"), e.get("state")) for e in events
                 if e["type"] in ("stage", "tool", "code")]
        self.assertEqual(kinds, [
            ("stage", "layout", "active"),
            ("tool", "read_scene", "running"), ("tool", "read_scene", "ok"),
            ("tool", "run_python", "running"), ("code", "layout", None), ("tool", "run_python", "ok"),
            ("stage", "layout", "done"),
        ])
        self.assertEqual([e["n"] for e in events if e["type"] == "round"], [1, 2])
        self.assertEqual(events[-1], {"type": "thinking", "since": None})

    def test_loop_tools_get_no_line_on_the_bar(self):
        client = FakeClient([poll("fix", tool=tool(1, "placement_problems")), poll(status="done")])
        _, events, ran = drive(client)
        self.assertEqual(ran, ["placement_problems"])
        self.assertFalse([e for e in events if e["type"] == "tool"])

    def test_every_answer_is_redacted(self):
        client = FakeClient([poll("layout", tool=tool(1, "run_python", code=CODE)), poll(status="done")])
        drive(client, execute=lambda _n, _a: {"ok": False, "error": "key secret-key leaked"}, secrets=("secret-key",))
        self.assertEqual(client.answers[0][1], {"ok": False, "error": "key [redacted] leaked"})

    def test_a_tool_that_raises_is_answered_as_an_error_the_model_reads(self):
        client = FakeClient([poll("layout", tool=tool(1, "read_scene")), poll(status="done")])

        def broken(_name, _args):
            raise RuntimeError("Blender is busy")

        result, events, _ = drive(client, execute=broken)
        self.assertEqual(client.answers, [(1, None, "Blender is busy")])
        self.assertEqual(result.status, "done")
        self.assertIn(("tool", "error"), [(e["type"], e.get("state")) for e in events])

    def test_code_check_refuses_a_step_before_it_runs(self):
        client = FakeClient([poll("layout", tool=tool(1, "run_python", code=CODE)), poll(status="done")])

        def execute(name, _args):
            return {"objects": ["Stall"], "collection": "Eachlabs scene"} if name == "chat_context" else {"ok": True}

        reviewed = []

        def review(code, objects, collection):
            reviewed.append((code, objects, collection))
            return False, "it deletes the person's objects."

        _, events, ran = drive(client, execute=execute, review=review)
        self.assertEqual(ran, ["chat_context"])
        self.assertEqual(reviewed, [(CODE, ["Stall"], "Eachlabs scene")])
        self.assertEqual(client.answers, [(1, None, eachsense_build.REFUSED % "it deletes the person's objects")])
        self.assertIn({"type": "code_check", "state": "refused", "reason": "it deletes the person's objects."}, events)

    def test_stop_cancels_the_build_once_and_keeps_what_was_built(self):
        cancel = threading.Event()
        cancel.set()
        client = FakeClient([poll("light"), poll("light"), poll(status="error", error="cancelled")])
        result, events, _ = drive(client, cancel=cancel)
        self.assertEqual(client.cancelled, 1)
        self.assertEqual((result.status, result.message), ("cancelled", eachsense_build.CANCELLED))
        self.assertEqual(events[-1], {"type": "stage", "stage": "light", "state": "cancelled"})

    def test_a_build_each_sense_stops_ends_with_its_error(self):
        client = FakeClient([poll("camera"), poll(status="error", error="Blender did not answer.")])
        result, events, _ = drive(client)
        self.assertEqual((result.status, result.message, result.failed_stage),
                         ("stopped", "Blender did not answer.", "camera"))
        self.assertEqual(events[-1]["state"], "failed")

    def test_a_step_that_changes_a_setting_stops_the_build(self):
        client = FakeClient([poll("layout", tool=tool(1, "run_python", code=CODE)), poll(status="done")])

        def execute(_name, _args):
            raise StopRun("A step changed the add-on's settings.")

        result, _, _ = drive(client, execute=execute)
        self.assertEqual((result.status, result.message), ("stopped", "A step changed the add-on's settings."))
        self.assertEqual(client.cancelled, 1)

    def test_polls_that_keep_failing_end_the_run(self):
        client = FakeClient([ApiError("Network error: refused")])
        with self.assertRaises(ApiError):
            drive(client)

    def test_a_build_each_sense_does_not_take_is_not_started_and_asks_again_whether_it_is_offered(self):
        eachsense_build._offers.clear()
        client = FakeClient([poll(status="done", reply="Never read.")])
        self.assertTrue(eachsense_build.offered(client))
        client.refuses = ApiError("Every build worker here is busy; try again in a moment.", status=429)
        with self.assertRaises(eachsense_build.NotStarted) as raised:
            drive(client)
        self.assertIn("busy", str(raised.exception))
        self.assertEqual((client.answers, client.cancelled), ([], 0))  # nothing ran there
        client.refuses = None
        self.assertTrue(eachsense_build.offered(client))
        self.assertEqual(client.asked, 2)  # the kept answer was dropped

    def test_a_retry_from_the_detail_stage_asks_for_the_stages_after_it(self):
        client = FakeClient([poll(status="done", reply="Done.")])
        drive(client, stages=("detail", "materials", "light", "camera", "check"))
        self.assertEqual(client.started["scopes"], ["materials", "light", "camera", "check"])

    def test_a_free_asset_runs_here_and_shows_on_the_bar(self):
        client = FakeClient([
            poll("materials", tool=tool(1, "free_texture", description="red brick", material="Wall")),
            poll(status="done", reply="Painted."),
        ])
        _result, events, ran = drive(client, execute=lambda name, args: {"ok": True, "name": "red_brick_03"})
        self.assertEqual(ran, ["free_texture"])
        self.assertEqual(client.answers, [(1, {"ok": True, "name": "red_brick_03"}, "")])
        self.assertEqual([e["summary"] for e in events if e["type"] == "tool"], ["free texture: red brick"] * 2)

    def test_all_five_stages_send_no_scopes(self):
        client = FakeClient([poll(status="done")])
        drive(client, stages=("layout", "detail", "materials", "light", "camera", "check"))
        self.assertNotIn("scopes", client.started)


class ExtrasTest(unittest.TestCase):
    """What the add-on brings to an each::sense build, and the tools its extras ask for."""

    def test_the_inputs_answer_carries_the_plan_and_pictures_and_runs_nothing_in_blender(self):
        inputs = {"visual": True, "concept": "data:image/jpeg;base64,QUJD", "generation": {"brief": "3D: Boat"},
                  "limits": {"total_rounds": 22}}
        client = FakeClient([poll("layout", tool=tool(1, "build_inputs")), poll("layout: thinking"),
                             poll(status="done")])
        _, events, ran = drive(client, inputs=inputs, tier="final")
        self.assertEqual(ran, [])
        self.assertEqual(client.answers, [(1, inputs, "")])
        self.assertFalse([e for e in events if e["type"] == "tool"])
        self.assertEqual([e["total"] for e in events if e["type"] == "round"], [22])

    def test_a_concept_picture_too_big_for_one_answer_is_left_out(self):
        big = {"concept": "data:image/jpeg;base64," + "A" * eachsense_build.ANSWER_BYTES, "visual": True}
        self.assertEqual(eachsense_build.fitted(big), {"concept": "", "visual": True})
        small = {"concept": "data:image/jpeg;base64,QUJD"}
        self.assertEqual(eachsense_build.fitted(small), small)

    def test_worker_tools_run_here_not_on_blenders_main_thread(self):
        client = FakeClient([poll("detail", tool=tool(1, "reference_picture", object="Lighthouse")),
                             poll(status="done")])
        asked = []
        _, _, ran = drive(client, local={"reference_picture": lambda args: asked.append(args) or {"image": "x"}})
        self.assertEqual((ran, asked), ([], [{"object": "Lighthouse"}]))
        self.assertEqual(client.answers, [(1, {"image": "x"}, "")])

    def test_a_detail_step_is_code_checked_and_shown_as_a_step_of_code(self):
        client = FakeClient([poll("detail", tool=tool(1, "detail_step", object="Lighthouse", code=CODE)),
                             poll(status="done")])
        reviewed = []

        def review(code, objects, collection):
            reviewed.append(code)
            return False, "it deletes the person's camera"

        _, events, ran = drive(client, review=review,
                               execute=lambda name, _a: {"objects": [], "collection": "c"} if name == "chat_context"
                               else {"ok": True})
        self.assertEqual(reviewed, [CODE])
        self.assertNotIn("detail_step", ran)
        self.assertEqual(client.answers[0][2], eachsense_build.REFUSED % "it deletes the person's camera")
        code = [e for e in events if e["type"] == "code"]
        self.assertEqual(code[0]["stage"], "detail")
        self.assertEqual({e["name"] for e in events if e["type"] == "tool"}, {"run_python"})

    def test_renders_show_looking_and_no_tool_line(self):
        client = FakeClient([poll("check", tool=tool(1, "render_frames", moves=True)), poll(status="done")])
        _, events, ran = drive(client, execute=lambda _n, _a: {"images": ["data:image/png;base64,AA"]})
        self.assertEqual(ran, ["render_frames"])
        self.assertEqual([e["state"] for e in events if e["type"] == "looking"], [True, False])
        self.assertFalse([e for e in events if e["type"] == "tool"])

    def test_a_renders_pictures_are_made_smaller_before_they_are_sent(self):
        client = FakeClient([poll("review", tool=tool(1, "review_views")), poll(status="done")])
        drive(client, execute=lambda _n, _a: {"images": ["big-1", "big-2"], "names": ["Cat"]},
              shrink=lambda url: url.replace("big", "small"))
        self.assertEqual(client.answers, [(1, {"images": ["small-1", "small-2"], "names": ["Cat"]}, "")])

    def test_an_answer_the_api_refuses_goes_back_as_the_tools_error(self):
        class Refusing(FakeClient):
            def answer_scene_tool(self, run_id, seq, result=None, error=""):
                if result is not None:
                    raise ApiError("the tool answer is over 2 MiB", status=413)
                super().answer_scene_tool(run_id, seq, result, error)

        client = Refusing([poll("review", tool=tool(1, "review_views")), poll(status="done", reply="A cat.")])
        result, _, _ = drive(client, execute=lambda _n, _a: {"images": ["x"]})
        self.assertEqual(result.status, "done")
        self.assertEqual(client.answers[0][0], 1)
        self.assertIn("too big to send", client.answers[0][2])

    def test_the_scene_reviews_steps_change_no_stage_and_count_no_round(self):
        client = FakeClient([poll("check: thinking"), poll("review: looking at the scene"),
                             poll("review: thinking"), poll(status="done")])
        _, events, _ = drive(client)
        self.assertEqual([e["stage"] for e in events if e["type"] == "stage"], ["check"])
        self.assertEqual([e["n"] for e in events if e["type"] == "round"], [1])


class OfferTest(unittest.TestCase):
    def setUp(self):
        eachsense_build._offers.clear()

    def test_it_is_offered_only_when_the_api_says_so_and_the_answer_is_kept(self):
        client = FakeClient([], capabilities={"enabled": True, "blender_chat": True})
        self.assertFalse(eachsense_build.offered(client, now=lambda: 0.0))
        self.assertFalse(eachsense_build.offered(client, now=lambda: 10.0))
        self.assertEqual(client.asked, 1)
        client.capabilities = {"blender_scene": True}
        self.assertTrue(eachsense_build.offered(client, now=lambda: 1000.0))

    def test_an_api_that_cannot_answer_does_not_offer_it(self):
        self.assertFalse(eachsense_build.offered(FakeClient([], capabilities=ApiError("404")), now=lambda: 0.0))

    def test_the_quality_mode_picks_the_tier(self):
        best = "openai/gpt-6-astra"
        self.assertEqual(eachsense_build.tier("PROTOTYPE", "openai/gpt-6.1-terra", best), "prototype")
        self.assertEqual(eachsense_build.tier("ADVANCED", "openai/gpt-6-sol", best), "final")
        self.assertEqual(eachsense_build.tier("ADVANCED", best, best), "best")
        self.assertEqual(eachsense_build.tier("PROTOTYPE", best, best), "prototype")


if __name__ == "__main__":
    unittest.main()
