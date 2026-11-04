import unittest

from eachlabs import viewport_marks as marks


class MarksTimingTests(unittest.TestCase):
    def setUp(self):
        marks.clear()

    def test_flash_fades_over_one_point_two_seconds(self):
        marks.flash(["A"], 10.0)
        self.assertEqual(marks.active_flashes(10.0), [("A", 1.0)])
        (name, alpha), = marks.active_flashes(10.6)
        self.assertEqual(name, "A")
        self.assertAlmostEqual(alpha, 0.5, places=6)
        self.assertEqual(marks.active_flashes(11.25), [])
        self.assertEqual(marks.active_flashes(12.0), [])

    def test_flashing_again_restarts(self):
        marks.flash(["A", "B"], 0.0)
        marks.flash(["A"], 1.0)
        got = dict(marks.active_flashes(1.3))
        self.assertAlmostEqual(got["A"], 1 - 0.3 / marks.FLASH_SECONDS, places=6)
        self.assertNotIn("B", got)

    def test_clear_empties_everything(self):
        marks.flash(["A"], 0.0)
        marks.set_camera_path([(0, 0, 0), (1, 1, 1)])
        marks.clear()
        self.assertEqual(marks.active_flashes(0.0), [])
        self.assertEqual(marks.camera_path(), [])
        self.assertFalse(marks.has_flashes())

    def test_camera_path_is_stored(self):
        marks.set_camera_path([(0, 0, 1), (4, 5, 6)])
        self.assertEqual(marks.camera_path(), [(0, 0, 1), (4, 5, 6)])
        marks.set_camera_path([])
        self.assertEqual(marks.camera_path(), [])

    def test_needs_redraw(self):
        self.assertFalse(marks.needs_redraw(True))
        marks.set_camera_path([(0, 0, 0), (1, 0, 0)])
        self.assertTrue(marks.needs_redraw(True))
        self.assertFalse(marks.needs_redraw(False))
        marks.set_camera_path([])
        marks.flash(["A"], 0.0)
        self.assertTrue(marks.needs_redraw(False))

    def test_dashed_pieces_lie_on_the_segment(self):
        points = marks.dashed((0, 0, 0), (10, 0, 0), dashes=5, share=0.5)
        self.assertEqual(len(points), 10)
        self.assertEqual(points[0], (0, 0, 0))
        self.assertAlmostEqual(points[1][0], 1.0)
        self.assertAlmostEqual(points[2][0], 2.0)
        self.assertAlmostEqual(points[-1][0], 9.0)

    def test_circle_points_sit_on_the_radius(self):
        points = marks.circle((1, 2, 3), (1, 0, 0), (0, 0, 1), 2.0, steps=8)
        self.assertEqual(len(points), 16)
        for x, y, z in points:
            self.assertAlmostEqual(((x - 1) ** 2 + (z - 3) ** 2) ** 0.5, 2.0)
            self.assertAlmostEqual(y, 2.0)


if __name__ == "__main__":
    unittest.main()
