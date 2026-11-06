import unittest

from eachlabs.shot.models import ASPECTS
from eachlabs.shot.timing import STILL_SECONDS, Plan, clip_size, default_seconds, longest, plan


class TimingTests(unittest.TestCase):
    def test_default_uses_whole_move(self):
        self.assertEqual(plan(1, 240, 24, None), Plan(1, 240, 0, 10, False))

    def test_shorter_takes_first_part(self):
        self.assertEqual(plan(1, 240, 24, 6), Plan(1, 144, 0, 6, False))

    def test_long_move_flagged(self):
        p = plan(1, 528, 24, None)
        self.assertEqual((p.too_long, p.frame_end, p.seconds), (True, 360, 15))

    def test_short_move_holds_last(self):
        self.assertEqual(plan(1, 48, 24, None), Plan(1, 48, 48, 4, False))

    def test_still_camera_defaults_to_five_seconds(self):
        self.assertEqual(STILL_SECONDS, 5)
        self.assertEqual(default_seconds(1, 240, 24, moves=False), 5)
        self.assertEqual(default_seconds(1, 48, 24, moves=False), 5)
        self.assertEqual(default_seconds(1, 240, 24, moves=True), 10)  # a move: its own length

    def test_still_camera_may_run_up_to_fifteen_seconds(self):
        self.assertEqual(longest(1, 48, 24, moves=False), 15)  # no move to stay inside
        self.assertEqual(longest(1, 48, 24, moves=True), 4)
        self.assertEqual(longest(1, 240, 24, moves=True), 10)
        self.assertEqual(longest(1, 528, 24, moves=True), 15)

    def test_still_shot_holds_the_last_frame_of_a_short_range(self):
        self.assertEqual(plan(1, 1, 24, 5), Plan(1, 1, 119, 5, False))  # one frame held for 5 s
        self.assertEqual(plan(1, 48, 24, 5), Plan(1, 48, 72, 5, False))
        self.assertEqual(plan(1, 250, 24, 5), Plan(1, 120, 0, 5, False))  # a long range: its first 5 s

    def test_clip_sizes_inside_limits(self):
        for aspect in ASPECTS:
            w, h = clip_size(aspect)
            self.assertTrue(409_600 <= w * h <= 927_000, aspect)

    def test_clip_sizes(self):
        self.assertEqual(clip_size("16:9"), (1280, 720))
        self.assertEqual(clip_size("9:16"), (720, 1280))
        self.assertEqual(clip_size("1:1"), (960, 960))
        self.assertEqual(clip_size("4:3"), (1104, 828))
        self.assertEqual(clip_size("3:4"), (828, 1104))
        self.assertEqual(clip_size("21:9"), (1456, 624))


if __name__ == "__main__":
    unittest.main()
