import unittest

from eachlabs.shot.prompts import photo_prompt, video_prompt


class PromptTests(unittest.TestCase):
    def test_clip_is_camera_only(self):
        self.assertIn("Use it only for the camera move and the layout", video_prompt([0.0]))

    def test_names_each_photo(self):
        p = video_prompt([0.0, 5.0, 10.0])
        self.assertIn("@Image1 at the first frame, @Image2 at about 5 seconds, @Image3 at about 10 seconds", p)
        self.assertIn("@Image1 to @Image3 are real photographs", p)

    def test_singular_second_and_fraction(self):
        p = video_prompt([0.0, 1.0, 2.5])
        self.assertIn("@Image2 at about 1 second,", p)
        self.assertIn("@Image3 at about 2.5 seconds", p)

    def test_one_photo_wording(self):
        self.assertIn("@Image1 is a real photograph", video_prompt([0.0]))

    def test_empty_person_no_extras(self):
        p = video_prompt([0.0], "  ")
        self.assertIn("Add nothing and remove nothing.", p)
        self.assertNotIn("direction", p)

    def test_person_text_last(self):
        p = video_prompt([0.0], "a teacup on the table.")
        self.assertTrue(p.endswith("The person's direction: a teacup on the table."))
        self.assertIn("except what the person asks for below", p)

    def test_photo_gets_person(self):
        self.assertIn("rainy evening", photo_prompt("rainy evening"))
        self.assertNotIn("direction", photo_prompt())

    def test_no_scene_words(self):
        text = (video_prompt([0.0]) + photo_prompt()).lower()
        for word in ("room", "fire", "book", "plaster"):
            self.assertNotIn(word, text)


    def test_still_camera_says_the_camera_stays_still(self):
        p = video_prompt([0.0], still=True)
        self.assertNotIn("camera path", p)
        self.assertNotIn("camera move", p)
        self.assertIn("the camera stays still for the whole shot", p)
        self.assertIn("follow its camera path", video_prompt([0.0]))


if __name__ == "__main__":
    unittest.main()
