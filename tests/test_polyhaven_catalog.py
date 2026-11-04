import unittest

from eachlabs.polyhaven import catalog

ASSETS = {
    "aarfontein_dawn_2": {"name": "Aarfontein Dawn 2", "tags": ["grass", "hilltop"], "categories": ["outdoor"],
                          "attributes": {"time_of_day": "sunrise", "weather": "partly_cloudy"}},
    "moonless_golf": {"name": "Moonless Golf", "tags": ["night", "stars"], "categories": ["outdoor", "night"],
                      "attributes": {"time_of_day": "night", "weather": "clear"}},
    "studio_small_03": {"name": "Studio Small 03", "tags": ["studio"], "categories": ["studio", "indoor"]},
    "../evil": {"name": "night sky night night"},
}


class Pick(unittest.TestCase):
    def test_time_of_day_wins(self):
        self.assertEqual(catalog.best(ASSETS, "clear night sky with stars", names_describe=False)[0], "moonless_golf")
        self.assertEqual(catalog.best(ASSETS, "sunrise over grassy hills", names_describe=False)[0], "aarfontein_dawn_2")

    def test_weak_match_is_none(self):
        self.assertIsNone(catalog.best(ASSETS, "underwater coral reef"))
        self.assertIsNone(catalog.best(ASSETS, "the sky"))  # only stop words

    def test_a_name_about_something_else_loses(self):
        textures = {
            "gravel_stones": {"name": "Gravel Stones", "tags": ["stone", "rough", "natural", "gray"],
                              "categories": ["terrain"]},
            "castle_wall_slates": {"name": "Castle Wall Slates", "tags": ["stone", "wall", "masonry", "gray"],
                                   "categories": ["wall"]},
        }
        self.assertEqual(catalog.best(textures, "rough gray stone wall masonry")[0], "castle_wall_slates")
        self.assertIsNone(catalog.best({"gravel_stones": textures["gravel_stones"]}, "smooth warm limestone blocks"))

    def test_one_shared_word_is_not_a_match(self):
        self.assertIsNone(catalog.best({"red_brick": {"name": "Red Brick", "tags": ["brick", "red"]}},
                                       "red paper lanterns glowing festival market"))

    def test_a_sky_of_sky_alone_wins_a_tie(self):
        skies = {
            "dawn_moor": {"name": "Dawn Moor", "tags": ["dawn", "moor"], "categories": ["outdoor"],
                          "attributes": {"time_of_day": "sunrise"}},
            "dawn_clouds": {"name": "Dawn Clouds", "tags": ["dawn", "clouds"], "categories": ["skies"],
                            "attributes": {"time_of_day": "sunrise"}},
        }
        self.assertEqual(catalog.best(skies, "dawn sunrise", names_describe=False)[0], "dawn_clouds")

    def test_bad_ids_never_picked(self):
        self.assertNotEqual(catalog.best(ASSETS, "night night night", names_describe=False)[0], "../evil")
        with self.assertRaises(ValueError):
            catalog.files_url("../evil")


class Files(unittest.TestCase):
    def test_sky_prefers_2k_hdr(self):
        files = {"hdri": {"1k": {"hdr": {"url": "https://dl/a_1k.hdr", "md5": "x", "size": 1}},
                          "2k": {"hdr": {"url": "https://dl/a_2k.hdr", "md5": "y", "size": 2},
                                 "exr": {"url": "https://dl/a_2k.exr"}}}}
        self.assertEqual(catalog.sky_file(files)["url"], "https://dl/a_2k.hdr")

    def test_texture_maps_and_https_only(self):
        files = {"Diffuse": {"1k": {"jpg": {"url": "https://dl/d.jpg"}}},
                 "Rough": {"1k": {"jpg": {"url": "http://dl/r.jpg"}}},
                 "nor_gl": {"2k": {"jpg": {"url": "https://dl/n.jpg"}}}}
        maps = catalog.texture_files(files)
        self.assertEqual(sorted(maps), ["color", "normal"])  # the http roughness map is left out
        self.assertEqual(catalog.texture_files({"Rough": files["Rough"]}), {})  # no colour map: nothing

    def test_tile_from_millimetres(self):
        self.assertEqual(catalog.tile_m({"dimensions": [2000, 2000]}), 2.0)
        self.assertEqual(catalog.tile_m({"dimensions": [30000, 30000]}), 20.0)
        self.assertEqual(catalog.tile_m({}), catalog.TILE_DEFAULT_M)


if __name__ == "__main__":
    unittest.main()
