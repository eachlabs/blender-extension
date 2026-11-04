import unittest

from eachlabs.things import ids


class LabelsTest(unittest.TestCase):
    def test_labels_are_cleaned_and_drop_the_kind(self):
        self.assertEqual(ids.labels("Wall, perimeter_wall, fence, wall", kind="fence"), ["wall", "perimeter wall"])

    def test_labels_are_capped(self):
        self.assertEqual(len(ids.labels(",".join("w%d" % i for i in range(20)))), ids.LABELS_MAX)

    def test_kind_from_name_drops_numbers(self):
        self.assertEqual(ids.kind_from_name("Shore_Pine_007.002"), "shore pine")
        self.assertEqual(ids.kind_from_name(""), "thing")


class NamesTest(unittest.TestCase):
    def test_base_name_keeps_the_models_words_and_case(self):
        self.assertEqual(ids.base_name("town_hall.002"), "Town hall")
        self.assertEqual(ids.base_name("Building A"), "Building A")
        self.assertEqual(ids.base_name("Shore_Pine_007"), "Shore Pine")

    def test_child_thing_names_its_parent(self):
        self.assertEqual(ids.thing_name("clock", "Town hall"), "Clock (Town hall)")
        self.assertEqual(ids.thing_name("town hall"), "Town hall")

    def test_part_name_drops_the_things_words(self):
        self.assertEqual(ids.part_name("Town hall", "town_hall_roof.001", "building"), "Town hall / Roof")
        self.assertEqual(ids.part_name("Fence", "fence"), "Fence / Fence")
        self.assertEqual(ids.part_name("Car", "Car_Wheel_FL"), "Car / Wheel FL")

    def test_names_fit_blender(self):
        self.assertLessEqual(len(ids.part_name("x" * 50, "y" * 50)), ids.NAME_MAX)


class MatchTest(unittest.TestCase):
    def test_a_label_finds_a_thing_named_otherwise(self):
        entry = {"name": "Larger village stone perimeter wall", "kind": "fence", "labels": ["wall", "boundary"]}
        self.assertTrue(ids.matches(entry, "fence"))
        self.assertTrue(ids.matches(entry, "boundary"))
        self.assertFalse(ids.matches(entry, "church"))


class SubtreeTest(unittest.TestCase):
    def test_child_things_come_along(self):
        parents = {"v": "", "hall": "v", "clock": "hall", "fence": "v", "tree": ""}
        self.assertEqual(sorted(ids.subtree(parents, "hall")), ["clock", "hall"])
        self.assertEqual(sorted(ids.subtree(parents, "v")), ["clock", "fence", "hall", "v"])


class InventoryTest(unittest.TestCase):
    def test_line_names_kind_labels_and_parent(self):
        line = ids.inventory_line({"name": "Clock (Town hall)", "kind": "clock", "labels": ["dial"],
                                   "parent": "Town hall", "parts": 4})
        self.assertEqual(line, "Clock (Town hall) | kind: clock | also: dial | in: Town hall | 4 parts")


if __name__ == "__main__":
    unittest.main()
