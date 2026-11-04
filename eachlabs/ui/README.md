# ui

The prompt bar's pixels and text, with no Blender code. The bar is drawn with Skia into an RGBA image that
`viewport/` shows in the 3D view; drawing returns the rectangles of its controls so clicks can be matched to them.

## Modules

| Module | Job |
|-|-|
| `bar.py` | Draws the whole bar for a state and returns the hit rectangles of its controls |
| `bar_state.py` | What the bar shows for a chat run, and where it sits in the 3D view |
| `status_rows.py` | Stage chips, the asked prompt, the checking and thinking lines, 3D job rows, errors, the camera menu above the actions |
| `action_rows.py` | Action pills (Play split with its camera menu part, Pause), the consent card, the plan card with its chips |
| `tab_row.py` | Scene, Assets and Characters above the input, the line under them saying what the next prompt does, and the chip of the selected thing it changes |
| `input_rows.py` | The prompt field, the send button and the hint; the menus' rows (quality, cameras) |
| `tooltips.py` | What each control says on hover, keyed by hit id; the sidebar's buttons use the same texts |
| `tooltip_card.py` | The tooltip card: its wrapped lines, where it sits over its control in the 3D view, and its pixels |
| `draw.py` | Drawing helpers: paints, text, icons, the spinner, the mark |
| `fonts.py` | Typefaces, fallback fonts, measuring and wrapping text |
| `text_field.py` | The editable prompt text: caret, selection, words, history, undo, clipboard |
| `tokens.py` | Colours, type and sizes of the bar |

## Neighbours

- **Called by** `viewport/` (drawing and input) and `overlay.py`.
- **Calls** Skia only.

## Keep out

- No `bpy`: everything here runs in the unit tests. Blender-side drawing and events live in `viewport/`.
- No run logic: the bar shows a state, it does not decide it.

## Tests

`tests/test_bar_render.py`, `tests/test_bar_state.py`, `tests/test_play_cameras.py`, `tests/test_text_field.py`,
`tests/test_tooltips.py`
(unit, with `skia-python`), and the
bar checks in `scripts/gui-check.sh`.
