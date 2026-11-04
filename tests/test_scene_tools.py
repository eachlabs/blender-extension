import json
import unittest

from eachlabs import chat_loop
from eachlabs import scene_tools as st

NAMES = ("run_python", "read_scene", "camera_view", "blender_api")


class SchemaTest(unittest.TestCase):
    def test_three_tools_and_the_texture_tool(self):
        self.assertEqual(set(st.TOOLS), set(NAMES) | {"generate_texture", "free_texture", "free_sky", "look_at"})
        self.assertEqual(st.BASE_TOOLS, NAMES)
        for name, tool in st.TOOLS.items():
            self.assertEqual(tool["type"], "function")
            fn = tool["function"]
            self.assertEqual(fn["name"], name)
            self.assertTrue(fn["description"].strip())
            self.assertEqual(fn["parameters"]["type"], "object")
        params = st.TOOLS["run_python"]["function"]["parameters"]
        self.assertEqual(params["required"], ["code"])
        self.assertEqual(params["properties"]["code"]["type"], "string")
        for name in ("read_scene", "camera_view"):
            self.assertEqual(st.TOOLS[name]["function"]["parameters"]["properties"], {})

    def test_look_at_arguments(self):
        self.assertEqual(st.validate("look_at", {}), {"object": None, "hide": [], "mode": "solid"})
        self.assertEqual(st.validate("look_at", {"object": " Cabin ", "hide": ["Tree 1"], "mode": "xray"}),
                         {"object": "Cabin", "hide": ["Tree 1"], "mode": "xray"})
        for bad in ({"mode": "wire"}, {"hide": "Tree 1"}, {"object": 3}):
            with self.assertRaises(st.ToolArgError):
                st.validate("look_at", bad)
        self.assertEqual(st.summary("look_at", {"object": "Cabin"}), "look at Cabin from four sides")

    def test_look_at_pictures_go_as_one_message(self):
        from eachlabs.chat import pictures
        message = pictures.around_message(["data:a", "data:b"], ["from 35 degrees around, 20 up"])
        self.assertTrue(message["look"])
        kinds = [p["type"] for p in message["content"]]
        self.assertEqual(kinds, ["text", "text", "image_url", "image_url"])
        self.assertEqual(chat_loop.LOOK_TOOLS["check"], ("look_at",))

    def test_every_stage_gets_the_three_tools(self):
        self.assertEqual(set(chat_loop.STAGE_TOOLS), set(chat_loop.STAGES) | {chat_loop.COMPLETE, chat_loop.EDIT,
                                                                               chat_loop.FIX})
        for stage in chat_loop.STAGES:
            self.assertEqual(set(chat_loop.STAGE_TOOLS[stage]), set(NAMES), stage)

    def test_generate_texture_arguments(self):
        self.assertEqual(st.validate("generate_texture", {"description": "  red   brick ", "material": "Wall "}),
                         {"description": "red brick", "material": "Wall", "tile_m": 1.0})
        self.assertEqual(st.validate("generate_texture", {"description": "oak", "material": "Floor", "tile_m": 2})
                         ["tile_m"], 2.0)
        for bad in ({"material": "Wall"}, {"description": "brick"}, {"description": "brick", "material": "W",
                                                                      "tile_m": "big"},
                    {"description": "brick", "material": "W", "tile_m": 500}):
            with self.assertRaises(st.ToolArgError):
                st.validate("generate_texture", bad)
        self.assertEqual(st.summary("generate_texture", {"description": "red brick"}), "texture: red brick")

    def test_run_python_description_names_the_allowed_imports(self):
        text = st.TOOLS["run_python"]["function"]["description"]
        for module in ("bpy", "bmesh", "mathutils", "math", "random"):
            self.assertIn(module, text)


class ValidateTest(unittest.TestCase):
    def test_run_python_needs_code(self):
        self.assertEqual(st.validate("run_python", {"code": "x = 1"}), {"code": "x = 1"})
        for bad in ({}, {"code": ""}, {"code": "   \n"}, {"code": 3}):
            with self.assertRaises(st.ToolArgError) as cm:
                st.validate("run_python", bad)
            self.assertIn("code is required", str(cm.exception))

    def test_reading_tools_take_nothing(self):
        self.assertEqual(st.validate("read_scene", {}), {})
        self.assertEqual(st.validate("camera_view", {}), {})
        with self.assertRaises(st.ToolArgError) as cm:
            st.validate("camera_view", {"frame": 3})
        self.assertIn("unknown argument frame", str(cm.exception))

    def test_unknown_tool_lists_the_three(self):
        with self.assertRaises(st.ToolArgError) as cm:
            st.validate("add_box", {})
        self.assertEqual(str(cm.exception), "add_box is not a tool; use run_python, read_scene, camera_view or blender_api")

    def test_arguments_must_be_an_object(self):
        with self.assertRaises(st.ToolArgError):
            st.validate("run_python", ["x = 1"])


class LabelTest(unittest.TestCase):
    def test_first_comment(self):
        self.assertEqual(st.first_comment("\n#  Ground and   two boxes\nx = 1"), "Ground and two boxes")
        self.assertEqual(st.first_comment("x = 1\n# later"), "")
        self.assertEqual(st.first_comment(""), "")

    def test_summary(self):
        self.assertEqual(st.summary("run_python", {"code": "# Street lamps\nx = 1"}), "Street lamps")
        self.assertEqual(st.summary("run_python", {"code": "x = 1\ny = 2\n\nz = 3"}), "run code · 3 lines")
        self.assertEqual(st.summary("run_python", {"code": "x = 1"}), "run code · 1 line")
        self.assertEqual(st.summary("read_scene", {}), "read the scene")
        self.assertEqual(st.summary("camera_view", {}), "check the camera view")
        long = st.summary("run_python", {"code": "# " + "a very long comment " * 10})
        self.assertEqual(len(long), 48)
        self.assertTrue(long.endswith("…"))
        for name in NAMES:
            self.assertLessEqual(len(st.summary(name, None)), 48)


def part(name, low=None, high=None, parent=None):
    return {"name": name, "parent": parent, "box": (low, high) if low is not None else None}


# A waving figure as a follow-up built it: the arm, forearm, hand and bubble were parented to the empty with
# world locations, so they sit at twice its offset; the two letters have no parent.
FIGURE = [
    part("Person_A"),
    part("Person_A_Torso", (-6.71, 3.28, 0.95), (-6.29, 3.52, 1.5), "Person_A"),
    part("Person_A_Hips", (-6.68, 3.29, 0.81), (-6.32, 3.51, 1.03), "Person_A"),
    part("Person_A_Head", (-6.6, 3.3, 1.54), (-6.4, 3.51, 1.78), "Person_A"),
    part("Person_A_Neck", (-6.56, 3.34, 1.5), (-6.44, 3.46, 1.58), "Person_A"),
    part("Person_A_LegL", (-6.68, 3.32, 0.07), (-6.54, 3.49, 0.89), "Person_A"),
    part("Person_A_ShoeL", (-6.68, 3.32, 0.0), (-6.54, 3.58, 0.1), "Person_A"),
    part("Person_A_ArmUp_R", (-12.86, 6.74, 1.22), (-12.58, 6.87, 1.62), "Person_A"),
    part("Person_A_Fore_R", (-12.66, 6.75, 1.53), (-12.46, 6.86, 1.91), "Person_A"),
    part("Person_A_Hand_R", (-12.55, 6.75, 1.86), (-12.41, 6.86, 2.02), "Person_A"),
    part("Person_A_Bubble", (-12.96, 6.53, 1.96), (-12.2, 6.97, 2.6), "Person_A"),
    part("Person_A_BubbleText_H", (-6.26, 3.55, 2.21), (-6.09, 3.57, 2.35)),
    part("Person_A_BubbleText_I", (-6.01, 3.55, 2.21), (-5.95, 3.57, 2.35)),
]


class LoosePartsTest(unittest.TestCase):
    def test_a_figure_whose_arm_floats_off_is_listed_with_the_parts_apart(self):
        loose = st.loose_parts(FIGURE)
        self.assertEqual(len(loose), 1)
        group = loose[0]
        self.assertEqual(group["parts_of"], "Person_A and its children")
        self.assertEqual(group["parts"], 12)  # the empty has no geometry; the letters join by name
        self.assertEqual(group["pieces"], 4)  # the body, the far arm and bubble, and each letter over the head
        self.assertEqual(group["apart"], ["Person_A_ArmUp_R", "Person_A_Bubble", "Person_A_BubbleText_H",
                                          "Person_A_BubbleText_I", "Person_A_Fore_R", "Person_A_Hand_R"])

    def test_parts_that_touch_are_not_listed(self):
        whole = [p for p in FIGURE if "Arm" not in p["name"] and "Fore" not in p["name"]
                 and "Hand" not in p["name"] and "Bubble" not in p["name"]]
        self.assertEqual(st.loose_parts(whole), [])
        house = [part("House_Walls", (0, 0, 0), (10, 8, 6)), part("House_Roof", (0, 0, 6.02), (10, 8, 9)),
                 part("House_Chimney", (7, 5, 8), (8, 6, 10)), part("House_Chimney_Cap", (6.9, 4.9, 10), (8.1, 6.1, 10.2))]
        self.assertEqual(st.loose_parts(house), [])

    def test_name_groups_without_a_parent(self):
        lamp = [part("Lamp_Pole", (0, 0, 0), (0.2, 0.2, 5)), part("Lamp_Arm", (0, 0, 4.8), (1.5, 0.2, 5)),
                part("Lamp_Head", (3, 0, 4.5), (3.4, 0.3, 4.8))]
        self.assertEqual(st.loose_parts(lamp), [{"parts_of": "Lamp_*", "parts": 3, "pieces": 2,
                                                 "apart": ["Lamp_Head"]}])

    def test_repeats_and_sides_are_not_one_object(self):
        far = [part("Window_%02d" % i, (i * 4, 0, 1), (i * 4 + 1, 0.1, 2)) for i in range(6)]
        trees = [part("Tree_%s_%s" % (side, kind), (x, 0, z0), (x + 1, 1, z1))
                 for side, x in (("L", -20), ("R", 20)) for kind, z0, z1 in (("Trunk", 0, 3), ("Crown", 3, 6))]
        self.assertEqual(st.loose_parts(far + trees), [])
        tyres = [part("Car_Tyre_%d" % i, (x, y, 0), (x + 0.6, y + 0.2, 0.6))
                 for i, (x, y) in enumerate(((-1.5, -1), (1.5, -1), (-1.5, 1), (1.5, 1)))]
        self.assertEqual(st.loose_parts(tyres), [])  # copies by a last number are apart by design

    def test_the_check_stage_is_told_which_parts_float(self):
        scene = '{"loose_parts": %s}' % __import__("json").dumps(st.loose_parts(FIGURE))
        problems = chat_loop.loose_problems(scene)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("Parts of Person_A and its children float apart: 12 parts in 4 "
                                               "pieces; apart from the rest: Person_A_ArmUp_R"), problems[0])
        self.assertEqual(chat_loop.loose_problems('{"objects": []}'), [])
        self.assertEqual(chat_loop.loose_problems("ERROR: gone"), [])
        self.assertIn("parts of one figure or object float apart", chat_loop.INSTRUCTIONS["check"])
        self.assertIn("attach(part, root)", chat_loop.INSTRUCTIONS["layout"])


def person(name, x, y, z=0.0):
    """A three-part person of 1.75 m with its feet at height z."""
    return [part(name + "_Legs", (x - 0.2, y - 0.1, z), (x + 0.2, y + 0.1, z + 0.9)),
            part(name + "_Body", (x - 0.25, y - 0.15, z + 0.9), (x + 0.25, y + 0.15, z + 1.5)),
            part(name + "_Head", (x - 0.12, y - 0.12, z + 1.5), (x + 0.12, y + 0.12, z + 1.75))]


CAR = [part("Car_Body", (-2.2, -0.9, 0.3), (2.2, 0.9, 1.1)), part("Car_Roof", (-1.2, -0.8, 1.1), (1.0, 0.8, 1.5)),
       part("Car_Bumper", (2.2, -0.9, 0.3), (2.4, 0.9, 0.6)),
       part("Car_Wheel_1", (-1.8, -1.0, 0.0), (-1.2, -0.8, 0.6)), part("Car_Wheel_2", (1.2, -1.0, 0.0), (1.8, -0.8, 0.6))]


class OverlapsTest(unittest.TestCase):
    def test_a_person_on_the_car_roof_is_listed(self):
        found = st.overlaps(CAR + person("Person_A", 0.0, 0.0, 1.5))
        self.assertEqual(found, [{"thing": "Person_A_*", "on": "Car_*", "part": "Car_Roof"}])
        problems = chat_loop.overlap_problems('{"overlaps": %s}' % __import__("json").dumps(found))
        self.assertEqual(problems, ["Person_A_* stands on top of Car_* (Car_Roof). Unless it belongs there, like "
                                    "a lamp on a table, move it down to the ground beside it."])

    def test_a_person_beside_the_car_or_on_a_kerb_is_not_listed(self):
        kerb = [part("Sidewalk", (-10, 2, 0), (10, 5, 0.15)), part("Road", (-10, -2, -0.01), (10, 2, 0))]
        self.assertEqual(st.overlaps(CAR + kerb + person("Person_A", 0.0, 1.4) + person("Person_B", 3, 3, 0.15)), [])

    def test_a_person_walking_through_a_solid_block_is_listed_as_inside(self):
        found = st.overlaps([part("Building_3", (0, 0, 0), (10, 8, 9))] + person("Person_A", 5, 4))
        self.assertEqual(found, [{"thing": "Person_A_*", "inside": "Building_3"}])
        self.assertTrue(chat_loop.overlap_problems('{"overlaps": %s}' % __import__("json").dumps(found))[0]
                        .startswith("Person_A_* is inside Building_3. Unless"))

    def test_a_car_in_a_garage_of_thin_walls_and_a_lamp_on_a_table_are_not_listed(self):
        garage = [part("Garage_WallL", (-3, -3, 0), (-2.8, 3, 2.6)), part("Garage_WallR", (2.8, -3, 0), (3, 3, 2.6)),
                  part("Garage_WallB", (-3, 2.8, 0), (3, 3, 2.6)), part("Garage_Roof", (-3, -3, 2.6), (3, 3, 2.8))]
        table = [part("Table_Top", (5, 5, 0.7), (6, 6, 0.75)), part("Table_Lamp", (5.4, 5.4, 0.75), (5.6, 5.6, 1.2))]
        self.assertEqual(st.overlaps(CAR + garage + table), [])

    def test_parts_named_inside_one_thing_and_children_are_one_thing(self):
        antenna = part("Car_Antenna_1", (0.0, 0.0, 0.5), (0.05, 0.05, 2.0))  # named after the car: one thing
        self.assertEqual(st.overlaps(CAR + [antenna]), [])
        root = part("Rig", (0, 0, 0), (0, 0, 0))
        root["box"] = None
        kid = part("Kid", (-0.2, -0.1, 0.0), (0.2, 0.1, 1.2), "Rig")
        seat = part("Seat", (-0.3, -0.3, 0.0), (0.3, 0.3, 0.45), "Rig")
        self.assertEqual(st.overlaps([root, kid, seat]), [])  # one parent: one thing

    def test_names_with_spaces_a_low_plinth_and_a_window_in_a_wall_are_not_listed(self):
        # Shapes and names from a real GPT-6 Sol run, where each of these was listed before.
        scene = [part("House | two floor main structure", (0, 0, 0), (10, 8, 6)),
                 part("House | pitched gabled roof", (-0.5, -0.5, 6), (10.5, 8.5, 9)),
                 part("Street foundation", (-40, -10, 0), (40, 10, 0.3)),
                 part("West block 0 building", (-30, 4, 0.3), (-20, 10, 12)),
                 part("Left side wall", (-5, 20, 0), (-4.8, 26, 3)),
                 part("Window night opening", (-5.05, 22, 1), (-4.75, 24, 2.4)),
                 part("Indoor plant tapered ceramic planter", (3, 22, 0), (3.6, 22.6, 0.6)),
                 part("Indoor plant branch trunk", (3.2, 22.2, 0.55), (3.4, 22.4, 1.9))]
        self.assertEqual(st.overlaps(scene), [])
        on_car = st.overlaps(CAR + person("Walker one", 0.0, 0.0, 1.5))
        self.assertEqual([(o["on"], o.get("part")) for o in on_car], [("Car_*", "Car_Roof")])  # names with spaces

    def test_a_window_set_into_a_wall_opening_is_not_on_the_wall(self):
        wall = [part("Room"), part("Room / wall under window", (0, 0, 0), (1.2, 0.2, 1.0), "Room"),
                part("Room / wall left", (-2, 0, 0), (0, 0.2, 3.0), "Room"),
                part("Room / wall over window", (0, 0, 2.2), (1.2, 0.2, 3.0), "Room")]
        window = [part("Window"), part("Window / frame", (0, 0, 1.0), (1.2, 0.2, 2.2), "Window"),
                  part("Window / pane", (0.1, 0.09, 1.1), (1.1, 0.11, 2.1), "Window"),
                  part("Window / sill", (0, 0, 1.0), (1.2, 0.2, 1.05), "Window")]
        self.assertEqual(st.overlaps(wall + window), [])
        found = st.overlaps(wall[:3] + window)  # with nothing of the wall over it, it stands on top
        self.assertEqual([(o["on"], o.get("part")) for o in found],
                         [("Room and its children", "Room / wall under window")])

    def test_no_overlaps_in_the_figure_and_the_list_is_capped(self):
        self.assertEqual(st.overlaps(FIGURE), [])
        crowd = [p for i in range(20) for p in person("Person_%d" % i, i * 2.0, 0.0, 9.0)]
        found = st.overlaps([part("Building_1", (-5, -5, 0), (45, 5, 9))] + crowd)
        self.assertEqual(len(found), st.OVERLAP_MAX)
        self.assertTrue(all(o["on"] == "Building_1" for o in found))

    def test_ground_is_stood_on_not_stood_in(self):
        parts = [{"name": "Valley ground", "parent": None, "box": ([-250, -250, -1.2], [250, 250, 0.1])},
                 {"name": "Mountain", "parent": None, "box": ([-40, -40, -1.0], [40, 40, 60])}]
        self.assertEqual(st.overlaps(parts), [])

    def test_the_check_stage_lists_overlaps_as_clearly_wrong(self):
        self.assertIn("an object stands on or inside another one where it should not (a person on a car roof",
                      chat_loop.INSTRUCTIONS["check"])
        self.assertIn("Never set a thing's location yourself", chat_loop.INSTRUCTIONS["layout"])
        self.assertEqual(chat_loop.overlap_problems("ERROR: gone"), [])
        self.assertEqual(chat_loop.overlap_problems('{"objects": []}'), [])


def fp(name, low, high):
    return {"name": name, "parent": None, "box": (list(low), list(high))}


class FreeSpaceTest(unittest.TestCase):
    def test_the_biggest_empty_rectangles_on_the_ground(self):
        # A 40 x 20 ground: a row of houses along the back (y 12..20) and a car at the front left.
        houses = [(x, 12, x + 8, 20) for x in (0, 10, 20, 30)]
        areas = st.free_areas((0, 0, 40, 20), houses + [(0, 0, 5, 3)])
        self.assertEqual(len(areas), 3)
        biggest = areas[0]
        self.assertEqual(biggest["turn"], 0)
        self.assertGreaterEqual(biggest["size"][0] * biggest["size"][1], 35 * 12 * 0.9)  # the open front
        self.assertTrue(0 <= biggest["centre"][1] <= 12)
        sizes = [a["size"][0] * a["size"][1] for a in areas]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertTrue(st.fits(areas, [10, 30]) and not st.fits(areas, [12, 30]) and not st.fits(areas, [5, 40]))
        self.assertTrue(st.fits(areas, [10, 8]) and st.fits(areas, [8, 10]))

    def test_a_full_ground_has_no_free_area(self):
        self.assertEqual(st.free_areas((0, 0, 10, 10), [(-1, -1, 11, 11)]), [])
        self.assertEqual(st.free_areas((0, 0, 0, 10), []), [])

    def test_a_new_thing_through_an_existing_one_is_listed(self):
        parts = [fp("Church", (4, 4, 0), (14, 24, 18)), fp("House_A", (0, 0, 0), (8, 8, 7)),
                 fp("House_B", (30, 0, 0), (38, 8, 7)), fp("Bench", (40, 40, 0), (42, 41, 0.9))]
        found = st.overlaps(parts, existing={"House_A", "House_B", "Bench"})
        self.assertIn({"thing": "Church", "overlaps_existing": "House_A", "size": [10, 20]}, found)
        self.assertFalse(any(e.get("thing") == "House_A" and "overlaps_existing" in e for e in found))
        self.assertEqual([e for e in st.overlaps(parts) if "overlaps_existing" in e], [])  # first prompt: nothing
        moved = [fp("Church", (12, 12, 0), (22, 32, 18))] + parts[1:]
        self.assertEqual([e for e in st.overlaps(moved, {"House_A", "House_B", "Bench"})
                          if "overlaps_existing" in e], [])

    def test_the_check_stage_is_told_to_move_it(self):
        scene = json.dumps({"overlaps": [{"thing": "Church", "overlaps_existing": "House_A", "size": [10, 20]},
                                         {"thing": "Tower", "overlaps_existing": "House_B", "size": [30, 30],
                                          "note": "no free area fits 30 x 30 m; extend the ground"}]})
        church, tower = chat_loop.overlap_problems(scene)
        self.assertIn("Church is new and stands through House_A, which was there before. Move it into free space",
                      church)
        self.assertIn("Move or remove House_A only if the request asked for that", church)
        self.assertIn("extend the ground at its edge with a new block or lawn, place it there, and say so", tower)
        self.assertIn("free_space in read_scene", chat_loop.FOLLOW_UP_INSTRUCTIONS["layout"])
        self.assertIn("overlaps_existing", chat_loop.INSTRUCTIONS["check"])


if __name__ == "__main__":
    unittest.main()
