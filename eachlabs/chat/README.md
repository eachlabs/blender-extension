# chat

One chat run, from the prompt to the reply. A run reads what the prompt asks for, shows a plan when something costs
money or exceeds the person's round limit, builds the scene stage by stage (layout, detail, materials, light, camera,
check), fixes what the checks measure, and reports what it built. This package holds the parts of a run, one job per
module; `chat_run.py` keeps the run's live state and `chat_loop.py` the stage loop.

## Modules

| Module | Job |
|-|-|
| `work.py` | The worker thread of a run: prompt, plan, stages, detail, 3D objects, the end |
| `stages.py` | The stages, their round budgets, and the tools and pictures each stage gets |
| `budget.py`, `detail_budget.py` | Rounds and money: what a request needs, scaled limits, the cost line |
| `messages.py` | The request message each stage gets |
| `model_calls.py` | Calling the language model: reply caps, retries, cut-off replies |
| `quality.py` | Prototype and Final: what each mode allows of the rounds, models, detail and pictures (no Blender) |
| `stage_models.py` | Which model answers which stage: the scene's model, a second one for light and materials, a third for the main objects' detail |
| `pictures.py` | Pictures in the model's messages, and calls sent again without them |
| `problems.py` | Measured problems: what a fix stage gets and how the reply words them |
| `review.py` | The scene review: one call judges the finished scene from four pictures, the guards on its findings, the second look after its fix and the done line (no Blender) |
| `review_run.py` | The scene review in Blender: its four pictures, and undoing its fix stage when the second look says it made the scene worse |
| `step_results.py` | Reading what a step came back with: errors, refusals, enum hints |
| `plan_flow.py` | The plan before Build, and building what is still missing |
| `edits.py`, `selection.py`, `removal.py` | Targeted edits, the selection and Find (by whole things: a selected part means its thing), the selection Assets and Characters change, and what rested on a removed thing |
| `detail_pick.py`, `detail_steps.py`, `candidates.py`, `judge.py` | The detail stage: picking objects, their steps, versions and the render judge |
| `object_jobs.py`, `texture_jobs.py`, `concepts.py` | Generated 3D objects, textures and pictures a run orders |
| `events.py`, `lifecycle.py`, `state.py`, `run_types.py` | Events applied on the main thread, the run's state and what it gives back |
| `scene_state.py`, `undo_watch.py`, `viewport.py`, `show_code.py` | The scene and viewport around a run, undo, and Show code |
| `operators.py` | The chat's Blender operators |
| `playback.py` | Play through a camera: the view looks through it while playing, then the view and the scene camera go back; whether a camera moves, from its keys and its parents', and from the targets of its constraints (Track To, Child Of, a Follow Path's animated path) |
| `play_cameras.py` | Which cameras Play lists, in what order, and each one's hint (no Blender) |
| `final_render.py` | Final render: the scene camera once with Cycles, saved next to the `.blend`, settings put back |
| `video_tab.py` | The bar's Video tab in Blender: the `Shot` it draws from (cameras, settings, photos from the measured view; it needs a camera, not a chat build), measuring that view when the tab opens, on a camera or aspect change and afresh on Send (never after an edit or under a modal tool), and what its chips and buttons do. Send opens the confirm card with that price; only Make video starts the video, with the key frames the card priced |
| `make_video.py` | Starting the shot video, and its operators outside the tab: Make video (opens the tab), Stop, Retry (the tab's confirm), Open Sequencer and Show file |
| `video_track.py` | A shot video job's state and stage (camera move, key frames, look, video, Sequencer) copied into the bar's video state on every main-thread tick (`pipeline.tick_hook`) and cleared when another file opens, how far its renders are, and where the video's window stops playing (no Blender) |
| `video_window.py` | Open Sequencer's window: the video's preview, the scene through its camera and the timeline, played together from the video's first frame and stopped at its last, the scene's last, or a wrap; its tagged workspace goes when it closes |
| `final_settings.py` | Final render's samples, aperture from the subject's size, and file name (no `bpy`) |
| `library_use.py`, `stage_log.py`, `debug_log.py` | The helper library in a run, the local stage log, the debug log |
| `live.py` | Late access to `chat_run`'s module state |

## Neighbours

- **Called by** `chat_run.py` (start, stop, retry) and the bar in `viewport/`.
- **Calls** `shot/` to start, retry and price a shot video, `instructions/` for what the model is told, `scene_build.py` and `code_runner.py` for every step,
  `checks/` through `read_scene`, `placement/`, `polyhaven/` and `library/`.

## Keep out

- Module state lives in `chat_run.py`; modules here read it late through `live.py`, never at import time.
- Modules marked "no Blender" in their docstring (`budget`, `stages`, `messages`, `problems`, `judge`, `quality`, …) import
  nothing from `bpy`, so unit tests cover them.

## Tests

`tests/test_chat_loop.py`, `tests/test_detail*.py`, `tests/test_judge.py`, `tests/test_review.py`, `tests/test_stage_log.py`,
`tests/test_play_cameras.py`, `tests/test_video_track.py` (unit), the
chat scenarios in `tests/smoke.py` (Blender), and the shot video's card and window in `tests/gui_check/video.py`.
