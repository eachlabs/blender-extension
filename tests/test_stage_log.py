import json
import os
import tempfile
import unittest
from unittest import mock

from eachlabs.chat import stage_log


def lines(folder):
    with open(os.path.join(folder, stage_log.FILE)) as fh:
        return [json.loads(line) for line in fh]


class StageLogTest(unittest.TestCase):
    def setUp(self):
        stage_log._last.update(finished=0.0, prompt="")

    def test_prompt_is_a_hash_by_default(self):
        folder = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"EACHLABS_CHAT_LOG": ""}):
            stage_log.finished(folder, "a secret harbour", "done", {"layout": "done"})
        row = lines(folder)[0]
        self.assertEqual(row["action"], "finished")
        self.assertNotIn("text", row)
        self.assertNotIn("harbour", json.dumps(row))
        self.assertEqual(row["stages"], {"layout": "done"})

    def test_prompt_text_only_with_the_chat_log_on(self):
        folder = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"EACHLABS_CHAT_LOG": "/tmp/x.jsonl"}):
            stage_log.undone(folder, "a harbour", "light")
        self.assertEqual(lines(folder)[0]["text"], "a harbour")

    def test_a_follow_up_soon_after_counts_as_an_edit(self):
        folder = tempfile.mkdtemp()
        stage_log.finished(folder, "a harbour", "done", {})
        stage_log.started(folder, "remove the lighthouse", True)
        stage_log.started(folder, "a new scene", False)
        actions = [r["action"] for r in lines(folder)]
        self.assertEqual(actions, ["finished", "edited_after"])

    def test_a_big_file_keeps_its_newest_half(self):
        folder = tempfile.mkdtemp()
        with mock.patch.object(stage_log, "BYTES_MAX", 200):
            for n in range(20):
                stage_log.retried(folder, "p%d" % n, "check")
        self.assertLess(len(lines(folder)), 20)
        self.assertEqual(lines(folder)[-1]["prompt"], stage_log.prompt_hash("p19"))


if __name__ == "__main__":
    unittest.main()
