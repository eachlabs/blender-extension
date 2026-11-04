import unittest

from eachlabs.chat import quality
from eachlabs.chat.run_types import Limits
from eachlabs.chat.stages import STAGE_ROUNDS, TOTAL_ROUNDS


class AdvancedTest(unittest.TestCase):
    def test_keeps_every_value_the_preferences_hold(self):
        mode = quality.ADVANCED
        limits = Limits(total_rounds=TOTAL_ROUNDS, max_failures=4)
        self.assertIs(quality.limits(mode, limits), limits)
        self.assertEqual(quality.rounds_cap(mode, 90), 90)
        self.assertEqual(quality.detail_rounds(mode, 3), 3)
        self.assertEqual(quality.secondary_rounds(mode, 1), 1)
        self.assertEqual(quality.candidates(mode, 2), 2)
        self.assertTrue(quality.references(mode, True))
        self.assertEqual(quality.stage_model(mode, "openai/gpt-6-astra"), "openai/gpt-6-astra")


class PrototypeTest(unittest.TestCase):
    def test_trims_only_the_look_and_keeps_layout_camera_and_check(self):
        limits = quality.limits(quality.PROTOTYPE, Limits(total_rounds=TOTAL_ROUNDS))
        self.assertEqual(limits.stage_rounds, {"layout": 3, "materials": 1, "light": 1, "camera": 3, "check": 2})
        self.assertEqual(limits.total_rounds, 10)
        self.assertEqual(STAGE_ROUNDS["layout"], 4)  # the shared defaults are left alone

    def test_never_more_than_the_persons_own_total(self):
        self.assertEqual(quality.limits(quality.PROTOTYPE, Limits(total_rounds=8)).total_rounds, 8)

    def test_one_model_no_pictures_light_detail(self):
        mode = quality.PROTOTYPE
        self.assertEqual(quality.rounds_cap(mode, 90), 40)
        self.assertEqual(quality.rounds_cap(mode, 20), 20)
        self.assertEqual(quality.detail_rounds(mode, 3), 1)
        self.assertEqual(quality.detail_rounds(mode, 0), 0)  # the detail stage turned off stays off
        self.assertEqual(quality.secondary_rounds(mode, 1), 0)
        self.assertEqual(quality.candidates(mode, 3), 1)
        self.assertFalse(quality.references(mode, True))
        self.assertEqual(quality.stage_model(mode, "anthropic/claude-sonnet-5.5"), "")

    def test_terra_builds_a_prototype_unless_the_person_chose_a_model(self):
        default = "openai/gpt-6-sol"
        self.assertEqual(quality.scene_model(quality.PROTOTYPE, default, default), "openai/gpt-6.1-terra")
        self.assertEqual(quality.scene_model(quality.PROTOTYPE, "vendor/mine", default), "vendor/mine")
        self.assertEqual(quality.scene_model(quality.ADVANCED, default, default), default)

    def test_a_cheap_concept_picture_and_no_generated_textures(self):
        self.assertEqual(quality.concept(quality.PROTOTYPE, "nano-banana-pro", 0.15),
                         ("z-image-turbo-text-to-image", 0.005))
        self.assertEqual(quality.concept(quality.ADVANCED, "nano-banana-pro", 0.15), ("nano-banana-pro", 0.15))
        self.assertEqual(quality.textures(quality.PROTOTYPE, 6), 0)
        self.assertEqual(quality.textures(quality.ADVANCED, 6), 6)

    def test_unknown_mode_is_prototype(self):
        self.assertEqual(quality.mode_of(None), quality.PROTOTYPE)
        self.assertEqual(quality.mode_of("FAST"), quality.PROTOTYPE)
        self.assertEqual(quality.mode_of(quality.ADVANCED), quality.ADVANCED)


if __name__ == "__main__":
    unittest.main()
