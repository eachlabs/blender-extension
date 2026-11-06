import unittest

from eachlabs.shot.keyframes import pick, pick_until, share, surrounds

REVEAL = {
    1: {"Bookshelf": 1.0},
    61: {"Bookshelf": 0.9},
    121: {"Fireplace": 1.0, "Picture": 1.0},
    175: {"Fireplace": 0.4, "Armchair": 0.7, "Window": 0.8},
    241: {"Armchair": 1.0, "Window": 1.0},
}


class PickTests(unittest.TestCase):
    def test_reveal_picks_whole_fireplace(self):
        self.assertEqual(pick(REVEAL, 1), [1, 121, 241])

    def test_no_things_gives_first_frame(self):
        self.assertEqual(pick({1: {}, 7: {}}, 1), [1])

    def test_frame_one_covers_everything(self):
        self.assertEqual(pick({1: {"A": 1.0}, 7: {"A": 1.0}}, 1), [1])

    def test_limit_caps_frames(self):
        views = {f: {str(f): 1.0} for f in range(1, 200, 6)}
        self.assertEqual(len(pick(views, 1, 9)), 9)

    def test_thing_in_view_at_every_frame_needs_no_frame(self):
        views = {1: {"Floor": 0.3, "A": 1.0}, 7: {"Floor": 1.0}, 13: {"Floor": 0.5, "B": 1.0}}
        self.assertEqual(pick(views, 1), [1, 13])

    def test_reveal_with_a_floor_in_every_frame(self):
        views = {frame: dict(shown, Floor=0.6 if frame == 175 else 0.2) for frame, shown in REVEAL.items()}
        self.assertEqual(pick(views, 1), [1, 121, 241])

    def test_merges_frames_covering_same_things(self):
        self.assertEqual(pick({1: {}, 7: {"A": 1.0, "B": 0.9}, 13: {"B": 1.0}}, 1), [1, 7])


class PickUntilTests(unittest.TestCase):
    VIEWS = {1: {"a": 1.0}, 7: {"a": 1.0, "b": 0.4}, 13: {"a": 1.0, "c": 0.8}, 19: {"a": 1.0, "c": 0.2}}

    def test_a_shorter_video_picks_from_the_same_measure(self):
        self.assertEqual(pick_until(self.VIEWS, 1, 19), pick(self.VIEWS, 1))
        self.assertEqual(pick_until(self.VIEWS, 1, 10), [1, 7])  # c comes into view after the video ends
        self.assertEqual(pick_until(self.VIEWS, 1, 1), [1])


class ShareTests(unittest.TestCase):
    def test_whole_box_in_frame(self):
        self.assertEqual(share([(0.2, 0.4, 0.2, 0.4)]), 1.0)

    def test_half_cut_off_by_the_edge(self):
        self.assertEqual(share([(-0.1, 0.1, 0.4, 0.6)]), 0.5)

    def test_out_of_frame_is_zero(self):
        self.assertEqual(share([(1.2, 1.5, 0.2, 0.4)]), 0.0)
        self.assertEqual(share([]), 0.0)

    def test_close_up_overflowing_the_frame_counts(self):
        self.assertEqual(share([(-3.0, 4.0, -2.0, 3.0)]), 1.0)

    def test_parts_make_one_box(self):
        self.assertEqual(share([(0.1, 0.2, 0.1, 0.2), (0.9, 1.1, 0.1, 0.2)]), 0.9)


class SurroundsTests(unittest.TestCase):
    CUBE = [(x, y, z) for x in (-1, 1) for y in (-2, 2) for z in (0, 3)]

    def test_point_inside_the_box(self):
        self.assertTrue(surrounds(self.CUBE, (0.5, -1.5, 2.9)))

    def test_point_outside_the_box(self):
        self.assertFalse(surrounds(self.CUBE, (0.5, -1.5, 3.1)))
        self.assertFalse(surrounds(self.CUBE, (1.2, 0.0, 1.0)))

    def test_no_corners(self):
        self.assertFalse(surrounds([], (0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
