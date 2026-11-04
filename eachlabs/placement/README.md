# placement

Where things go, by relations. The model says what it means (a thing stands in an area, on the ground or on a named
surface, near or apart from something, in a ring or a row) with `zone()`, `place()` and `scatter()`, and this package
works out the positions. It knows no kinds of things, only the relations and the names the model gave.

## Modules

| Module | Job |
|-|-|
| `relations.py` | What the model may say about where a thing or an area goes, checked and put in one shape |
| `solver.py` | A spot and a turn for each thing so its relations hold; what cannot be placed is reported with the rule |
| `zones.py` | Laying out the areas (villages, a forest, a camp) from what the model says about them |
| `area_rules.py` | The relations the request itself states between places ("around the mountain", "in the forest") |
| `scatter.py` | Spots for many copies across an area: random, never in rows, clear of each other |
| `geometry.py`, `grid.py` | Plain 2D boxes, rings and turned footprints, and a spatial grid to test them quickly |
| `scene_io.py` | The Blender side: footprints, the ground, the areas, what lies under a spot |
| `apply.py` | Runs a step's placement calls on the main thread after the step's code |
| `settle.py` | Small loose props come down onto what is under them, a whole thing at a time: a thing's parts keep where they stand to each other; a group of things settles thing by thing |

## Neighbours

- **Called by** `code_runner.py` after each step (`apply.run`), `scene/step_namespace.py` (the calls a step sees) and
  the stage loop (`settle`).
- **Calls** Blender, in `scene_io.py`, `apply.py` and `settle.py`, and `things.registry` (what a thing is) in `settle.py`.

## Keep out

- `relations`, `solver`, `zones`, `area_rules`, `scatter`, `geometry` and `grid` import nothing from `bpy`, so the unit
  tests cover them.
- No knowledge of particular objects: a relation names things; it never assumes what they are.

## Tests

`tests/test_placement.py` (unit) and the placement and zone scenarios in `tests/smoke.py` (Blender).
