# library

Helper functions that worked in earlier scenes, kept on this computer. When a run finishes, the top-level helpers of
its successful steps are stored; later runs are offered the ones that fit their request by name, and a helper a step
calls is defined before the step runs. The "Reuse helpers that worked" setting turns it off.

## Modules

| Module | Job |
|-|-|
| `helpers.py` | Finding the helpers in a step's code, which ones a later step calls, and which ones fit a request |
| `store.py` | The library's one JSON file in the add-on's own folder, capped in size |

## Neighbours

- **Called by** `chat/library_use.py` (loading, offering, keeping) and `code_runner.py` (defining what a step calls).
- **Calls** `code_check.py`: every helper passes the code filter when it is stored, loaded and reused.

## Keep out

- `helpers.py` imports nothing from `bpy`.
- Nothing leaves this computer except as part of the model call that offers a helper.

## Tests

`tests/test_library.py` (unit) and the helper library scenario in `tests/smoke.py` (Blender).
