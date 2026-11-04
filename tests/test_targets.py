import unittest

from eachlabs.chat.stages import ORDER
from eachlabs.instructions import targets


class RequestTest(unittest.TestCase):
    def test_a_scene_keeps_the_persons_words(self):
        self.assertEqual(targets.request("scene", "a cabin at night", fresh=False), "a cabin at night")
        self.assertEqual(targets.request("unknown", "a cabin", fresh=True), "a cabin")

    def test_an_asset_in_a_scene_adds_one_thing_and_keeps_what_exists(self):
        text = targets.request("asset", " a wooden barrel ", fresh=False)
        self.assertTrue(text.startswith("Add exactly one new thing to the scene: a wooden barrel\n"))
        self.assertIn("Change nothing that exists", text)
        self.assertIn("leave the light, the sky and the camera", text)

    def test_a_character_is_the_main_object(self):
        text = targets.request("character", "a fox", fresh=False)
        self.assertTrue(text.startswith("Add exactly one new character to the scene: a fox\n"))
        self.assertIn("main object", text)

    def test_on_an_empty_scene_the_thing_is_shown_on_its_own(self):
        for target in ("asset", "character"):
            with self.subTest(target):
                text = targets.request(target, "a fox", fresh=True)
                self.assertIn("on its own: a fox", text)
                self.assertIn("camera move", text)


class StagesTest(unittest.TestCase):
    def test_an_addition_to_a_scene_skips_light_and_camera(self):
        for target in ("asset", "character"):
            with self.subTest(target):
                self.assertEqual(targets.stages(target, False, ORDER), ("layout", "detail", "materials", "check"))

    def test_a_scene_and_an_empty_scene_run_every_stage(self):
        self.assertEqual(targets.stages("scene", False, ORDER), ORDER)
        self.assertEqual(targets.stages("asset", True, ORDER), ORDER)
        self.assertEqual(targets.stages("character", True, ORDER), ORDER)


if __name__ == "__main__":
    unittest.main()
