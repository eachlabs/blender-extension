import unittest

from eachlabs import timing


class SceneFpsTest(unittest.TestCase):
    def test_integer_and_fractional_rates(self):
        self.assertEqual(timing.scene_fps(24), 24.0)
        self.assertAlmostEqual(timing.scene_fps(30000, 1001), 29.97003, places=5)

    def test_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            timing.scene_fps(0)
        with self.assertRaises(ValueError):
            timing.scene_fps(24, 0)


class RangeTest(unittest.TestCase):
    def test_inclusive_length(self):
        self.assertEqual(timing.range_length(1, 48), 48)
        self.assertEqual(timing.range_length(101, 101), 1)

    def test_reversed_range(self):
        with self.assertRaises(ValueError):
            timing.range_length(10, 9)


class TargetLengthTest(unittest.TestCase):
    def test_fit_range_matches_rendered_frames_whatever_the_clip(self):
        # A 5 s, 30 fps result for a 48-frame render at 24 fps still spans 48 frames.
        self.assertEqual(timing.target_length(150, 30.0, 24.0, 48, timing.FIT_RANGE), 48)

    def test_keep_timing_converts_duration_to_timeline_frames(self):
        self.assertEqual(timing.target_length(150, 30.0, 24.0, 48, timing.KEEP_TIMING), 120)
        self.assertEqual(timing.target_length(48, 24.0, 24.0, 10, timing.KEEP_TIMING), 48)
        # 121 frames at 24 fps on a 29.97 fps timeline.
        self.assertEqual(timing.target_length(121, 24.0, 30000 / 1001, 0, timing.KEEP_TIMING), 151)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            timing.target_length(0, 24, 24, 48)
        with self.assertRaises(ValueError):
            timing.target_length(10, 24, 24, 0, timing.FIT_RANGE)
        with self.assertRaises(ValueError):
            timing.target_length(10, 0, 24, 48, timing.KEEP_TIMING)
        with self.assertRaises(ValueError):
            timing.target_length(10, 24, 24, 48, "SOMETHING")


class SpeedTest(unittest.TestCase):
    def test_speed_factor(self):
        self.assertAlmostEqual(timing.speed_factor(120, 48), 2.5)
        self.assertAlmostEqual(timing.speed_factor(48, 60), 0.8)
        self.assertEqual(timing.speed_factor(48, 48), 1.0)

    def test_needs_retime(self):
        self.assertFalse(timing.needs_retime(48, 48))
        self.assertTrue(timing.needs_retime(121, 48))
        self.assertFalse(timing.needs_retime(49, 48))  # a short surplus tail is trimmed
        self.assertFalse(timing.needs_retime(50, 48))
        self.assertTrue(timing.needs_retime(51, 48))
        self.assertTrue(timing.needs_retime(47, 48))

    def test_speed_rejects_zero(self):
        with self.assertRaises(ValueError):
            timing.speed_factor(48, 0)

    def test_fit_then_speed_round_trip(self):
        # 30 fps result with 61 frames fitted to a 48 frame render at 24 fps.
        length = timing.target_length(61, 30.0, 24.0, 48)
        self.assertEqual(length, 48)
        self.assertAlmostEqual(timing.speed_factor(61, length) * length, 61)


class ChannelTest(unittest.TestCase):
    def test_empty_timeline_uses_channel_one(self):
        self.assertEqual(timing.first_free_channel([], 1, 48), 1)

    def test_skips_overlapping_channels_only(self):
        occupied = [(1, 1, 49), (2, 40, 100), (3, 49, 80)]
        # [1, 49) overlaps channel 1 and 2; channel 3 starts exactly at 49, so it is free.
        self.assertEqual(timing.first_free_channel(occupied, 1, 48), 3)

    def test_adjacent_strip_is_not_overlap(self):
        self.assertEqual(timing.first_free_channel([(1, 49, 60)], 1, 48), 1)

    def test_no_free_channel(self):
        occupied = [(c, 0, 1000) for c in range(1, 4)]
        with self.assertRaises(ValueError):
            timing.first_free_channel(occupied, 10, 5, max_channel=3)


class PreviewTest(unittest.TestCase):
    def test_percentages(self):
        self.assertEqual(timing.preview_percentage(1080, 720), 67)
        self.assertEqual(timing.preview_percentage(1080, 480), 44)
        self.assertEqual(timing.preview_percentage(1080, 0), 100)
        self.assertEqual(timing.preview_percentage(720, 1080), 100)

    def test_even_dimensions(self):
        self.assertEqual(timing.even_dimensions(1281, 721), (1280, 720))
        self.assertEqual(timing.even_dimensions(1, 1), (2, 2))


if __name__ == "__main__":
    unittest.main()
