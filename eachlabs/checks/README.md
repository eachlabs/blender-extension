# checks

Measurements of the scene the chat built, taken from geometry and materials, never from names or kinds of things.
`read_scene` lists what they find, so the model fixes it; the run gives the placement problems a fix stage of their
own and never reports the scene as fine while they remain.

## Modules

| Module | Job |
|-|-|
| `placement.py` | Where things stand: free space, zones (outside, overlapping, too close, underfilled, counted by the things whose parent thing is the area), footing, sinking, floating over their support, parts off the ground |
| `overlaps.py`, `part_groups.py`, `loose_parts.py` | Things through each other, parts grouped into their things, parts apart from the rest |
| `gaps.py` | Gaps between a thing's parts, and small parts standing off the surface behind them |
| `piercing.py` | Thin parts that pass through another part of the same thing and stick out into the air |
| `duplicates.py` | Two copies of the same part in one place, and flat parts of two things doing the same job laid over each other (a second clock dial over a tower's own) |
| `mesh_health.py` | Holes and flipped faces in solid meshes, and closing small flat open ends |
| `free_space.py` | Free areas of the ground |
| `lights.py` | How many lights cast shadows, kept within what EEVEE can fit |
| `emission.py` | Glows that render as flat white shapes, or so bright they wash out to white |
| `looks.py` | Photo textures next to flat colours in one scene |
| `colours.py` | A thing whose biggest surfaces are not the colour the request asked for (the plan gives the colour) |
| `text_facing.py` | Text that reads backwards from the camera |
| `framing.py`, `exposure.py`, `through_glass.py` | Things in front of the lens, a frame too dark or one colour all over (an orange or blue cast), what the camera sees through glass |

## Neighbours

- **Called by** `scene/report.py` (`read_scene`), `scene/camera_view.py`, and `scene_build.py` at the end of a stage.
- **Calls** `solids.py` for evaluated meshes; nothing in `chat/`.

## Keep out

- No knowledge of particular objects: a check measures surfaces, gaps, colours and counts, and the model decides
  what a finding means for the thing it built.
- Checks report; they do not move or change objects (closing small open ends and the shadow limit are the two
  deliberate exceptions, applied at the end of a stage).

## Tests

`tests/test_colour_checks.py`, `tests/test_emission_check.py`, `tests/test_exposure_check.py`, `tests/test_framing_checks.py`,
`tests/test_looks_checks.py` (unit), and the check scenarios in `tests/smoke.py` (Blender).
