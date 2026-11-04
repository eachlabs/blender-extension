import unittest

from eachlabs import api_lookup

PROPS = [{"id": "type", "type": "enum", "enum": ["POINT", "SUN", "SPOT", "AREA"], "desc": "Type of light"},
         {"id": "energy", "type": "float", "desc": "Light energy emitted"},
         {"id": "use_shadow", "type": "boolean", "desc": ""}]


class SplitTest(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(api_lookup.split_name("Light.type"), ("Light", "type"))
        self.assertEqual(api_lookup.split_name("bpy.types.Light.type"), ("Light", "type"))
        self.assertEqual(api_lookup.split_name(" bpy.types.EeveeSettings "), ("EeveeSettings", None))


class DescribeTest(unittest.TestCase):
    def test_one_property_lists_its_enum(self):
        text = api_lookup.describe("Light", PROPS, "5.2.3", "type")
        self.assertIn("Blender 5.2.3", text)
        self.assertIn("one of POINT, SUN, SPOT, AREA", text)
        self.assertNotIn("energy", text)

    def test_a_missing_property_names_close_ones(self):
        text = api_lookup.describe("Light", PROPS, "5.2.3", "shadow")
        self.assertIn("has no property shadow", text)
        self.assertIn("use_shadow", text)

    def test_a_type_lists_every_property(self):
        text = api_lookup.describe("Light", PROPS, "4.2.0")
        self.assertIn("- energy: float", text)
        self.assertIn("- use_shadow: boolean", text)

    def test_long_answers_are_cut(self):
        many = [{"id": "p%d" % i, "type": "float", "desc": "x" * 60} for i in range(200)]
        self.assertLessEqual(len(api_lookup.describe("Big", many, "5.2")), api_lookup.CHARS_MAX)


if __name__ == "__main__":
    unittest.main()
