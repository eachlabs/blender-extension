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
| `tab_row.py` | Scene, Assets, Characters and Video above the input (wrapping in a narrow bar), the line under them saying what the next prompt does, and the chip of the selected thing it changes |
| `input_rows.py` | The prompt field, the send button and the hint; the menus' rows (quality, cameras) |
| `video_line.py` | The shot video on the other tabs: its line on the done card, on the status line while a chat run goes, or in the note otherwise; its part of the folded line; and its pills |
| `video_tab.py` | The Video tab from a `Shot`: the settings chips and their menus with prices, the notes (no camera, still camera, a move over 15 s), the confirm card Send opens, and what the tab puts on the bar state |
| `video_card.py` | The Video tab's card for a video being made, made, failed or stopped: stage chips from the job's stage, time and price, the sentence on the stage and the next, the live line, Stop's question and the buttons |
| `video_rows.py` | The Video tab's rows: the card above the tabs, an open chip's menu, the settings chips with the price, the notes |
| `video_texts.py` | What the Video tab says, and the hit ids of its chips, menu items and buttons |
| `tooltips.py` | What each control says on hover, keyed by hit id; the sidebar's buttons use the same texts |
| `tooltip_card.py` | The tooltip card: its wrapped lines, where it sits over its control in the 3D view, and its pixels |
| `draw.py` | Drawing helpers: paints, text, icons, the spinner, the mark |
| `fonts.py` | Typefaces, fallback fonts, measuring and wrapping text |
| `text_field.py` | The editable prompt text: caret, selection, words, history, undo, clipboard |
| `tokens.py` | Colours, type and sizes of the bar |

## Neighbours

- **Called by** `viewport/` (drawing and input) and `overlay.py`.
- **Calls** Skia, and reads the video model, its prices and limits from `shot/models.py` and `shot/price.py`.

## Keep out

- No `bpy`: everything here runs in the unit tests. Blender-side drawing and events live in `viewport/`.
- No run logic: the bar shows a state, it does not decide it.

## Tests

`tests/test_bar_render.py`, `tests/test_bar_state.py`, `tests/test_play_cameras.py`, `tests/test_text_field.py`,
`tests/test_tooltips.py`, `tests/test_video_tab.py`
(unit, with `skia-python`), and the
bar checks in `scripts/gui-check.sh`.
