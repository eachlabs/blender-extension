# polyhaven

Free skies and textures from Poly Haven, all CC0. The model asks for a sky or a texture by description; the add-on,
not the model's code, picks a matching asset, downloads it, and puts it on the chat's own world or material at its
real size. The "Free skies and textures" setting turns it off, and without a network the model is told to build the
material with procedural nodes instead.

## Modules

| Module | Job |
|-|-|
| `catalog.py` | Picking an asset for a description (a sky of sky alone wins a tie), and the files to download |
| `fetch.py` | Downloading into the cache folder, https only, with size limits and file checks |
| `apply.py` | Putting a sky on the chat's world, or colour, roughness and normal maps on a material. The sky lights the scene; the camera sees a gradient in its colours, never the photo of the place |
| `tools.py` | The model's two tools, `free_sky` and `free_texture`: their schemas and how they run |

## Neighbours

- **Called by** the light and materials stages through `chat/work.py`.
- **Calls** `api_client.py`'s download helpers (in `fetch.py`) and `textures.py`'s node helpers (in `apply.py`).

## Keep out

- `catalog.py` uses no Blender and no network; `fetch.py` runs on the worker thread and never touches `bpy`.
- Only the chat's own worlds and materials are changed.

## Tests

`tests/test_polyhaven_catalog.py`, `tests/test_polyhaven_fetch.py`, `tests/test_polyhaven_tools.py` (unit).
