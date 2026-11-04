import math
import unittest

from eachlabs.placement import geometry as geo
from eachlabs.placement import area_rules, relations, scatter, solver, zones
from eachlabs.placement.grid import Grid


def item(name, w=2.0, d=2.0, **rel):
    return solver.Item(name, (w, d), (0.0, 0.0), relations.thing(name, **rel))


class GeometryTest(unittest.TestCase):
    def test_turned_box_swaps_sides_at_a_quarter_turn(self):
        box = geo.turned_box(0, 0, (4, 2), (0, 0), math.pi / 2)
        self.assertAlmostEqual(box[2] - box[0], 2)
        self.assertAlmostEqual(box[3] - box[1], 4)

    def test_facing_turn_points_front_at_target(self):
        turn = geo.facing_turn(0, 0, 0, -5)  # target straight ahead along -Y: no turn
        self.assertAlmostEqual(turn, 0.0)

    def test_ring_holds_a_box_between_its_edges_only(self):
        ring = geo.Area("Forest", centre=(0, 0), inner=10, outer=30)
        self.assertTrue(ring.contains_box(geo.box_around(20, 0, 2, 2)))
        self.assertFalse(ring.contains_box(geo.box_around(0, 0, 2, 2)))  # in the hole
        self.assertFalse(ring.contains_box(geo.box_around(40, 0, 2, 2)))  # outside

    def test_ring_overlaps_box_on_its_band_not_in_its_hole(self):
        ring = geo.Area("Forest", centre=(0, 0), inner=10, outer=30)
        self.assertTrue(ring.overlaps_box(geo.box_around(25, 0, 3, 3)))
        self.assertFalse(ring.overlaps_box(geo.box_around(0, 0, 3, 3)))


class RelationsTest(unittest.TestCase):
    def test_near_takes_a_name_or_a_range(self):
        self.assertEqual(relations.thing("Tent", near=["Fire", 3, 6])["near"], ("Fire", 3.0, 6.0))
        self.assertEqual(relations.thing("Tent", near="Fire")["near"], ("Fire", 0.0, None))

    def test_wrong_values_say_what_to_write(self):
        with self.assertRaises(relations.Wrong):
            relations.thing("Tent", near=["Fire", 6, 3])
        with self.assertRaises(relations.Wrong):
            relations.area("Forest", ring_m=40)  # a ring needs around=
        with self.assertRaises(relations.Wrong):
            relations.area("Village")  # no size
        with self.assertRaises(relations.Wrong):
            relations.area("Village", size=[40, 40], holds="many")

    def test_an_area_says_how_many_things_it_holds(self):
        self.assertEqual(relations.area("Village", size=[60, 60], holds=12)["holds"], 12)
        self.assertIsNone(relations.area("Village", size=[60, 60])["holds"])

    def test_names_in_lists_every_reference(self):
        rel = relations.thing("Tent", zone="Camp", near=["Fire", 3], apart_m={"Road": 5}, facing="Fire")
        self.assertEqual(sorted(relations.names_in(rel)), ["Camp", "Fire", "Fire", "Road"])


class SolverTest(unittest.TestCase):
    def world(self):
        w = solver.World()
        w.domain = geo.Area("ground", box=(-50, -50, 50, 50))
        return w

    def test_things_in_a_zone_stay_inside_and_apart(self):
        w = self.world()
        w.areas["Camp"] = geo.Area("Camp", box=(10, 10, 30, 30))
        placed, unplaced = solver.solve([item("Tent %d" % i, 3, 3, zone="Camp") for i in range(6)], w)
        self.assertEqual(unplaced, [])
        boxes = [w.boxes["Tent %d" % i] for i in range(6)]
        for box in boxes:
            self.assertTrue(w.areas["Camp"].contains_box(box, max(solver.ZONE_SLACK_M, solver.ZONE_SLACK_SHARE * 20)))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(geo.boxes_overlap(a, b))

    def test_around_puts_things_on_a_ring_facing_the_middle(self):
        w = self.world()
        w.boxes["Fire"] = geo.box_around(0, 0, 0.6, 0.6)
        w.grid.add(w.boxes["Fire"], "Fire")
        placed, unplaced = solver.solve([item("Bandit %d" % i, 0.6, 0.6, around="Fire") for i in range(5)], w)
        self.assertEqual(unplaced, [])
        for name, (x, y, turn) in placed.items():
            self.assertLess(math.hypot(x, y), 3.0)
            self.assertGreater(math.hypot(x, y), 0.8)
            self.assertLess(geo.angle_off(turn, geo.facing_turn(x, y, 0, 0)), 0.01)

    def test_near_keeps_the_distance(self):
        w = self.world()
        w.boxes["Well"] = geo.box_around(0, 0, 1, 1)
        w.grid.add(w.boxes["Well"], "Well")
        placed, _ = solver.solve([item("Bench", 2, 1, near=["Well", 2, 4])], w)
        x, y, _turn = placed["Bench"]
        d = math.hypot(x, y)
        self.assertGreater(d, 1.0)
        self.assertLess(d, 8.0)

    def test_a_full_zone_reports_the_failing_rule(self):
        w = self.world()
        w.areas["Tiny"] = geo.Area("Tiny", box=(0, 0, 3, 3))
        _placed, unplaced = solver.solve([item("Barn", 10, 10, zone="Tiny")], w)
        self.assertEqual(unplaced[0]["thing"], "Barn")
        self.assertIn("Tiny", unplaced[0]["rule"])

    def test_unknown_names_are_reported(self):
        _placed, unplaced = solver.solve([item("Tent", zone="Nowhere")], self.world())
        self.assertIn("Nowhere", unplaced[0]["rule"])

    def test_valid_rejects_spots_the_blender_side_refuses(self):
        w = self.world()
        w.valid = lambda name, x, y, on: True if x > 0 else "water"
        placed, _ = solver.solve([item("Hut")], w)
        self.assertGreater(placed["Hut"][0], 0)


class ZonesTest(unittest.TestCase):
    def test_ring_forest_around_a_mountain_and_apart_villages(self):
        domain = geo.Area("ground", box=(-300, -300, 300, 300))
        boxes = {"Mountain": geo.box_around(0, 0, 40, 40)}
        reqs = [relations.area("Forest", ring_m=80, around="Mountain"),
                relations.area("Small village", size=(40, 40), inside="Forest"),
                relations.area("Large village", size=(80, 80), apart_m={"Small village": 120}),
                relations.area("Bandit camp", size=(25, 25), inside="Forest", apart_m={"Small village": 40})]
        out, unplaced = zones.solve(reqs, {}, boxes, domain)
        self.assertEqual(unplaced, [])
        forest = out["Forest"]
        self.assertTrue(forest.is_ring)
        self.assertGreater(forest.inner, 40)
        self.assertTrue(forest.contains_box(out["Small village"].box))
        self.assertTrue(forest.contains_box(out["Bandit camp"].box))
        self.assertGreaterEqual(geo.box_gap(out["Large village"].box, out["Small village"].box), 120)
        self.assertGreaterEqual(geo.box_gap(out["Bandit camp"].box, out["Small village"].box), 40)
        self.assertFalse(geo.boxes_overlap(out["Large village"].box, boxes["Mountain"]))

    def test_no_room_says_to_grow_the_ground(self):
        domain = geo.Area("ground", box=(-20, -20, 20, 20))
        _out, unplaced = zones.solve([relations.area("Town", size=(100, 100))], {}, {}, domain)
        self.assertIn("ground", unplaced[0]["rule"])


class ScatterTest(unittest.TestCase):
    def test_copies_spread_in_the_ring_clear_of_obstacles(self):
        ring = geo.Area("Forest", centre=(0, 0), inner=20, outer=60)
        grid = Grid()
        grid.add(geo.box_around(40, 0, 6, 6), "Hut")
        out = scatter.spots(ring, 200, 1.5, grid, seed=3)
        self.assertGreater(len(out), 150)
        for x, y, _turn, scale in out:
            self.assertTrue(ring.contains_point(x, y, 1.0))
            self.assertFalse(geo.boxes_overlap(geo.box_around(x, y, 1.5 * scale, 1.5 * scale),
                                               geo.box_around(40, 0, 6, 6)))


class AreaSizedTest(unittest.TestCase):
    def test_a_wall_as_large_as_its_area_goes_in_the_middle(self):
        w = solver.World()
        w.areas["Village"] = geo.Area("Village", box=(0, 0, 100, 88))
        placed, unplaced = solver.solve([item("Stone fence", 101, 89, zone="Village")], w)
        self.assertEqual(unplaced, [])
        self.assertAlmostEqual(placed["Stone fence"][0], 50, places=3)
        self.assertAlmostEqual(placed["Stone fence"][1], 44, places=3)


class AreaRulesTest(unittest.TestCase):
    RULES = area_rules.parse([{"area": "forest", "around": "the mountain"}, {"area": "bandit camp", "inside": "forest"},
                              {"area": "nowhere"}, "junk"])

    def test_parse_keeps_stated_relations_only(self):
        self.assertEqual([r["area"] for r in self.RULES], ["forest", "bandit camp"])

    def test_a_box_forest_becomes_a_ring_around_the_mountain(self):
        req = relations.area("Forest", size=(80, 70), near=["Snow mountain", 4, 20])
        honoured, stated = area_rules.honour(req, self.RULES, ["Snow mountain", "Path"], {"Forest", "Bandit camp"})
        self.assertEqual(honoured["around"], "Snow mountain")
        self.assertEqual(honoured["ring_m"], 40)
        self.assertIsNone(honoured["size"])
        self.assertEqual(stated, {"around": "Snow mountain"})

    def test_a_camp_near_the_forest_goes_inside_it(self):
        req = relations.area("Bandit settlement camp", size=(30, 30), near=["Forest", 0, 20])
        honoured, stated = area_rules.honour(req, self.RULES, [], {"Forest", "Bandit settlement camp"})
        self.assertEqual(honoured["inside"], "Forest")
        self.assertEqual(stated, {"inside": "Forest"})

    def test_the_zones_solver_then_meets_both(self):
        boxes = {"Snow mountain": geo.box_around(0, 0, 40, 40)}
        reqs = [area_rules.honour(r, self.RULES, list(boxes), {"Forest", "Bandit camp"})[0] for r in (
            relations.area("Forest", size=(120, 120)), relations.area("Bandit camp", size=(25, 25)))]
        out, unplaced = zones.solve(reqs, {}, boxes, geo.Area("ground", box=(-300, -300, 300, 300)))
        self.assertEqual(unplaced, [])
        self.assertEqual(area_rules.ring_cover(out["Forest"], boxes["Snow mountain"]), 1.0)
        self.assertIsNone(area_rules.unmet(out["Bandit camp"], {"inside": "Forest"}, parent=out["Forest"]))

    def test_a_rule_for_one_village_never_reaches_the_other(self):
        rules = area_rules.parse([{"area": "small village", "inside": "forest"}])
        req = relations.area("Larger village", size=(90, 85))
        honoured, stated = area_rules.honour(req, rules, [], {"Forest", "Small village", "Larger village"})
        self.assertEqual(stated, {})
        self.assertIsNone(honoured["inside"])

    def test_unmet_names_what_is_wrong(self):
        beside = geo.Area("Forest", box=(60, -40, 140, 40))
        mountain = geo.box_around(0, 0, 40, 40)
        self.assertLess(area_rules.ring_cover(beside, mountain), 0.5)
        self.assertIn("way round", area_rules.unmet(beside, {"around": "Snow mountain"}, mountain))
        camp = geo.Area("Camp", box=(200, 200, 230, 230))
        self.assertIn("outside", area_rules.unmet(camp, {"inside": "Forest"}, parent=beside))


if __name__ == "__main__":
    unittest.main()


class GrownZone(unittest.TestCase):
    def test_a_camp_too_small_for_its_tents_grows_around_its_centre(self):
        from eachlabs.placement import geometry as g
        camp = g.Area("Camp", box=g.box_around(10, 0, 3, 3))  # 6 x 6 m
        bigger = g.grown_for(camp, (9.0, 5.0))
        self.assertAlmostEqual(bigger.box[2] - bigger.box[0], 9.0 * g.GROW_MARGIN)
        self.assertAlmostEqual((bigger.box[0] + bigger.box[2]) / 2, 10.0)
        self.assertEqual(bigger.box[3] - bigger.box[1], 6.0)  # deep enough already

    def test_fits_already(self):
        from eachlabs.placement import geometry as g
        self.assertIsNone(g.grown_for(g.Area("Field", box=g.box_around(0, 0, 10, 10)), (4.0, 4.0)))

    def test_a_ring_widens_outward(self):
        from eachlabs.placement import geometry as g
        forest = g.Area("Forest", centre=(0, 0), inner=50, outer=54)
        self.assertGreater(g.grown_for(forest, (8.0, 6.0)).outer, 58)
