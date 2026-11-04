import unittest

from eachlabs.checks import duplicates


def part(name, thing, centre, size=(0.9, 0.06, 0.9), vertices=96):
    return {"name": name, "thing": thing, "vertices": vertices, "size": list(size), "centre": list(centre)}


class DuplicatesTest(unittest.TestCase):
    def test_second_clock_face_over_the_first(self):
        found = duplicates.duplicates([part("tower clock face", "town hall", (0, 0, 12)),
                                       part("analog clock face", "analog clock", (0.02, 0.03, 12.05))])
        self.assertEqual(1, len(found))
        self.assertEqual("tower clock face", found[0]["copy"])
        self.assertEqual("analog clock face", found[0]["copy_of"])

    def test_a_row_of_windows_is_not_a_duplicate(self):
        row = [part("window %d" % i, "house", (i * 1.5, 0, 3)) for i in range(5)]
        self.assertEqual([], duplicates.duplicates(row))

    def test_stacked_logs_and_side_by_side_boards_are_not_duplicates(self):
        logs = [part("wall log %02d" % i, "cabin", (0, 0, 0.3 * i), size=(6.0, 0.3, 0.3)) for i in range(4)]
        boards = [part("floorboard %02d" % i, "cabin", (0.15 * i, 0, 0), size=(0.15, 4.0, 0.03)) for i in range(6)]
        self.assertEqual([], duplicates.duplicates(logs + boards))

    def test_books_side_by_side_on_a_shelf_are_not_duplicates(self):
        books = [part("book %d" % i, "shelf books", (0.04 * i, 0, 0.7), size=(0.03, 0.18, 0.24)) for i in range(6)]
        self.assertEqual([], duplicates.duplicates(books))

    def test_two_books_a_step_apart_and_a_third_elsewhere_are_still_duplicates(self):
        books = [part("book %d" % i, "shelf books", centre, size=(0.03, 0.18, 0.24))
                 for i, centre in enumerate(((0, 0, 0.7), (0.04, 0, 0.7), (0.5, 0, 0.7)))]
        self.assertEqual(["book 1"], [f["copy"] for f in duplicates.duplicates(books)])

    def test_different_size_or_shape_is_not_a_duplicate(self):
        self.assertEqual([], duplicates.duplicates([part("a", "x", (0, 0, 0)),
                                                    part("b", "x", (0, 0, 0), size=(1.4, 0.06, 0.9))]))
        self.assertEqual([], duplicates.duplicates([part("a", "x", (0, 0, 0)),
                                                    part("b", "x", (0, 0, 0), vertices=24)]))

    def test_the_list_is_capped(self):
        stack = [part("p%02d" % i, "x", (0, 0, 0)) for i in range(20)]
        self.assertEqual(duplicates.DUPLICATES_MAX, len(duplicates.duplicates(stack)))


class StackedTest(unittest.TestCase):
    def test_a_moved_clock_over_the_towers_own_dial(self):
        # measured in a real village: a separate clock's dial 0.7 m in front of the tower's dial, partly over it
        hall = {"name": "town hall_Clock south enamel dial", "thing": "town hall", "vertices": 130, "order": 2,
                "size": [3.32, 0.09, 3.32], "centre": [29.0, 17.1, 19.41]}
        clock = {"name": "Clock ivory dial", "thing": "analog clock", "vertices": 66, "order": 1,
                 "size": [4.08, 0.17, 4.08], "centre": [29.0, 16.35, 16.9]}
        found = duplicates.report([hall, clock])
        self.assertEqual(1, len(found))
        self.assertEqual("Clock ivory dial", found[0]["copy_of"])
        self.assertIn("clock", found[0]["same_job"])

    def test_glass_and_frame_of_one_window_are_not_versions(self):
        glass = {"name": "house_window glass", "thing": "house", "vertices": 8, "order": 1,
                 "size": [1.0, 0.02, 1.2], "centre": [0, 0, 2]}
        frame = {"name": "house_window frame", "thing": "house", "vertices": 40, "order": 2,
                 "size": [1.1, 0.06, 1.3], "centre": [0, 0.02, 2]}
        self.assertEqual([], duplicates.stacked([glass, frame]))

    def test_a_rebuilt_sign_stacks_on_its_old_version(self):
        old = {"name": "shop_Shop sign board", "thing": "shop", "vertices": 8, "order": 1,
               "size": [2.0, 0.05, 0.6], "centre": [0, 0, 3]}
        new = {"name": "shop_Shop sign board carved", "thing": "shop", "vertices": 120, "order": 5,
               "size": [2.1, 0.08, 0.62], "centre": [0, 0.05, 3]}
        pairs = duplicates.stacked([new, old])
        self.assertEqual([("shop_Shop sign board", "shop_Shop sign board carved")],
                         [(a["name"], b["name"]) for a, b in pairs])
        self.assertTrue(duplicates.similar_faces(*pairs[0]))
        self.assertEqual([], duplicates.report([new, old]))  # within one thing it is removed, not reported


if __name__ == "__main__":
    unittest.main()
