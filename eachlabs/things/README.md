# things

What belongs to what. Every object the chat builds belongs to exactly one **thing**: a town hall, a fence, a
clock, a village area. The add-on writes the thing's id on every object; the model only says what a thing is (a
kind and a few labels) and which thing it belongs to. Delete, replace, move, find and select then act on a whole
thing, its parts and its child things, whatever each part is called.

## Modules

| Module | Job |
|-|-|
| `ids.py` | Thing ids, labels, the naming scheme (`Town hall`, `Clock (Town hall)`, `Town hall / Roof`), matching a word against a thing, a thing's subtree, the inventory line |
| `registry.py` | The Blender side: declaring a thing on its root object, giving every object its thing's id after a step, gathering a thing's loose parts under its root, orphans, removing the rest of a thing whose root a step removed, making a planned part (a gate in a fence) a child of its owner, the inventory, migrating scenes built before things existed |
| `outliner.py` | One collection per thing, nested for child things, and the end-of-run names (a thing with copies, and its copies, go by their kind: `Pine tree 1`) |
| `after_step.py` | read_scene's things and orphans; after each step: applies the step's `thing()` calls and copies (a copy records which thing it copies), makes placed, scattered and zoned objects things, gives every object its thing, lists orphans and removes the rest of a thing whose root the step removed; at the end of a stage, orphans become things, planned parts become child things of their owner and the collections follow; at the end of a run, the names |

## Neighbours

- **Called by** `code_runner.py` after each step (declare, refresh, cascade), `scene_build.py` at the end of a
  stage (orphans left, collections) and the run's end (names), `scene/report.py` (the inventory), and the edit,
  find and selection code (a thing's subtree).
- **Calls** nothing outside the package except Blender, in `registry.py` and `outliner.py`.

## Keep out

- `ids.py` imports nothing from `bpy`, so the unit tests cover it.
- No knowledge of particular objects: kinds and labels come from the model, never from a list in the add-on.
- The model's code never writes a thing id: `thing()` queues a request and the add-on applies it after the step.

## Tests

`tests/test_things.py` (unit) and `test_things` in `tests/smoke.py` (Blender).
