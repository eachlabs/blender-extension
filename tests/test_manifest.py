import os
import tomllib
import unittest

import eachlabs

MANIFEST = os.path.join(os.path.dirname(eachlabs.__file__), "blender_manifest.toml")


class ManifestTest(unittest.TestCase):
    def setUp(self):
        with open(MANIFEST, "rb") as handle:
            self.manifest = tomllib.load(handle)

    def test_version_matches_package(self):
        self.assertEqual(self.manifest["version"], eachlabs.VERSION)

    def test_extension_platform_rules(self):
        m = self.manifest
        self.assertEqual(m["type"], "add-on")
        self.assertEqual(m["blender_version_min"], "4.2.0")
        self.assertLessEqual(len(m["tagline"]), 64)
        self.assertFalse(m["tagline"][-1] in ".!?")
        for reason in m["permissions"].values():
            self.assertLessEqual(len(reason), 64)
            self.assertFalse(reason[-1] in ".!?")
        self.assertEqual(set(m["permissions"]), {"network", "files"})
        self.assertNotIn("wheels", m)

    def test_gpl_license_ships_in_the_package(self):
        self.assertEqual(self.manifest["license"], ["SPDX:GPL-3.0-or-later"])
        root = os.path.dirname(os.path.dirname(MANIFEST))
        with open(os.path.join(root, "LICENSE"), encoding="utf-8") as a, \
                open(os.path.join(os.path.dirname(MANIFEST), "LICENSE"), encoding="utf-8") as b:
            text = a.read()
            self.assertEqual(text, b.read())
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text)
        self.assertIn("Version 3, 29 June 2007", text)


if __name__ == "__main__":
    unittest.main()
