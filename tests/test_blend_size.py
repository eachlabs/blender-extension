import unittest

from eachlabs.scene import blend_size


class BlendSizeTest(unittest.TestCase):
    def test_thin_part_stays_several_voxels_across(self):
        voxel, _ = blend_size.settings([(0.6, 0.3, 0.3), (0.06, 0.06, 0.3)], 0.6, 0.0)
        self.assertAlmostEqual(voxel, 0.005)
        self.assertGreaterEqual(0.06 / voxel, blend_size.VOXELS_THINNEST[1])

    def test_softer_means_coarser_and_more_smoothing(self):
        hard = blend_size.settings([(0.6, 0.3, 0.3), (0.06, 0.06, 0.3)], 0.6, 0.0)
        soft = blend_size.settings([(0.6, 0.3, 0.3), (0.06, 0.06, 0.3)], 0.6, 1.0)
        self.assertGreater(soft[0], hard[0])
        self.assertEqual((hard[1], soft[1]), blend_size.SMOOTH_STEPS)

    def test_large_result_caps_the_mesh_size(self):
        voxel, _ = blend_size.settings([(12.0, 4.0, 4.0), (0.05, 0.05, 1.0)], 12.0, 0.5)
        self.assertAlmostEqual(voxel, 12.0 / blend_size.VOXELS_WIDEST)

    def test_flat_part_and_softness_out_of_range(self):
        voxel, steps = blend_size.settings([(1.0, 1.0, 0.0), (1.0, 1.0, 1.0)], 0.05, 3)
        self.assertEqual(voxel, blend_size.VOXEL_MIN_M)
        self.assertEqual(steps, blend_size.SMOOTH_STEPS[1])

    def test_thin_and_flat_parts_stay_out(self):
        self.assertTrue(blend_size.thin((0.04, 0.04, 0.35)))  # a tail
        self.assertTrue(blend_size.thin((0.1, 0.016, 0.12)))  # an ear
        self.assertFalse(blend_size.thin((0.1, 0.1, 0.4)))  # a leg
        self.assertFalse(blend_size.thin((0.7, 0.32, 0.32)))  # a body
        self.assertTrue(blend_size.thin((0.0, 0.0, 0.0)))

    def test_colours_meet_the_same_from_both_sides(self):
        colours = [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)]
        shares = blend_size.weights([0.0, 0.0], 0.1)
        self.assertEqual(shares, [0.5, 0.5])
        for own in (0, 1):  # each side shows own * (1 - mix) + other * mix
            r, g, b, mix = blend_size.other_colour(shares, colours, own)
            shown = [colours[own][c] * (1 - mix) + (r, g, b)[c] * mix for c in range(3)]
            self.assertEqual(shown, [0.5, 0.0, 0.5])
        self.assertEqual(blend_size.weights([0.0, None], 0.1), [1.0, 0.0])
        self.assertEqual(blend_size.other_colour([1.0, 0.0], colours, 0)[3], 0.0)
        self.assertEqual(blend_size.weights([None, None], 0.1), [0.0, 0.0])
        self.assertGreater(blend_size.edge_width(0.01, 1.0), blend_size.edge_width(0.01, 0.0))


if __name__ == "__main__":
    unittest.main()
