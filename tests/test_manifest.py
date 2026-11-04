import os
import tomllib
import unittest

import eachlabs

MANIFEST = os.path.join(os.path.dirname(eachlabs.__file__), "blender_manifest.toml")
BUILD = os.path.join(os.path.dirname(os.path.dirname(MANIFEST)), "scripts", "build.sh")
SKIA_VERSION = "144.1"


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

    def test_skia_wheels_for_every_platform_and_both_pythons(self):
        # Blender 4.2 runs Python 3.11 and 5.2 runs 3.13; scripts/build.sh downloads these files.
        tags = {"macos-arm64": "macosx_11_0_arm64", "macos-x64": "macosx_11_0_x86_64",
                "windows-x64": "win_amd64", "linux-x64": "manylinux_2_28_x86_64"}
        self.assertEqual(self.manifest["platforms"], list(tags))
        expected = ["./wheels/skia_python-%s-%s-%s-%s.whl" % (SKIA_VERSION, py, py, tag)
                    for tag in tags.values() for py in ("cp311", "cp313")]
        self.assertEqual(self.manifest["wheels"], expected)
        with open(BUILD, encoding="utf-8") as handle:
            self.assertIn('SKIA_VERSION="%s"' % SKIA_VERSION, handle.read())
        with open(os.path.join(os.path.dirname(BUILD), "skia-wheels.sha256"), encoding="utf-8") as handle:
            pinned = [line.split() for line in handle if line.strip()]
        self.assertEqual(sorted("./wheels/" + name for _, name in pinned), sorted(expected))
        for digest, _ in pinned:
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_network_permission_names_what_is_sent(self):
        self.assertEqual(self.manifest["permissions"]["network"], "Send renders and prompts to Eachlabs and download results")

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
