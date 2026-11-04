import unittest
from unittest import mock

from eachlabs import thread_safety


class UnsafeTest(unittest.TestCase):
    def tearDown(self):
        thread_safety._chat_threads = thread_safety._gen_threads = 0

    def test_unsafe_only_while_a_chat_worker_runs_on_an_old_python(self):
        with mock.patch.object(thread_safety, "override_races", return_value=True):
            self.assertFalse(thread_safety.ops_override_unsafe())
            thread_safety.chat_thread_started()
            self.assertTrue(thread_safety.ops_override_unsafe())
            thread_safety.chat_thread_started()  # a new run while an abandoned worker still ends
            thread_safety.chat_thread_ended()
            self.assertTrue(thread_safety.ops_override_unsafe())
            thread_safety.chat_thread_ended()
            self.assertFalse(thread_safety.ops_override_unsafe())
            thread_safety.chat_thread_ended()  # never below zero
            thread_safety.chat_thread_started()
            self.assertTrue(thread_safety.ops_override_unsafe())

    def test_a_generation_worker_counts_after_the_chat_worker_ended(self):
        with mock.patch.object(thread_safety, "override_races", return_value=True):
            thread_safety.chat_thread_started()
            thread_safety.gen_thread_started()
            thread_safety.chat_thread_ended()
            self.assertTrue(thread_safety.ops_override_unsafe())  # the 3D worker still runs Python
            thread_safety.gen_thread_ended()
            self.assertFalse(thread_safety.ops_override_unsafe())
            thread_safety.gen_thread_ended()  # never below zero
            self.assertEqual(thread_safety._gen_threads, 0)

    def test_never_unsafe_from_python_3_12(self):
        with mock.patch.object(thread_safety, "override_races", return_value=False):
            thread_safety.chat_thread_started()
            self.assertFalse(thread_safety.ops_override_unsafe())


if __name__ == "__main__":
    unittest.main()
