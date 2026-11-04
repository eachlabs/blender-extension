"""Tells Blender's untouched startup Cube apart from every other object. Pure Python: ``facts`` come from Blender.

A new chat scene hides that one object (in the viewport and the render; it is never deleted, moved or changed),
because the default 2 m Cube at the origin otherwise sits in the middle of every shot. Any difference from the
startup file's Cube means the person made it theirs, and it is left alone.
"""

DEFAULT_MATERIAL = "Material"
TOLERANCE = 1e-6
CORNERS = frozenset((x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0))


def _near(values, expected):
    return len(values) == len(expected) and all(abs(v - e) <= TOLERANCE for v, e in zip(values, expected))


def matches(facts):
    """True when ``facts`` (see ``scene_build.cube_facts``) describe Blender's untouched startup Cube."""
    try:
        verts = [tuple(v) for v in facts["vertices"]]
        corners_found = all(any(_near(v, c) for v in verts) for c in CORNERS)
        return (facts["name"] == "Cube" and facts["type"] == "MESH" and facts["data_name"] == "Cube"
                and len(verts) == 8 and facts["faces"] == 6 and corners_found
                and _near(facts["location"], (0.0, 0.0, 0.0)) and _near(facts["rotation"], (0.0, 0.0, 0.0))
                and _near(facts["scale"], (1.0, 1.0, 1.0))
                and not facts["hidden"] and facts["modifiers"] == 0 and not facts["parent"]
                and facts["data_users"] == 1 and facts["children"] == 0
                and facts["constraints"] == 0 and not facts["animation"]
                and all(m in (None, DEFAULT_MATERIAL) for m in facts["materials"]))
    except (KeyError, TypeError, ValueError):
        return False
