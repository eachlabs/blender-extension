# shot

The chat's camera move turned into a realistic video: which frames become photos, how long the clip runs, what it
costs and what the prompts say, then the renders and the job that make it. The pure modules hold the rules; the
Blender modules (`views`, `render`, `start`) stay thin around them.

## Modules

| Module | Job |
|-|-|
| `keyframes.py` | How well a frame shows a thing, whether its box is around the camera, and the frames that show each thing best, also within the first part of a longer measure; a thing in view at every frame needs none of its own (no Blender) |
| `timing.py` | The clip's frames, hold and length, the dialog's default and longest length (a camera that does not move: a still shot, 5 s by default, up to 15 s), and its size per aspect ratio (no Blender) |
| `price.py` | The price of a shot video and its text (no Blender) |
| `models.py` | The video and photo models with their prices and limits, the aspects and resolutions |
| `prompts.py` | The prompts for the video and for each photo, with the person's direction; a camera that does not move is asked to stay still (no Blender) |
| `worker.py` | The job's worker: uploads the clip and renders, makes the photos, then the video, and downloads it (no Blender) |
| `views.py` | Which of the chat's things, nested ones too, the camera shows at each frame of the move, without the things around the camera |
| `view_cache.py` | That view measured once per camera, aspect and frame range (up to the longest video), kept until another file opens; a duration only picks again from it. Never measured on a draw, after an edit, or while a modal tool runs |
| `render_window.py` | Blender's render window kept closed while the shot renders; the person's setting comes back when the renders end, fail or stop |
| `render.py` | The grey Workbench clay clip with its held last frame, and an Eevee JPEG per key frame, one render at a time |
| `start.py` | Starts a shot job: checks the request, measures the view afresh and refuses (`SceneChanged`, nothing made or billed) when it no longer shows the key frames the person confirmed, renders, then runs the worker on the job registry; Retry does it all again. `key_frames` is the pick the price counts |

The job lives on `pipeline.REGISTRY`, so `pipeline.import_result` puts the video in the Video Sequencer like every
video job, but into the camera's own scene rather than a workspace's sequencer scene: one playhead then drives the
video and the camera move. Final render turns the scene's
sequencer off while it renders, so the strip never replaces the 3D picture. Prices round half up to the cent. The sidebar panel's video (`pipeline.start_video`) stays as it is. Retry never reuses renders or uploads:
the scene may have changed in ways no check sees.

## Tests

`tests/test_shot_keyframes.py`, `tests/test_shot_timing.py`, `tests/test_shot_price.py`, `tests/test_shot_prompts.py`,
`tests/test_shot_worker.py`; the Blender modules in the smoke test `tests/smoke/shot.py`.
