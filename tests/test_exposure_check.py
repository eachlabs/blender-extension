import unittest

from eachlabs.chat import pictures
from eachlabs.checks import exposure


class Exposure(unittest.TestCase):
    def test_dark_night_frame(self):
        mean, p90 = exposure.levels([0.02] * 95 + [0.6] * 5)
        note = exposure.assess(mean, p90)
        self.assertIn("too dark", note)

    def test_readable_night_frame_is_fine(self):
        self.assertEqual(exposure.assess(*exposure.levels([0.08] * 50 + [0.5] * 50)), "")

    def test_washed_out(self):
        self.assertIn("washed out", exposure.assess(0.95, 1.0))

    def test_note_reaches_the_model(self):
        found = {"images": ["data:image/png;base64,AA=="], "notes": [exposure.assess(0.03, 0.1)]}
        text = pictures.look_message(found)["content"][0]["text"]
        self.assertIn("brightness: too dark", text)


class ColourCast(unittest.TestCase):
    def test_an_orange_frame_is_named(self):
        note = exposure.assess(0.4, 0.7, 0.6, 0.2)
        self.assertIn("colour cast: the whole frame is orange", note)
        self.assertIn("Unless the request asks for warm", note)

    def test_a_blue_frame_is_named(self):
        self.assertIn("the whole frame is blue", exposure.assess(0.4, 0.7, 0.2, 0.5))

    def test_a_balanced_frame_says_nothing(self):
        self.assertEqual(exposure.assess(0.4, 0.7, 0.45, 0.35), "")
        self.assertEqual(exposure.assess(0.4, 0.7), "")

    def test_too_dark_comes_first(self):
        self.assertIn("too dark", exposure.assess(0.03, 0.1, 0.05, 0.01))


if __name__ == "__main__":
    unittest.main()
