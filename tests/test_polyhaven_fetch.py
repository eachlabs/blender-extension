import hashlib
import json
import os
import shutil
import tempfile
import unittest

from eachlabs.polyhaven import fetch

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
HDR = b"#?RADIANCE\n" + b"0" * 64
ASSETS = {"castle_brick_02_red": {"name": "Castle Brick 02 Red", "tags": ["brick", "red", "wall"],
                                  "dimensions": [1500, 1500]}}


def md5(data):
    return hashlib.md5(data).hexdigest()


class FakeClient:
    """Serves the Poly Haven URLs from memory, like ``EachlabsClient.download``."""

    def __init__(self, files, fail=False):
        self.files, self.fail, self.calls = files, fail, []

    def download(self, url, dest, cancel_event=None, max_bytes=0, wait_seconds=None):
        self.calls.append(url)
        if self.fail:
            raise OSError("no network")
        with open(dest, "wb") as handle:
            handle.write(self.files[url])
        return "application/octet-stream"


def texture_site(color=JPEG, listed_md5=None):
    files = {"Diffuse": {"1k": {"jpg": {"url": "https://dl/brick_diff.jpg", "md5": listed_md5 or md5(color)}}}}
    return {
        "https://api.polyhaven.com/assets?t=textures": json.dumps(ASSETS).encode(),
        "https://api.polyhaven.com/files/castle_brick_02_red": json.dumps(files).encode(),
        "https://dl/brick_diff.jpg": color,
    }


class Fetch(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_texture_downloads_once(self):
        client = FakeClient(texture_site())
        found = fetch.Haven(client, self.folder).texture("red brick wall")
        self.assertEqual(found["id"], "castle_brick_02_red")
        self.assertEqual(found["tile_m"], 1.5)
        self.assertTrue(os.path.exists(found["maps"]["color"]))
        calls = len(client.calls)
        fetch.Haven(client, self.folder).texture("red brick wall")  # a new run: everything from the cache
        self.assertEqual(len(client.calls), calls)

    def test_damaged_file_is_refused(self):
        client = FakeClient(texture_site(listed_md5="0" * 32))
        with self.assertRaises(fetch.HavenError):
            fetch.Haven(client, self.folder).texture("red brick wall")

    def test_not_a_picture_is_refused(self):
        client = FakeClient(texture_site(color=b"<html>oops</html>"))
        with self.assertRaises(fetch.HavenError):
            fetch.Haven(client, self.folder).texture("red brick wall")

    def test_offline_says_what_to_do(self):
        with self.assertRaises(fetch.HavenError) as caught:
            fetch.Haven(FakeClient({}, fail=True), self.folder).sky("night sky")
        self.assertIn("procedural", str(caught.exception))

    def test_sky(self):
        sky = {"moonless_golf": {"name": "Moonless Golf", "tags": ["night"], "attributes": {"time_of_day": "night"}}}
        files = {"hdri": {"2k": {"hdr": {"url": "https://dl/m_2k.hdr", "md5": md5(HDR)}}}}
        client = FakeClient({"https://api.polyhaven.com/assets?t=hdris": json.dumps(sky).encode(),
                             "https://api.polyhaven.com/files/moonless_golf": json.dumps(files).encode(),
                             "https://dl/m_2k.hdr": HDR})
        found = fetch.Haven(client, self.folder).sky("clear night")
        self.assertEqual(found["name"], "Moonless Golf")
        self.assertTrue(found["path"].endswith("m_2k.hdr"))


if __name__ == "__main__":
    unittest.main()
