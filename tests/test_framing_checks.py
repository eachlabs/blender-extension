import unittest

from eachlabs.checks import framing

POST = {"name": "Stall post", "root": "Market stall", "coverage_pct": 22.0, "distance_m": 1.2,
        "rect": (0.4, 0.55, 0.0, 1.0), "ground": False}


class Blockers(unittest.TestCase):
    def test_post_in_front_of_the_lens(self):
        found = framing.near_blockers([POST], subject="Town hall")
        self.assertEqual(found, [{"name": "Market stall", "distance_m": 1.2, "coverage_pct": 22.0}])

    def test_not_a_blocker(self):
        far = dict(POST, distance_m=9.0)
        edge = dict(POST, rect=(0.0, 0.15, 0.0, 1.0))  # a wall at the side of the frame frames the shot
        ground = dict(POST, ground=True)
        subject = dict(POST, root="Town hall")
        small = dict(POST, coverage_pct=3.0)
        self.assertEqual(framing.near_blockers([far, edge, ground, subject, small], subject="Town hall"), [])

    def test_closest_point_of_a_box(self):
        corners = [(x, y, z) for x in (1, 2) for y in (-1, 1) for z in (0, 1)]
        self.assertEqual(framing.closest_m((0, 0, 0), corners), 1.0)
        self.assertEqual(framing.closest_m((1.5, 0, 0.5), corners), 0.0)


class Never(unittest.TestCase):
    def test_a_boat_never_in_frame(self):
        views = [{"visible": [{"name": "Boat A hull"}, {"name": "Quay"}]}, {"visible": [{"name": "Boat B mast"}]}]
        big = {"Boat A": ["Boat A", "Boat A hull"], "Boat B": ["Boat B", "Boat B mast"],
               "Boat C": ["Boat C", "Boat C hull"]}
        self.assertEqual(framing.never_in_view(views, big), ["Boat C"])

    def test_only_what_the_request_is_about(self):
        views = [{"visible": [{"name": "Quay"}]}]
        big = {"Fishing boat 3": ["Fishing boat 3"], "Breakwater rocks": ["Breakwater rocks"]}
        self.assertEqual(framing.never_in_view(views, big, ["fishing boats", "lighthouse"]), ["Fishing boat 3"])


if __name__ == "__main__":
    unittest.main()
