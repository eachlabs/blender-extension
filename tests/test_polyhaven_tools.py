import unittest

from eachlabs import scene_tools
from eachlabs.polyhaven import fetch, tools


class Args(unittest.TestCase):
    def test_registered_with_the_scene_tools(self):
        self.assertIn("free_sky", scene_tools.TOOLS)
        self.assertEqual(scene_tools.validate("free_texture", {"description": " oak  planks ", "material": "Floor"}),
                         {"description": "oak planks", "material": "Floor"})

    def test_bad_arguments_say_what_to_send(self):
        with self.assertRaises(scene_tools.ToolArgError):
            scene_tools.validate("free_texture", {"description": "oak"})
        with self.assertRaises(scene_tools.ToolArgError):
            scene_tools.validate("free_sky", {"description": "noon", "strength": "bright"})

    def test_sky_strength_is_clamped(self):
        self.assertEqual(scene_tools.validate("free_sky", {"description": "noon", "strength": 99})["strength"],
                         tools.SKY_STRENGTH_MAX)


class Worker(unittest.TestCase):
    def test_downloads_here_and_applies_on_the_main_thread(self):
        calls = []

        def executor(name, args):
            calls.append((name, args))
            return {"ok": True}

        class Haven:
            def __init__(self, *a):
                pass

            def sky(self, description):
                return {"id": "moonless_golf", "name": "Moonless Golf", "path": "/cache/m.hdr"}

        original, fetch.Haven = fetch.Haven, Haven
        try:
            call = tools.on_worker(executor, None, "/cache", None)
            result = call("free_sky", {"description": "night", "strength": 0.3, "rotation_deg": 0.0})
            self.assertEqual(calls[0][0], "apply_free_sky")
            self.assertEqual(calls[0][1]["path"], "/cache/m.hdr")
            self.assertEqual(result["credit"], "Poly Haven, CC0")
            call("read_scene", {})  # every other tool goes straight through
            self.assertEqual(calls[-1][0], "read_scene")
        finally:
            fetch.Haven = original

    def test_a_failure_goes_back_to_the_model(self):
        class Haven:
            def __init__(self, *a):
                pass

            def texture(self, description):
                raise fetch.HavenError("Poly Haven could not be reached; build this look with procedural nodes")

        original, fetch.Haven = fetch.Haven, Haven
        try:
            result = tools.on_worker(lambda n, a: {}, None, "/c", None)("free_texture", {"description": "x",
                                                                                         "material": "M"})
        finally:
            fetch.Haven = original
        self.assertFalse(result["ok"])
        self.assertIn("procedural", result["error"])


if __name__ == "__main__":
    unittest.main()
