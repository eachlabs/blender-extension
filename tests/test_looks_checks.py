import unittest

from eachlabs.checks import looks, text_facing


class Looks(unittest.TestCase):
    def test_textured_walls_next_to_plain_houses_are_mixed(self):
        found = looks.mixed({"Town wall stone": (300.0, True), "House plaster": (500.0, False),
                             "Roof tiles": (200.0, False), "Door handle": (0.1, True)})
        self.assertEqual(found["textured"], ["Town wall stone"])
        self.assertIn("House plaster", found["plain"])
        self.assertNotIn("Door handle", found["plain"] + found["textured"])  # a detail may differ

    def test_one_look_is_fine(self):
        self.assertIsNone(looks.mixed({"Plaster": (500.0, False), "Roof": (200.0, False)}))
        self.assertIsNone(looks.mixed({"Plaster": (500.0, True), "Roof": (200.0, True)}))
        self.assertIsNone(looks.mixed({"Ground": (5000.0, True), "Bench": (8.0, False)}))  # 99% textured

    def test_surface(self):
        self.assertEqual(looks.surface_m2((2, 3, 4)), 52.0)


class Text(unittest.TestCase):
    def test_front_reads_right(self):
        self.assertFalse(text_facing.reads_backwards(0.8, 1.0))

    def test_from_behind_reads_backwards(self):
        self.assertTrue(text_facing.reads_backwards(-0.8, 1.0))

    def test_mirroring_scale_reads_backwards_from_the_front(self):
        self.assertTrue(text_facing.reads_backwards(0.8, -1.0))
        self.assertFalse(text_facing.reads_backwards(-0.8, -1.0))


if __name__ == "__main__":
    unittest.main()
