# scene

The scene the chat builds, as the model sees it. `read_scene` gathers every object of the chat's own with its real
bounds, and every check's findings; `camera_view` reports what the scene camera sees through its move; and each step
runs with a small set of helpers already defined. `scene_build.py` keeps one build's state and calls into here.

## Modules

| Module | Job |
|-|-|
| `report.py` | `read_scene`: the chat's objects, lights, world and camera, its things (kind, other words, parent) and orphans, with every check's findings |
| `camera_view.py` | What the scene camera sees: framing, the subject through the move, keeping a move intact |
| `camera_move.py` | The camera's keyed move: its keys, its length and the notes about it |
| `view_lists.py` | Shorter `camera_view` lists: objects grouped by kind, the empty share of the frame |
| `step_namespace.py` | What a step's code finds defined: `scene`, `attach()`, `replace()`, `copy_thing()`, `blend()`, `thing()`, `zone()`, `place()`, `scatter()`; `thing()` and copies are queued for the add-on, never written by the step |
| `blend.py` | `blend()`: round parts fused into one smooth surface (joined, voxel remeshed, smoothed) on the top part, each face keeping the nearest part's material and colours fading where parts meet (a face-corner colour each material copy mixes in); thin or flat parts stay out, attached; modifiers only, no `bpy.ops` |
| `blend_size.py` | How finely `blend()` remeshes and how much it smooths, which parts are too thin or flat for it, and each colour's share near an edge |
| `replaced.py` | A rebuilt part's old version removed: by `replace(old, new)` at once, or after a stage when the old one still lies under the new |
| `snapshot.py` | What a step may change, measured before and after it |
| `generated.py` | Generated 3D models and the world: keeping their looks when a step changes them |
| `new_scene.py` | A fresh Blender scene for New scene, and telling the startup Cube apart |
| `common.py` | Constants and small helpers the build and its checks share |

## Neighbours

- **Called by** `scene_build.py` (one build's state) and `code_runner.py` (each step).
- **Calls** `checks/` for the measurements, `placement/` for the step's placement calls.

## Keep out

- No decisions about what to fix: this package measures and reports, `chat/` decides.
- `common.py`, `view_lists.py` and `blend_size.py` stay free of `bpy`.

## Tests

`tests/test_scene_tools.py` and `tests/test_blend_size.py` (unit) and the `read_scene`, camera and step scenarios in `tests/smoke.py` (Blender).
