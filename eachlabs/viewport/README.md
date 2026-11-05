# viewport

The prompt bar inside Blender's 3D view: putting the Skia image on screen, turning presses and keys into actions,
and running what the bar's buttons do. `overlay.py` keeps the bar's live state and registers the handlers; the
image itself comes from `ui/`.

## Modules

| Module | Job |
|-|-|
| `draw.py` | Drawing the bar in the 3D view: its scale, insets around side panels, the image as a GPU texture |
| `input.py` | Which region a press lands in, clicks, drags and double clicks in the field, and typing |
| `hover.py` | Tooltips: the control under the mouse, the wait before its tooltip shows, and the card in the 3D view |
| `fold.py` | Folding the done card to one line: when the run ended, when the mouse left the bar, one redraw when due |
| `actions.py` | What the field and the buttons do: focus, submit, the consent card, each action button |
| `live.py` | Late access to `overlay.py`'s module state |

## Neighbours

- **Called by** `overlay.py` (draw handler, gizmo and keymap).
- **Calls** `ui/` for the pixels and hit rectangles, and `chat_run.py` and `chat/operators.py` for actions.

## Keep out

- Module state lives in `overlay.py`; modules here read it late through `live.py`.
- `input.py` stays free of `bpy`, so the hit and selection logic is unit tested.

## Tests

`tests/test_bar_state.py`, `tests/test_text_field.py` (unit) and the bar checks in `scripts/gui-check.sh` (Blender
with a window).
