import unittest

from eachlabs.checks import emission


class HarshTest(unittest.TestCase):
    def test_strong_flat_white_is_harsh(self):
        self.assertTrue(emission.is_harsh((1.0, 0.95, 0.9), 30.0, False))

    def test_warm_colour_is_not(self):
        self.assertFalse(emission.is_harsh((1.0, 0.45, 0.1), 30.0, False))

    def test_varied_colour_is_not(self):
        self.assertFalse(emission.is_harsh((1.0, 1.0, 1.0), 30.0, True))

    def test_weak_glow_is_not(self):
        self.assertFalse(emission.is_harsh((1.0, 1.0, 1.0), 2.0, False))

    def test_dim_grey_is_not(self):
        self.assertFalse(emission.is_harsh((0.3, 0.3, 0.3), 30.0, False))


class WashedOutTest(unittest.TestCase):
    def test_strong_amber_flame_washes_out(self):
        self.assertTrue(emission.washes_out([(0.72, 0.09, 0.01)], 5.0))

    def test_amber_flame_at_flame_strength_does_not(self):
        self.assertFalse(emission.washes_out([(0.72, 0.09, 0.01)], 2.5))

    def test_a_ramp_washes_out_when_any_coloured_stop_does(self):
        self.assertTrue(emission.washes_out([(0.1, 0.02, 0.0), (1.0, 0.6, 0.1)], 4.0))

    def test_a_warm_white_bulb_is_meant_to_read_white(self):
        self.assertFalse(emission.washes_out([(1.0, 0.85, 0.7)], 25.0))


if __name__ == "__main__":
    unittest.main()
