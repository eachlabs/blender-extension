# prefs

The add-on's saved settings as a chat run reads them: the model, round and wait limits, 3D objects, textures, the
detail stage, consent, folders and the API client. `preferences.py` defines the settings and their panel; this
package reads them, with safe defaults when the add-on's preferences cannot be read.

## Modules

| Module | Job |
|-|-|
| `chat_settings.py` | The chat's settings as a run reads them |
| `live.py` | Late access to `preferences.py`, so readers always use its current helpers |

## Neighbours

- **Called by** `chat_run.py` when a run starts, and by `chat/` modules that need one setting.
- **Calls** `preferences.py` through `live.py`.

## Keep out

- No new settings here: a setting is defined once, in `preferences.py`, with its default.
- No module state; settings are read when needed.

## Tests

The settings scenarios in `tests/smoke.py` (Blender).
