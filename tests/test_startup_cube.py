import unittest

from eachlabs import startup_cube

CORNERS = [(x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]


def default(**changes):
    facts = {"name": "Cube", "type": "MESH", "data_name": "Cube", "vertices": list(CORNERS), "faces": 6,
             "location": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0), "scale": (1.0, 1.0, 1.0), "hidden": False,
             "modifiers": 0, "parent": False, "children": 0, "data_users": 1, "constraints": 0, "animation": False,
             "materials": ["Material"]}
    facts.update(changes)
    return facts


class StartupCubeTest(unittest.TestCase):
    def test_the_untouched_startup_cube_matches(self):
        self.assertTrue(startup_cube.matches(default()))
        self.assertTrue(startup_cube.matches(default(materials=[])))
        self.assertTrue(startup_cube.matches(default(materials=[None])))
        self.assertTrue(startup_cube.matches(default(location=(1e-7, 0.0, 0.0))))

    def test_any_change_makes_it_the_persons(self):
        edited = list(CORNERS)
        edited[0] = (-1.0, -1.0, -1.5)
        for changes in ({"location": (0.0, 0.5, 0.0)}, {"scale": (2.0, 1.0, 1.0)}, {"rotation": (0.0, 0.0, 0.3)},
                        {"name": "Cube.001"}, {"name": "Box"}, {"data_name": "Cube.001"}, {"type": "CURVE"},
                        {"vertices": edited}, {"vertices": CORNERS + [(0.0, 0.0, 0.0)]}, {"faces": 12},
                        {"modifiers": 1}, {"materials": ["Brick"]}, {"materials": ["Material", "Brick"]},
                        {"hidden": True}, {"parent": True}, {"constraints": 1}, {"animation": True},
                        {"data_users": 2}, {"children": 1}):
            self.assertFalse(startup_cube.matches(default(**changes)), changes)

    def test_unreadable_facts_never_match(self):
        self.assertFalse(startup_cube.matches({}))
        self.assertFalse(startup_cube.matches(default(vertices=None)))


if __name__ == "__main__":
    unittest.main()
