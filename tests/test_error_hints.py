import unittest

from eachlabs import code_check, error_hints


class CloseNamesTest(unittest.TestCase):
    def test_a_name_containing_the_wanted_one_comes_first(self):
        self.assertEqual(error_hints.close_names("translation_matrix", ["Translation", "translation", "_private",
                                                                        "to_euler"])[:2],
                         ["Translation", "translation"])

    def test_private_names_are_never_offered(self):
        self.assertNotIn("_private", error_hints.close_names("private", ["_private", "public"]))


class HintTest(unittest.TestCase):
    def test_a_missing_faces_key_after_a_create_operator_says_what_it_returns(self):
        error = "Traceback ...\nKeyError: 'faces'"
        code = "r = bmesh.ops.create_cube(bm, size=1)\nfor f in r['faces']: pass"
        self.assertIn("return only {\"verts\": [...]}", error_hints.hint(error, code))

    def test_a_missing_key_elsewhere_gets_no_hint(self):
        self.assertEqual(error_hints.hint("KeyError: 'faces'", "d = {}\nd['faces']"), "")
        self.assertEqual(error_hints.hint("KeyError: 'colour'", "bmesh.ops.create_cube(bm)"), "")


class RefusalTest(unittest.TestCase):
    def refusal(self, code):
        with self.assertRaises(code_check.Refused) as caught:
            code_check.check(code)
        return str(caught.exception)

    def test_dunder_import_names_the_modules_every_step_already_has(self):
        self.assertIn("already has bpy, bmesh, mathutils, math and random imported",
                      self.refusal('random = __import__("random")'))

    def test_a_private_name_says_how_to_rename_it(self):
        self.assertIn("helper, not _helper", self.refusal("_helper = 1"))


if __name__ == "__main__":
    unittest.main()
