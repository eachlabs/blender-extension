import json
import unittest

from eachlabs import plan3d
from eachlabs.chat import problems
from eachlabs.checks import colours


class AskedColourTest(unittest.TestCase):
    def test_the_plan_keeps_an_asked_colour(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [], "code": [
            {"name": "sofa", "colour": "#B01818"}, {"name": "rug", "color": "b0b0b0"},
            {"name": "lamp", "colour": "red"}]}), 2)
        sofa, rug, lamp = plan.items
        self.assertEqual((sofa.colour, rug.colour, lamp.colour), ("#b01818", "#b0b0b0", ""))
        self.assertIn('that colour as "#rrggbb"', plan3d.system(2))

    def test_a_dull_brown_is_not_the_asked_red(self):
        red, brown, dark_red = (0.69, 0.09, 0.09), (0.48, 0.35, 0.25), (0.55, 0.08, 0.08)
        self.assertGreater(colours.difference(red, brown), colours.DIFFERENT)
        self.assertLess(colours.difference(red, dark_red), colours.DIFFERENT)

    def test_a_small_part_of_the_right_colour_does_not_count(self):
        red = colours.hex_rgb("#b01818")
        has, gap = colours.closest(red, [(0.85, (0.48, 0.35, 0.25)), (0.15, red)])
        self.assertEqual(has, (0.48, 0.35, 0.25))
        self.assertGreater(gap, colours.DIFFERENT)
        has, gap = colours.closest(red, [(0.6, (0.48, 0.35, 0.25)), (0.4, red)])
        self.assertEqual(gap, 0.0)

    def test_hex_and_linear(self):
        self.assertEqual(colours.hex_rgb("#ff0000"), (1.0, 0.0, 0.0))
        self.assertIsNone(colours.hex_rgb("red"))
        self.assertEqual(colours.hex_of(colours.to_srgb((0.2159, 0.2159, 0.2159))), "#808080")

    def test_the_fix_stage_gets_it_and_the_reply_names_it(self):
        found = problems.placement_problems({"colour_off": [{"thing": "Sofa", "asked": "#b01818", "has": "#7a5a40"}]})
        self.assertEqual(problems.problem_items(found), ["Sofa is #7a5a40, not the asked #b01818"])


if __name__ == "__main__":
    unittest.main()
