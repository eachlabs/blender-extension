import datetime
import os
import unittest

from eachlabs import naming


class IdTest(unittest.TestCase):
    def test_format_and_sorting(self):
        early = naming.new_id(datetime.datetime(2026, 10, 19, 15, 30, 12))
        late = naming.new_id(datetime.datetime(2026, 10, 19, 15, 30, 13))
        self.assertTrue(early.startswith("20261019-153012-"))
        self.assertTrue(naming.is_id(early))
        self.assertLess(early, late)

    def test_unique_within_one_second(self):
        moment = datetime.datetime(2026, 10, 19, 15, 30, 12)
        ids = {naming.new_id(moment) for _ in range(50)}
        self.assertGreater(len(ids), 40)

    def test_is_id_rejects_other_strings(self):
        self.assertFalse(naming.is_id("abc"))
        self.assertFalse(naming.is_id(""))
        self.assertFalse(naming.is_id(None))


class FolderTest(unittest.TestCase):
    def test_saved_file_gets_a_folder_next_to_it(self):
        folder = naming.output_dir("/projects/shot 010/orbit.v2.blend")
        self.assertEqual(folder, os.path.join("/projects/shot 010", "eachlabs", "orbit.v2"))

    def test_unsafe_characters_are_replaced(self):
        folder = naming.output_dir("/p/my:shot*?.blend")
        self.assertEqual(os.path.basename(folder), "my_shot")

    def test_unsaved_file_uses_system_temp(self):
        folder = naming.output_dir("", temp_root="/tmp/x")
        self.assertEqual(folder, os.path.join("/tmp/x", "eachlabs-blender", "unsaved"))


class PathTest(unittest.TestCase):
    def test_every_file_carries_its_id(self):
        set_id, job_id = "20261019-153012-a1b2", "20261019-153500-c3d4"
        self.assertEqual(os.path.basename(naming.input_path("/o", set_id, "still", "png")),
                         set_id + "_still.png")
        self.assertEqual(os.path.basename(naming.input_path("/o", set_id, "clip", ".mp4")),
                         set_id + "_clip.mp4")
        self.assertEqual(naming.frames_dir("/o", set_id), os.path.join("/o", set_id + "_frames"))
        self.assertEqual(naming.frame_pattern("/o", set_id), os.path.join("/o", set_id + "_frames", "frame_"))
        self.assertEqual(os.path.basename(naming.result_path("/o", job_id, 2, "mp4")), job_id + "_result_2.mp4")
        self.assertEqual(os.path.basename(naming.manifest_path("/o", job_id)), job_id + ".json")


class MediaTest(unittest.TestCase):
    def test_extension_from_url_then_content_type(self):
        self.assertEqual(naming.extension_for("https://cdn/x/out.MP4?sig=1"), "mp4")
        self.assertEqual(naming.extension_for("https://cdn/x/out", "image/jpeg; charset=binary"), "jpg")
        self.assertEqual(naming.extension_for("https://cdn/x/out.json", "application/json"), "bin")
        self.assertEqual(naming.extension_for("https://cdn/x/abc", "video/quicktime"), "mov")

    def test_media_kind(self):
        self.assertEqual(naming.media_kind("a.png"), "image")
        self.assertEqual(naming.media_kind("a.webm"), "video")
        self.assertEqual(naming.media_kind("a.bin", "video/mp4"), "video")
        self.assertIsNone(naming.media_kind("a.bin"))

    def test_upload_kinds(self):
        self.assertEqual(naming.upload_kind("/x/style.webp"), "image")
        self.assertEqual(naming.upload_kind("/x/ref.mov"), "video")
        self.assertEqual(naming.upload_kind("/x/score.mp3"), "audio")
        self.assertEqual(naming.upload_kind("/x/notes.txt"), "other")

    def test_upload_content_types(self):
        self.assertEqual(naming.content_type_for("/x/a_still.png"), "image/png")
        self.assertEqual(naming.content_type_for("/x/a_clip.mp4"), "video/mp4")
        self.assertEqual(naming.content_type_for("/x/a.xyz"), "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
