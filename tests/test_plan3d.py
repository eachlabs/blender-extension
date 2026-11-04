import json
import unittest

from eachlabs import plan3d

ANSWER = json.dumps({"objects_3d": [
    {"name": "car", "description": "red 1970s muscle car", "tier": "large"},
    {"name": "tree", "description": "leafy oak tree", "tier": "medium"},
    {"name": "street lamp", "description": "black iron street lamp", "tier": "medium"},
    {"name": "coin", "description": "a coin", "tier": "tiny"}],
    "code": ["road", "sidewalks", "buildings", "Road"]})


class ParseTest(unittest.TestCase):
    def test_items_tiers_and_order(self):
        plan = plan3d.parse(ANSWER, 4)
        self.assertEqual([(i.name, i.mode, i.tier) for i in plan.items],
                         [("car", "3d", "large"), ("tree", "3d", "medium"), ("street lamp", "3d", "medium"),
                          ("coin", "code", "medium"), ("road", "code", "medium"), ("sidewalks", "code", "medium"),
                          ("buildings", "code", "medium")])
        self.assertEqual(plan.items[0].description, "red 1970s muscle car")

    def test_the_limit_moves_the_rest_to_code(self):
        plan = plan3d.parse(ANSWER, 2)
        self.assertEqual([i.name for i in plan.three_d], ["car", "tree"])
        self.assertEqual(plan.items[2].mode, "code")

    def test_a_fenced_answer_and_no_answer(self):
        self.assertEqual(len(plan3d.parse("Here:\n```json\n%s\n```" % ANSWER, 4).three_d), 3)
        self.assertIsNone(plan3d.parse("I cannot plan this.", 4))
        self.assertEqual(plan3d.parse('{"objects_3d": [], "code": ["room"]}', 4).three_d, [])

    def test_cached_items(self):
        plan = plan3d.parse(ANSWER, 4, cached=lambda d, t: d == "leafy oak tree" and t == "medium")
        self.assertEqual([i.cached for i in plan.three_d], [False, True, False])


class PlanTest(unittest.TestCase):
    def test_summary_lines(self):
        plan = plan3d.parse(ANSWER, 4)
        # Made one at a time: 205 + 170 + 170 s.
        self.assertEqual(plan.summary_3d(), "3D: car, tree, street lamp · 3 × $0.45 = $1.35 · about 9 min one by one")
        self.assertEqual(plan.summary_code(), "Code: coin, road, sidewalks, buildings")
        self.assertEqual(plan.cost(), 1.35)

    def test_cached_items_are_free(self):
        plan = plan3d.parse(ANSWER, 4, cached=lambda d, t: d == "leafy oak tree")
        self.assertEqual(plan.summary_3d(), "3D: car, tree, street lamp · 2 × $0.45 = $0.90 · 1 cached, free · "
                                            "about 6 min one by one")
        self.assertEqual(plan.cost(), 0.9)
        everything = plan3d.parse(ANSWER, 4, cached=lambda d, t: True)
        self.assertEqual(everything.summary_3d(), "3D: car, tree, street lamp · 3 cached, free")

    def test_the_limit_is_for_the_chats_suggestions_only(self):
        plan = plan3d.parse(ANSWER, 2)
        self.assertEqual([i.name for i in plan.three_d], ["car", "tree"])
        self.assertEqual(plan3d.Plan().limit, 2)
        self.assertTrue(plan.toggle(2))  # the person moves the lamp, a piece the chat offered in 3D, past the limit
        for index in (4, 5, 6):  # the road, the sidewalks and the buildings have parts: they stay in code
            self.assertFalse(plan.toggle(index))
        self.assertEqual([i.name for i in plan.three_d], ["car", "tree", "street lamp"])
        self.assertTrue(plan.items[2].chosen)
        self.assertTrue(plan.toggle(0))
        self.assertEqual(plan.items[0].mode, "code")
        self.assertFalse(plan.toggle(99))

    def test_every_approved_item_is_queued_largest_first(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [
            {"name": "sports car", "description": "red sports car", "tier": "large"},
            {"name": "trees", "description": "oak trees", "tier": "medium"}],
            "code": [{"name": "boulder", "solid": True}, {"name": "statue", "solid": True}, "road"]}), 2)
        plan.toggle(2)
        plan.toggle(3)  # the person moves the boulder and the statue to 3D, past the chat's limit of 2
        queue = plan.queue()
        self.assertEqual(len(queue), 4)
        self.assertEqual([i.name for i in queue], ["sports car", "trees", "boulder", "statue"])
        plan.items[2].tier = "large"
        self.assertEqual([i.name for i in plan.queue()], ["sports car", "boulder", "trees", "statue"])

    def test_code_versions_are_found_by_the_items_name(self):
        for name in ("Sports car", "Sports_car", "sports car 2", "Sports car.001", "SPORTS-CAR_3"):
            self.assertTrue(plan3d.names_item(name, "sports car"), name)
        for name in ("Sports car wheel", "Car", "Sports", ""):
            self.assertFalse(plan3d.names_item(name, "sports car"), name)
        self.assertTrue(plan3d.names_item("Tree 4", "trees"))
        self.assertTrue(plan3d.names_item("Trees_1", "tree"))
        self.assertEqual((plan3d.root_name("trees"), plan3d.root_name("trees", 2)), ("Trees", "Trees 2"))

    def test_the_chats_picture_prompt_and_size_per_item(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [
            {"name": "trees", "description": "oak trees", "tier": "medium",
             "picture_prompt": "a mature oak tree, the whole tree from roots to crown, full size, no pot",
             "size_m": 9, "measure": "height"},
            {"name": "car", "description": "red car", "size_m": "big"}],
            "code": [{"name": "house", "picture_prompt": "a two-floor house", "size_m": 8, "measure": "height"},
                     "road"]}), 2)
        trees, car, house, road = plan.items
        self.assertEqual((trees.picture_prompt, trees.size_m, trees.measure),
                         ("a mature oak tree, the whole tree from roots to crown, full size, no pot", 9.0, "height"))
        self.assertEqual((car.picture_prompt, car.size_m), ("", None))  # no size: the code version's size
        self.assertEqual((house.size_m, house.mode, road.size_m), (8.0, "code", None))
        self.assertIn('- "Trees" (copies "Trees 1", "Trees 2"…): oak trees, 9 m tall', plan.brief())
        text = plan3d.system(2)
        self.assertIn("picture_prompt: how to draw that one object", text)
        self.assertIn("no pot, base or pedestal unless it belongs to the object", text)
        self.assertIn("real-world size in metres", text)

    def test_a_name_joined_with_and_is_two_things(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [], "code": ["church and hall", "villagers and guards",
                                                                  "salt, pepper"]}), 2)
        names = ["Village church", "Town hall clock tower", "Villager 1", "Salt cellar", "Pepper mill"]
        self.assertEqual([i.name for i in plan3d.missing(plan, names)], ["villagers and guards"])
        self.assertEqual(plan3d.missing(plan, names + ["Gate guard 2"]), [])

    def test_the_plan_lists_every_thing_and_the_people_a_place_implies(self):
        text = plan3d.system(2)
        self.assertIn("every thing the request names, each once, at most %d" % plan3d.CODE_MAX, text)
        self.assertIn("never one name joined with \"and\"", text)
        self.assertIn("the people who live in a camp", text)

    def test_missing_items(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [
            {"name": "sports car", "description": "red sports car"}, {"name": "house", "description": "house"}],
            "code": ["road", "sidewalks", "garage"]}), 2)
        names = ["Sports car", "Sports car wheel", "Road_asphalt", "Sidewalk_left", "Two_floor_house"]
        missing = plan3d.missing(plan, names)
        self.assertEqual([i.name for i in missing], ["house", "garage"])  # the house is not under its exact name
        self.assertEqual([i.name for i in plan3d.missing(plan, names, done={"house"})], ["garage"])
        self.assertEqual(plan3d.missing_text(missing[0]),
                         '"House" (the code version of a 3D object: one root object named exactly "House")')
        self.assertEqual(plan3d.missing_text(missing[1]), "garage (named after it)")

    def test_a_thing_mounted_on_another_names_its_owner(self):
        plan = plan3d.parse(json.dumps({"code": [{"name": "shop"}, {"name": "shop sign", "part_of": "Shop"}]}), 2)
        self.assertEqual([i.part_of for i in plan.items], ["", "shop"])
        self.assertIn("shop sign belongs to the shop", plan.brief())
        self.assertIn("\"part_of\": the owner's entry name", plan3d.system(2))

    def test_contents_count_only_on_their_holder(self):
        plan = plan3d.parse(json.dumps({"code": [{"name": "workbench"}, {"name": "tools", "on": "Workbench"},
                                                 {"name": "flowers", "in": "vase"}]}), 2)
        self.assertEqual([i.holder for i in plan.items], ["", "workbench", "vase"])
        names = ["Workbench", "Tools_hammer", "Flowers"]
        self.assertEqual([i.name for i in plan3d.missing(plan, names)], [])  # no placement check given
        on = {("tools", "workbench"): False, ("flowers", "vase"): True}
        missing = plan3d.missing(plan, names, placed=lambda item, holder: on[(item, holder)])
        self.assertEqual([i.name for i in missing], ["tools"])  # built, but not on the workbench
        self.assertEqual(plan3d.missing_text(missing[0]), "tools (named after it, on or in the workbench)")
        self.assertIn("\"on\": the holder's entry name", plan3d.system(2))

    def test_only_solid_pieces_move_to_3d(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [], "code": [
            {"name": "car", "detail": "high"}, {"name": "boulder", "solid": True, "detail": "medium"},
            {"name": "road", "detail": "low"}]}), 2)
        self.assertEqual([i.name for i in plan.movable], ["boulder"])
        self.assertFalse(plan.toggle(0))  # the car has parts: it stays in code
        self.assertEqual(plan.items[0].mode, "code")
        self.assertTrue(plan.toggle(1))
        self.assertEqual([i.name for i in plan.three_d], ["boulder"])
        self.assertEqual([i.detail for i in plan.items], ["high", "medium", "low"])

    def test_references_are_the_high_detail_code_items(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [{"name": "statue", "description": "statue"}], "code": [
            {"name": "car", "detail": "high"}, {"name": "church", "detail": "high"}, {"name": "tree"},
            {"name": "road", "detail": "low"}]}), 2)
        self.assertEqual([i.name for i in plan.references()], ["car", "church"])
        self.assertEqual([i.name for i in plan.references(1)], ["car"])
        self.assertEqual(plan3d.looks_text(False, 0, 0.15, ["car", "church"], 0.034), "References: car, church · $0.07")
        self.assertEqual(plan3d.looks_text(True, 0, 0.15, ["car"], 0.034),
                         "Looks: a concept picture · $0.15. References: car · $0.03")

    def test_a_plan_asks_only_when_there_is_something_to_decide(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [], "code": [{"name": "car", "detail": "high"}]}), 2)
        self.assertFalse(plan.asks())
        plan.looks = "References: car · $0.03"
        self.assertTrue(plan.asks())
        plan = plan3d.parse(json.dumps({"objects_3d": [], "code": [{"name": "rock", "solid": True}]}), 2)
        self.assertTrue(plan.asks())

    def test_realistic_words_bind_solid_pieces_only(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [], "code": [
            {"name": "car"}, {"name": "statue", "solid": True}]}), 2)
        moved = plan3d.bind(plan, "a realistic car next to a realistic statue")
        self.assertEqual([i.name for i in moved], ["statue"])
        self.assertEqual(plan.items[0].mode, "code")
        self.assertEqual(plan.items[0].detail, "high")  # the car gets high detail instead

    def test_an_object_with_parts_is_never_upgraded_to_3d(self):
        plan = plan3d.parse(json.dumps({"objects_3d": [], "code": [{"name": "church"}]}), 2)
        self.assertIsNone(plan3d.upgrade(plan, "church", ["Church"], (10, 20, 30)))
        self.assertIsNone(plan3d.upgrade(plan3d.Plan(), "tower", ["Tower"], (2, 2, 9)))
        self.assertEqual(plan.three_d, [])

    def test_nothing_in_3d(self):
        plan = plan3d.parse('{"objects_3d": [{"name": "car", "description": "car"}], "code": []}', 4)
        plan.toggle(0)
        self.assertEqual(plan.summary_3d(), "")
        self.assertEqual(plan.minutes(), 0)

    def test_brief(self):
        plan = plan3d.parse(ANSWER, 4)
        plan.toggle(2)
        brief = plan.brief()
        self.assertIn('- "Car" (copies "Car 1", "Car 2"…): red 1970s muscle car', brief)
        self.assertNotIn('"Street lamp"', brief)
        self.assertIn("named after them: street lamp, coin, road", brief)

    def test_instructions(self):
        text = plan3d.system(3)
        self.assertIn("At most 3 entries.", text)
        self.assertIn("never generate a building, a vehicle, furniture", text)
        self.assertIn("when the request says no 3D, objects_3d is empty", text)
        self.assertIn("detail: high for the subject", text)
        follow = plan3d.system(2, True, ["red 1970s muscle car"])
        self.assertIn("list only the objects this change adds", follow)
        self.assertIn("already has these generated 3D objects: red 1970s muscle car", follow)
        self.assertEqual(plan3d.request("add a tree", ["a street"]),
                         "Request: add a tree\nEarlier requests for this scene, most recent first (context only):\n"
                         "- a street")


class FollowUpPlanTest(unittest.TestCase):
    CARS_IN_CODE = json.dumps({"objects_3d": [], "code": [{"name": "sports cars", "description": "red sports cars"},
                                                          "parking marks"], "adds_objects": True})
    STATUES_IN_CODE = json.dumps({"objects_3d": [], "code": [
        {"name": "statues", "description": "marble statues", "solid": True}, "parking marks"], "adds_objects": True})

    def test_the_persons_words_put_a_solid_piece_in_3d(self):
        plan = plan3d.parse(self.STATUES_IN_CODE, 0)  # the chat suggested nothing, and has no suggestions left
        moved = plan3d.bind(plan, "add two hyper-realistic marble statues by the curb")
        self.assertEqual([i.name for i in moved], ["statues"])
        self.assertEqual((plan.items[0].mode, plan.items[0].chosen, plan.items[0].tier), ("3d", True, "medium"))
        self.assertEqual(plan.items[1].mode, "code")
        self.assertEqual(plan.summary_3d(), "3D: statues · 1 × $0.45 = $0.45 · about 3 min one by one")
        cars = plan3d.parse(self.CARS_IN_CODE, 0)
        self.assertEqual(plan3d.bind(cars, "add two hyper-realistic red sports cars by the curb"), [])
        self.assertEqual((cars.items[0].mode, cars.items[0].detail), ("code", "high"))

    def test_without_those_words_nothing_moves(self):
        plan = plan3d.parse(self.CARS_IN_CODE, 0)
        self.assertEqual(plan3d.bind(plan, "add a red sports car by the curb"), [])
        self.assertEqual(plan.three_d, [])
        self.assertTrue(plan.adds_objects)  # still shown, so the person can move it themselves

    def test_the_words_count_only_next_to_the_item(self):
        for prompt, real in (("replace the car with two realistic red sports cars", True),
                             ("add sports cars in 3D", True),
                             ("add sports cars, generated in 3D", True),
                             ("add sports cars and a real fountain", False),  # "real" is for the fountain
                             ("make the house realistic and add sports cars", False),
                             ("add photoreal sports cars", True)):
            self.assertEqual(plan3d.asked_real(prompt, "sports cars"), real, prompt)

    def test_upgrading_an_existing_object_in_place(self):
        self.assertTrue(plan3d.asks_real("make this hyper-realistic"))
        self.assertTrue(plan3d.asks_real("make the red sports car a 3D model"))
        self.assertFalse(plan3d.asks_real("make the red sports car blue"))
        plan = plan3d.parse('{"objects_3d": [], "code": [{"name": "stone lion", "solid": true}], '
                            '"adds_objects": false}', 2)
        item = plan3d.upgrade(plan, "stone lion", ["Stone_lion"], (1.9, 4.6, 1.3))
        self.assertEqual((item.name, item.mode, item.chosen, item.targets), ("stone lion", "3d", True,
                                                                             ["Stone_lion"]))
        self.assertEqual((item.size_m, item.measure), (4.6, "length"))  # the size of what is there
        self.assertTrue(plan.adds_objects)  # so the plan is shown
        self.assertIn("stone lion: already in the scene as Stone_lion; keep it as it is", plan.brief())
        self.assertEqual(plan3d.missing(plan, ["Stone_lion"]), [])
        rock = plan3d.upgrade(plan3d.parse('{"objects_3d": [], "code": [{"name": "rock", "solid": true}]}', 2),
                              "rock", ["Rock"], (5.0, 5.0, 9.0))
        self.assertEqual((rock.name, rock.measure, rock.size_m), ("rock", "height", 9.0))  # the existing item
        car = plan3d.parse('{"objects_3d": [], "code": ["red sports car"]}', 2)
        self.assertIsNone(plan3d.upgrade(car, "red sports car", ["Sports_car"], (1.9, 4.6, 1.3)))

    def test_an_upgrades_picture_comes_from_the_object_as_it_is(self):
        text = plan3d.upgrade_picture("Red car", "make this hyper-realistic", [
            "Red car", "Red car body", "car front left light", "Car wheel.001", "Car wheel.002"],
            [("Car paint", "red"), ("Tyre rubber", "black"), ("Glass", "dark grey")])
        self.assertEqual(text, 'Red car, as the person asked: "make this hyper-realistic"; with body, front left '
                               'light, wheel; in red paint, black tyre rubber, dark grey glass; the whole Red car '
                               'fully in view at full size, three-quarter view')
        self.assertEqual(plan3d.upgrade_picture("Bench", "make it real", [], []),
                         'Bench, as the person asked: "make it real"; the whole Bench fully in view at full size, '
                         'three-quarter view')

    def test_the_looks_line(self):
        self.assertEqual(plan3d.looks_text(True, 6, 0.15), "Looks: a concept picture and up to 6 textures · up to $1.05")
        self.assertEqual(plan3d.looks_text(False, 1, 0.15), "Looks: up to 1 texture · up to $0.15")
        self.assertEqual(plan3d.looks_text(True, 0, 0.15), "Looks: a concept picture · $0.15")
        self.assertEqual(plan3d.looks_text(True, 0, 0.15, concept_price=0.005), "Looks: a concept picture · $0.005")
        self.assertEqual(plan3d.looks_text(True, 2, 0.15, concept_price=0.005),
                         "Looks: a concept picture and up to 2 textures · up to $0.30")
        self.assertEqual(plan3d.looks_text(False, 0, 0.15), "")

    def test_a_looks_only_plan_asks_before_any_picture_is_paid_for(self):
        plan = plan3d.looks_plan(True, 6, 0.15)
        self.assertTrue(plan.looks_only)
        self.assertEqual((plan.items, plan.looks), ([], "Looks: a concept picture and up to 6 textures · up to $1.05"))
        self.assertEqual(plan.queue(), [])  # nothing for the 3D queue
        self.assertEqual(plan3d.looks_plan(False, 2, 0.15).looks, "Looks: up to 2 textures · up to $0.30")
        self.assertIsNone(plan3d.looks_plan(False, 0, 0.15))  # nothing to pay for: no plan

    def test_colour_words(self):
        self.assertEqual([plan3d.colour_word(c) for c in ((0.6, 0.02, 0.02), (0.8, 0.8, 0.8), (0.05, 0.2, 0.6),
                                                          (0.2, 0.08, 0.02), (0.005, 0.005, 0.005))],
                         ["red", "white", "blue", "brown", "black"])

    def test_a_change_that_adds_nothing_has_no_plan_to_show(self):
        plan = plan3d.parse('{"objects_3d": [], "code": ["car"], "adds_objects": false}', 2)
        self.assertFalse(plan.adds_objects)
        self.assertIn("adds_objects: false when the request only removes, moves, recolours", plan3d.system(2))
        self.assertIn("goes in objects_3d, past the limit if needed", plan3d.system(2))


class RemovalEntryTest(unittest.TestCase):
    def test_a_removal_is_never_a_planned_thing(self):
        plan = plan3d.parse('{"code": [{"name": "lighthouse removal"}, {"name": "fish market stall"}], '
                            '"adds_objects": true}', 2)
        self.assertEqual([i.name for i in plan.items], ["fish market stall"])
        self.assertTrue(plan3d.is_removal("Remove the old fence"))
        self.assertFalse(plan3d.is_removal("market stall"))


class AreasTest(unittest.TestCase):
    def test_the_plan_keeps_how_the_request_relates_its_places(self):
        plan = plan3d.parse('{"code": [{"name": "pond"}], "areas": [{"area": "pond", "inside": "garden"}, '
                            '{"area": "x"}]}', 2)
        self.assertEqual(plan.areas, [{"area": "pond", "inside": "garden"}])
