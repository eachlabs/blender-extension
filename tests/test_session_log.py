import unittest

from eachlabs.api_client import ApiError, EachlabsClient
from eachlabs.chat import session_log

from .fake_server import FakeServer


class LinesTest(unittest.TestCase):
    def test_a_run_adds_its_prompt_and_the_answer(self):
        lines = session_log.lines_for("t1", "A lighthouse.", "Built it.", "done", {"cost": 0.12, "stages": {}})
        self.assertEqual([(l["line_id"], l["role"], l["kind"], l["content"]) for l in lines], [
            ("t1-user", "user", "user", "A lighthouse."), ("t1-reply", "assistant", "assistant", "Built it.")])
        self.assertNotIn("detail", lines[0])
        self.assertEqual(lines[1]["detail"], {"cost": 0.12, "status": "done"})

    def test_a_retry_adds_only_its_answer(self):
        lines = session_log.lines_for("t2", "A lighthouse.", "Built it.", "done", retry=True)
        self.assertEqual([l["line_id"] for l in lines], ["t2-reply"])
        self.assertTrue(lines[0]["detail"]["retry"])

    def test_a_stopped_run_is_an_error_line_with_its_reason(self):
        line = session_log.lines_for("t3", "A lighthouse.", "The model did not answer.", "stopped")[-1]
        self.assertEqual((line["kind"], line["content"]), ("error", "The model did not answer."))
        self.assertEqual(session_log.lines_for("t3", "x", "", "cancelled")[-1]["content"], "cancelled")

    def test_a_long_reply_is_cut_to_the_services_limit(self):
        line = session_log.lines_for("t4", "x", "y" * 30000, "done")[-1]
        self.assertEqual(len(line["content"]), session_log.LINE_CHARS)

    def test_prompts_come_back_newest_first_and_capped(self):
        messages = [{"role": "user", "content": "one"}, {"role": "assistant", "content": "Built."},
                    {"role": "user", "content": "two"}, {"role": "user", "content": " "},
                    {"role": "user", "content": "three"}]
        self.assertEqual(session_log.prompts_from(messages, 2), ["three", "two"])
        self.assertEqual(session_log.prompts_from(None, 5), [])

    def test_unavailable_is_the_api_saying_no_not_a_network_fault(self):
        self.assertTrue(session_log.unavailable(ApiError("no", status=403)))
        self.assertTrue(session_log.unavailable(ApiError("no route", status=404)))
        self.assertFalse(session_log.unavailable(ApiError("down", status=503)))
        self.assertFalse(session_log.unavailable(ApiError("Network error")))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer().__enter__()
        self.client = EachlabsClient("key", base_url=self.server.url)
        self.lines = session_log.lines_for("t1", "A lighthouse.", "Built it.", "done")

    def tearDown(self):
        self.server.__exit__()

    def _stored(self, sessions):
        self.server.route("GET", "/v1/eachsense/sessions", (200, {}, {"sessions": sessions}))
        self.server.route("POST", "/v1/eachsense/sessions/lines",
                          lambda r: (200, {}, {"session_id": r.json().get("session_id") or "new"}))

    def test_the_first_run_of_a_scene_starts_its_session(self):
        self._stored([])
        self.assertEqual(session_log.write(self.client, "run1", self.lines), "new")
        sent = self.server.find("POST", "/v1/eachsense/sessions/lines")[0].json()
        self.assertEqual((sent["surface"], sent["scope"]), ("blender", "run1"))
        self.assertNotIn("session_id", sent)

    def test_a_reopened_file_continues_the_session_it_had(self):
        self._stored([{"id": "s1", "scope": "run1"}])
        self.assertEqual(session_log.write(self.client, "run1", self.lines), "s1")

    def test_a_known_session_is_not_looked_up_again(self):
        self._stored([])
        self.assertEqual(session_log.write(self.client, "run1", self.lines, session_id="s1"), "s1")
        self.assertEqual(self.server.find("GET", "/v1/eachsense/sessions"), [])

    def test_read_gives_the_session_and_its_prompts(self):
        self._stored([{"id": "s1"}])
        self.server.route("GET", "/v1/eachsense/sessions/s1", (200, {}, {"messages": [
            {"role": "user", "content": "A lighthouse."}, {"role": "assistant", "content": "Built it."},
            {"role": "user", "content": "Make it taller."}]}))
        self.assertEqual(session_log.read(self.client, "run1", 20), ("s1", ["Make it taller.", "A lighthouse."]))

    def test_read_of_a_scene_without_a_session_is_empty(self):
        self._stored([])
        self.assertEqual(session_log.read(self.client, "run1", 20), (None, []))


if __name__ == "__main__":
    unittest.main()
