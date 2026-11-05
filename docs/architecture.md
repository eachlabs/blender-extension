# Architecture

The Eachlabs Blender extension sends what a Blender user already produces (a rendered frame, a
rendered camera move, later render passes) to an Eachlabs model or workflow and brings the result
back into Blender. Blender is the host and Eachlabs is the service: the add-on calls the public
HTTPS API directly with the standard library and adds no web UI or server. An agent can drive the
same operators later.

It also has a **scene chat**: a prompt bar in the 3D view that builds a scene and a camera move from
one prompt. The model writes Blender Python and the add-on runs it; this is **not a sandbox**. See
[Scene chat](#scene-chat) and [Running the model's code](#running-the-models-code).

Supported hosts: Blender 4.2 LTS and newer. Behaviour that differs between 4.2 and 5.x is isolated
in `compat.py` and listed under [Version differences](#version-differences).

## Modules

All code lives in the `eachlabs` package (the extension source directory).

| Module | bpy | Responsibility |
|---|---|---|
| `api_client.py` | no | HTTPS client for the Eachlabs API: catalog, workflows, presigned upload, predictions, workflow executions, downloads, error normalization |
| `capabilities.py` | no | Turns catalog entries into capability records, filters targets per action, lists bindable inputs, builds the request input |
| `jobs.py` | no | Job model, the worker that uploads, submits, polls and downloads, and the queue that hands results to the main thread |
| `naming.py` | no | Output folder and file names (job IDs in every name) |
| `timing.py` | no | Scene fps, frame ranges and strip speed math |
| `mcp_client.py` | no | Minimal MCP client (`initialize`, `tools/list`) for the connection line in the sidebar |
| `startup_cube.py` | no | Tells Blender's untouched startup Cube apart from every other object |
| `scene_tools.py` | no | The three tool schemas (`run_python`, `read_scene`, `camera_view`), argument checks, row labels |
| `chat_loop.py` | no | The stage loop: model call, tool calls, round caps, failures, Code check refusals, cancel |
| `detail.py` | no | The detail stage: the pick of main objects, and each object's rounds on worker threads |
| `detail_compare.py` | no | The detail stage's comparison of an object with its reference picture, after each round |
| `code_check.py` | no | The rule filter that refuses Blender Python outside scene building, and `redact` for the API key |
| `code_review.py` | no | Code check: one extra model call that reads a step before it runs |
| `settings_guard.py` | no | Empties the API key in the preferences while a step runs, and notices a step that changed a setting |
| `ui/tokens.py` | no | Colours, type and sizes of the prompt bar |
| `ui/bar.py` | no | Draws the prompt bar with Skia into RGBA pixels and returns the hit rectangles of its controls |
| `ui/bar_state.py` | no | What the bar shows for a chat run, and where it sits in the 3D view |
| `ui/text_field.py` | no | The editable prompt text: caret, selection, words, history, undo, clipboard |
| `viewport_marks.py` | draw only | Orange flash on new objects and the dashed camera path; its state is plain Python |
| `code_runner.py` | yes | Runs one filtered step in a fresh namespace under a time limit and summarizes what it changed |
| `error_hints.py` | yes | The answer to a failed step's error: close names for a missing attribute, read from the live type |
| `edit_guard.py` | yes | Puts back what a targeted edit changed outside its targets, and the world through a follow-up not about the light |
| `scene_build.py` | yes | Runs the three tools on the run's scene, owns its collection and tags, one undo step per stage |
| `undo_steps.py` | yes | Reads the name of Blender's active undo step for *Undo stage* |
| `chat_run.py` | yes | Run state, the chat worker thread, the queue it hands work through, the chat operators |
| `overlay.py` | yes | Draws the bar in every 3D view; takes presses through an invisible gizmo (and a 3D View keymap item as fallback) and keys through a modal operator that runs only while the bar has focus; redraws while focused or running; not registered without Skia (the sidebar shows a plain prompt instead) |
| `main_thread.py` | yes | The single `bpy.app.timers` dispatcher, UI redraw tagging and file-load handlers |
| `render_export.py` | yes | Still, viewport and frame-range renders, MP4 packaging and first/last frame export |
| `visual_check.py` | yes | The visual check's small render for the chat model, and the detail stage's close-up of one object, with the scene's settings put back |
| `importers.py` | yes | Image datablocks, Image Editor, camera background, VSE movie strips and fps reconciliation |
| `compat.py` | yes | Version shims for the sequencer, output-format and scene-building APIs |
| `catalog.py` | yes | Session cache of models and workflows and the window-manager collections the panels search |
| `pipeline.py` | yes | Orchestrates each action: validate, render, start the job, import |
| `preferences.py` | yes | API key, base URL, polling settings, Test connection |
| `props.py` | yes | Scene settings, input bindings, model parameters and the last inputs kept for re-run |
| `operators.py` | yes | Thin operators that validate context and call `pipeline` |
| `panels.py` | yes | The `Eachlabs` sidebar tab in the 3D Viewport and the Video Sequencer |

Modules without `bpy` import nothing from Blender, so the unit tests run under any Python 3.11+
(the bar tests also need `skia-python`).

The biggest modules above keep their entry points and delegate to packages, one job per module. Each package has a README with its modules, its neighbours and its tests:

| Package | Holds |
|---|---|
| [`chat/`](../eachlabs/chat/README.md) | One chat run, split by job: `stages`, `budget`, `messages`, `model_calls`, `pictures`, `problems`, `step_results`, `run_types`, `debug_log`, `detail_budget` (the detail stage's rounds within the person's limit), `stage_models` (which model each stage calls), `stage_log` (a local log of kept, undone and retried stages), `review` (the scene review, no `bpy`) and `review_run` (its pictures and undo), `final_settings` (no `bpy`), and `work`, `events`, `edits`, `selection`, `plan_flow`, `object_jobs`, `texture_jobs`, `detail_steps`, `detail_pick`, `concepts`, `removal`, `scene_state`, `undo_watch`, `viewport`, `show_code`, `lifecycle`, `state`, `operators`, `library_use` (the helper library in a run), `final_render` (Cycles render of the finished scene) |
| [`instructions/`](../eachlabs/instructions/README.md) | Everything the model is told: `rules` (shared rules, shape examples, version notes), `stages`, `notes`, `detail`, `plan` (the plan call's text) |
| [`scene/`](../eachlabs/scene/README.md) | The scene a run builds: `common` helpers, `report` (`read_scene`), `camera_view`, `generated`, `new_scene`, `snapshot` (what a step changed), `step_namespace` (what a step's code finds defined), `blend` (round parts fused into one smooth surface: joined, voxel remeshed, smoothed, colours fading where parts meet, thin parts left out; modifiers only) |
| [`checks/`](../eachlabs/checks/README.md) | One check per module: `placement`, `gaps`, `piercing`, `mesh_health`, `lights`, `looks` (photo textures next to flat colours), `text_facing` (signs that read backwards), `framing` (what blocks the lens, big things never in frame), `exposure` (a frame too dark), `emission` (strong flat white glows, and coloured glows bright enough to render white), `through_glass` (what the camera sees past each window); `placement` also lists big things floating over their support (`floats_above`) and areas holding fewer things than they should (`underfilled`) |
| [`polyhaven/`](../eachlabs/polyhaven/README.md) | Free CC0 skies and textures: `catalog` (picking one for a description, no `bpy`, no network), `fetch` (download and cache on the worker, md5 and signature checked), `apply` (world and material nodes, main thread), `tools` (the model's `free_sky` and `free_texture`) |
| [`placement/`](../eachlabs/placement/README.md) | Where things go, by relations: `geometry`, `grid`, `relations`, `solver`, `zones`, `scatter` (no `bpy`), and `scene_io`, `apply` (the Blender side, run after each step's code) |
| [`things/`](../eachlabs/things/README.md) | What every built object belongs to: `ids` (ids, kinds, labels, names, matching, no `bpy`), `registry` (declaring, ids after a step, removals, the inventory), `outliner` (one collection per thing, the end-of-run names), `after_step` (what a step's run applies) |
| [`library/`](../eachlabs/library/README.md) | Helpers that worked in earlier scenes: `helpers` (finding, offering and reusing them, no `bpy`), `store` (one capped JSON file on this computer) |
| [`viewport/`](../eachlabs/viewport/README.md) | The prompt bar in the 3D view: `draw`, `input`, `actions` |
| [`prefs/`](../eachlabs/prefs/README.md) | `chat_settings`: the chat's settings as a run reads them |
| [`ui/`](../eachlabs/ui/README.md) | The Skia bar, split into `fonts`, `draw`, `status_rows`, `action_rows`, `input_rows` |

The model can ask `blender_api` (`api_lookup`) for a type's properties, enum values and a node's sockets, read live from the running Blender.

A step's code calls `zone()`, `place()` and `scatter()` instead of setting positions: they queue requests, and
`placement.apply` lays out the areas, places the things and spreads the copies once the code has run, before
the step's new objects join the build. The solver filters candidate spots by hard rules (inside the area, on the
ground or a named surface, clear of every part, far enough from what to keep apart from), scores the rest by
soft ones (near, around, in a row), checks what lies under the best spots with a ray, and reports the rule that
failed for anything it cannot place.

Every object the chat builds belongs to exactly one thing. The add-on writes the thing's id on each object, never
the step's code. A step names a thing with `thing(obj, kind, labels, parent)`; its parts get the id through the
hierarchy or, in a detail step or a one-target edit, from the thing being worked on. New objects that belong to no
thing are reported as orphans, and become things of their own at the end of the stage. Removing, moving,
settling, finding, selecting and editing act on whole things, and the intent call matches them by name, kind and
labels from the inventory `read_scene` also lists. At the end of a run the add-on names them by one scheme
(`Town hall`, `Clock (Town hall)`, `Town hall / Roof`); code relies on the id, never on the name.

`chat_run.py`, `overlay.py` and `preferences.py` keep their module state; the modules split out of them read
it late, through `chat/live.py`, `viewport/live.py` and `prefs/live.py`, so the packages import in any order.

## Threading and timers

Blender's data API is not thread-safe, so the add-on keeps two strict sides.

```text
main thread                                   worker thread (one per job)
-----------                                   ---------------------------
operator -> pipeline.validate
         -> render (Blender render job, async)
render_complete handler sets a flag
dispatcher tick sees the flag
         -> restore render settings
         -> package MP4 / frames
         -> jobs.start(spec) ---------------->  upload inputs (presign + PUT)
                                                submit prediction / trigger workflow
                                                poll status (2 s, backing off to 5 s)
                                                download outputs
dispatcher tick drains queue  <-------------  post(update)   (never touches bpy)
         -> update Job, tag redraw
         -> on success: importers.* (bpy)
```

- **One dispatcher.** `main_thread.py` registers one persistent `bpy.app.timers` function. Each
  tick drains a `queue.SimpleQueue` of callables posted by workers and runs them on the main
  thread. It ticks every 0.2 s while any job or render is active (so elapsed time stays live) and
  every 1 s when idle.
- **Workers never touch `bpy`.** A worker receives an immutable `JobSpec` (paths, target,
  request input, API settings), a `threading.Event` for cancellation and a `post` function. It
  reports progress only by posting updates; the `Job` record is mutated on the main thread only.
- **Online access is checked on the main thread** (`bpy.app.online_access`) before any operator
  starts network work. Workers inherit that decision; they cannot read `bpy`.
- **Rendering stays in Blender's render job.** In the UI, renders run with
  `bpy.ops.render.render('INVOKE_DEFAULT', ...)`, so Blender shows progress and Esc cancels.
  `render_complete` and `render_cancel` handlers only set a flag; the dispatcher does the follow-up
  work, because render handlers can run while the render job still owns the scene. In background
  mode (`blender --background`) rendering is synchronous and the pipeline continues inline.
  Viewport snapshots (`render.opengl`) are synchronous and short.
- **Cancellation.** Cancel sets the job's event. The worker checks it between HTTP calls and
  waits on it instead of sleeping, so polling stops within one interval. For predictions the
  worker then calls `POST /v1/prediction/{id}/cancel`, best effort; that marks the run cancelled
  but does not stop provider work already in flight. Workflow executions have no public cancel
  endpoint, so cancelling a workflow job only stops local polling. The panel states both caveats.
  Python cannot stop Blender's render job, so a cancel during rendering
  marks the job cancelled, and the panel tells the user to press Esc in the render window to stop
  early. When the render ends, settings are restored and nothing is uploaded.
- **File loads and unregister.** A `load_pre` handler and `unregister()` cancel every job and stop
  the dispatcher, so no worker can import into a closed file.

## Actions and data flow

### Generate Image from View

1. Validate: online access, API key, a selected target, required inputs bound.
2. Render the current frame at the scene resolution to `<id>_still.png` (`render.render` with
   `write_still`), or take a viewport snapshot (`render.opengl`) when *Source* is *Viewport*.
   Render settings are snapshotted and restored afterwards.
3. Worker: upload `<id>_still.png` (presign, then PUT with the returned `required_headers`), build
   the request input from the bindings, submit, poll, download every output URL to
   `<id>_result_<n>.<ext>`.
4. Main thread: load the result as an Image datablock, show it in an Image Editor (an existing one,
   else the render view, else a new window), and when *Camera background* is on, put it in a
   reused background-image slot on the active camera for A/B comparison.

### Generate Video from Camera Move

1. Validate as above plus a valid frame range (defaults to the scene range).
2. Render the range as a PNG sequence at the preview resolution into `<id>_frames/` (scene
   resolution scaled by a percentage chosen to reach the preview height).
3. Package: encode `<id>_clip.mp4` (H.264 in MP4) from the PNG sequence through a temporary,
   sequencer-only scene using Blender's FFmpeg output with the scene fps and a neutral *Standard*
   view transform, then copy the first and last frames to `<id>_first_frame.png` and
   `<id>_last_frame.png`. Rendering the 3D scene once and encoding the frames keeps first/last
   frames identical to the clip without extra renders.
4. Worker: upload only the files the selected target is bound to, submit, poll, download.
5. Main thread: add the clip as a movie strip at the render's start frame on the first channel that
   is free over the whole range, then reconcile timing (below).

### Re-run

Each action stores its last input set on the scene (`props.py`): input set ID, file paths, frame
range, scene fps, and the uploaded URL per file with its upload time. *Re-run* rebuilds the request
from the current panel (target, prompt, seed, parameters) and the stored files, without rendering.
Uploaded URLs are reused while their stored copy is retained (we upload with a 7-day retention);
otherwise the file is uploaded again. Re-run is disabled when a stored file is missing.

### Catalog, model detail and Test connection

- *Refresh* fetches all models (`GET /v1/models`, paged by 100) and, with an API key, the
  organization's workflows and their definitions. Results are cached for the Blender session.
- Selecting a model fetches `GET /v1/models/{slug}` in the background for its `cost` block.
- *Test connection* calls `GET /v1/billing/balance` and shows the balance or the API error text.

## Capability resolution and input binding

The model catalog declares, per model, an `output_type` and a `category` slug such as
`image-to-video`. It does not declare which request field takes which kind of media, or which
field is the first or last frame. The add-on therefore uses only what the API declares and asks
the user for the rest; it never guesses from field names.

**Output kind** is `output_type` when it is `image` or `video`; otherwise the output side of the
category slug (`*-to-image`, `*-to-video`).

**Accepted input kind** is the input side of the category slug (`image-to-*`, `video-to-*`,
`reference-to-*`). A model with no URI input field (`format: uri`, or an array of them) cannot take
a render and is never offered.

| Action | Offered models | Offered workflows |
|---|---|---|
| Generate Image | output kind `image` and input kind `image` | any workflow with an `image` input |
| Generate Video | output kind `video` and input kind `image`, `video` or `reference` | any workflow with an `image` or `video` input |

*Show all URL-input models* relaxes the input-kind check for models whose category under-declares
what they accept.

**Bindings.** Every URI field of the selected target is listed with a source selector:
*None*, *Rendered still* (image action), or *Clip (MP4)*, *First frame*, *Last frame* (video action).
A source is pre-selected only when declared metadata leaves one sensible choice: a model with
exactly one URI field and exactly one declared input kind (`image` or `video`), or a workflow with
exactly one input of a declared media type. That field gets the primary source for its kind:
*Rendered still* for an image in the image action, *Clip* for a video, and *First frame* for an
image in the video action. Everything else starts at *None* and the user chooses. *Last frame* is
never pre-selected, because no API field declares a frame role. Binding becomes automatic once
the API declares media kinds and frame roles per field.

**Prompt and seed** bind to the fields literally named `prompt` and `seed`, the catalog-wide
convention; models without them hide those controls. Other scalar fields (enums, numbers,
booleans, short strings) are listed as optional parameter overrides. Required fields that are not
supplied fall back to the schema's declared `default`; if a required field still has no value the
action stops before rendering and names the field. *Extra inputs (JSON)* merges arbitrary keys for
array or object fields.

## Files on disk

```text
<blend dir>/eachlabs/<blend name>/          # or <system temp>/eachlabs-blender/unsaved/
  <id>_still.png                            # image action input
  <id>_frames/frame_0001.png ...            # video action render, deleted once packaged
  <id>_clip.mp4
  <id>_first_frame.png
  <id>_last_frame.png
  <job>_result_1.png | .mp4                 # downloads
  <job>.json                                # job manifest: target, request input, remote ID, outputs
```

IDs look like `20261019-153012-a1b2`: local time plus four random hex digits, so names sort by time
and stay unique when two jobs start in the same second. A re-run gets a new job ID but keeps the
input set's ID on its input files. Unsaved files use the system temp directory, not Blender's
session temp directory, which Blender deletes on exit while strips and images still point at it.

## Timing reconciliation

Let the rendered range be `N` scene frames at scene fps `S = fps / fps_base`, and the result clip
have `F` frames at `R` fps (read from the loaded movie, since the API reports no fps).

- **Fit to rendered range** (default): the strip spans exactly `N` frames, so its playback speed is
  `F / N` source frames per timeline frame. This matches the brief's acceptance criterion and
  keeps the result aligned with the render it came from, even when a model returns a different
  duration.
- **Keep source timing**: the strip plays at real time, spanning `round(F * S / R)` frames.

When the target span equals `F`, the movie strip is used as is. Otherwise the movie strip is trimmed
or extended to the target span and a *Speed Control* effect in *Stretch* mode, on the next free
channel, plays all `F` source frames across it. The movie strip itself sits on the first channel
free over the range.

## Scene chat

The person types one prompt in the bar, such as `a street at dusk, slow dolly forward over 5 seconds`.
The scene fills in stage by stage in the viewport. Pressing Play then shows the camera move.

### How a run works

The model is `openai/gpt-6-sol` by default, called through `POST /v1/chat/completions` with the
add-on's API key as `Authorization: Bearer`. The `materials` and `light` stages go to a second model,
`anthropic/claude-sonnet-5.5` by default (Preferences, *Light and materials model*), with that model's own
reply cap (`chat/stage_models.py`). The detail stage of the high-detail objects goes to a third model,
`openai/gpt-6-astra` by default (*Main objects' detail model*); the plan's cost estimate prices all three. Sonnet
gave the richer light and materials, GPT-6 Sol the more complete builds, GPT-6 Astra the best single objects. It gets three tools in every stage: `run_python` (one step
of Blender Python, run by `code_runner` after `code_check`), `read_scene` and `camera_view`.

| Stage | Builds | Rounds |
|---|---|---|
| `layout` | the ground, the shapes and the props, as plain geometry | 4 |
| `materials` | a Principled BSDF material for each object | 3 |
| `light` | lights, the world and the EEVEE look | 3 |
| `camera` | the camera and its keyed move: build, measure with `camera_view`, fix | 3 |
| `check` | reads the scene and the camera view, fixes what is clearly wrong | 2 |

- Stages run in order, without stopping for approval.
- **What the stages ask for:** the details a person expects in the place, each thing built from several
  parts, bevels, procedural textures, and a real light of matching colour at every light source the scene
  shows. Without them a scene was a few plain boxes lit flat by the person's own default light, and emission
  alone barely lit its surroundings. The person's own lights do not count.
- The light stage's first step adds the lights and a visible glowing shape for each light source the prompt
  names (flames for a fire). Night keeps the world's background strength at about 0.05 or less, dusk at about
  0.1-0.3, and the check stage reads that strength, not only the colour. The materials
  stage's first step gives every mesh a material in one loop. The check reply describes only what
  `read_scene` and `camera_view` show.
- **A stage ends when the model answers without a tool call**, or at its round budget. The model is told
  the scene is already in its message, so it builds at once, and that the check stage does the checking.
- **A light stage that leaves no lights of the run's own** gets one more round, once per run, with a note to
  add them now. The check stage gives that round back. The check stage also looks for a dark frame and for
  light that does not match the time of day the prompt asks for.
- The check stage's message also holds `camera_view`. Its last round is sent without tools and asks for
  the one- or two-sentence reply, which the bar shows.
- **Each stage starts fresh:** its instructions, the prompt, a summary of each earlier `run_python` step
  of this run (what it created, removed or changed; never its code; the last 30) and a `read_scene` result.
- **`read_scene` lists every object the run built.** Three or more objects of one kind (the same name
  apart from its numbers, type and materials) are one entry: the first and the last name, the name
  pattern, the count and the space they fill. An object whose geometry sits away from its origin also
  lists its world bounds. Without these, a 150-object street did not fit and the model spent whole
  stages printing the scene instead of building.
- **`read_scene` lists the chat's things that stand on or inside another thing of its own** (`overlaps`).
  - A thing is a group of `loose_parts`, or an object in no group. Only things 1 m tall or more are checked.
    Names that start with the same word (`House | roof`, `House | walls`; `Car`, `Car_Tyre_1`) are one thing.
  - **On:** its bottom rests on the top of a part of the other thing, at least 0.5 m above that thing's base
    (a person on a car roof, not a building on a low plinth). **Inside:** a quarter of its box or more is inside
    one part of the other thing that is 0.5 m thick or more (not a window in a wall).
  - Only the chat's own objects are measured and named. The check stage gets each entry as something to fix
    unless it belongs there; the rules ask for every part to be built at its final place first.
- **`read_scene` lists the chat's figures and objects whose parts float apart** (`loose_parts`).
  - A group is one parent of the chat's with everything under it, or the chat's objects that share a name start
    (`Person_A_*`).
  - Copies that differ only by a last number (`Car_Tyre_1` to `_4`) are not a group.
  - Two parts touch when their world boxes are 5 cm apart or less. Each group gives its part and piece counts and
    the parts apart from the rest. Only the chat's own objects are measured.
  - The check stage gets each group by name. The rules ask for parts that touch, joined or parented to one empty
    with `part.matrix_parent_inverse = root.matrix_basis.inverted()`.
  - Before this, a follow-up parented arms built in world coordinates to an empty without it, and they floated at
    twice the empty's offset.
- Every tool result passes through `code_check.redact` before it reaches the model.
- **Debug log, off by default.** Set `EACHLABS_CHAT_LOG` to a file path, and every model call's messages and
  reply are appended to it as JSON lines.
  - It holds the prompts, the scene summaries, the code the model wrote and what that code printed.
  - The printed output can include names of your own objects, through the gap described under privacy below.
  - The API key is redacted, and request headers are never written.
  - The file grows with every call: delete it when you are done debugging.
- `camera_view` measures, at the first and the last frame, each chat object's share of the frame from its
  bounding box, whether the frame cuts it off, the empty share of the frame, and objects behind the camera.
  It also gives the share and count of the person's objects in view (never their names), whether rays in
  four directions all meet the chat's objects (`camera_enclosed`), and the first object between the
  camera and its aim point. The camera stage keeps an interior camera enclosed, the person's share under 10%
  and the subject at 15% or more of the last frame; the check stage looks for the same, and its message names each such problem `camera_view` measured.
  - The subject is the chat's root object the aim meets at the first frame. For a moving camera, `during_move`
    gives its share of the frame at a quarter, half and three quarters of the move, and the chat object that
    hides it. The check stage is told when it leaves the frame or is hidden. The visual check also renders the
    middle frame of a move.
- `read_scene` checks the footing of the root objects a run made: a ray down through each one's middle names
  the surface it stands on when the model marked that surface `obj["walkable"] = False` (water), and a ray up
  names the chat's object right over it. `free_space` leaves such surfaces out.
  - `sunk_into`: at nine points of a thing's footprint, a ray up finds its own base and a ray down from its top
    finds the highest upward surface of another object; a base more than 3 cm below that surface, with nothing
    of the thing in between, is sunk (a cat inside a cushion; a book between shelf boards is not).
  - `open_holes` and `flipped_normals` (`SceneBuild.mesh_health`): the run's meshes, with modifiers, that have
    open edge loops of 4 cm or more (a missing face, an uncapped tube) or faces turned against their neighbours.
    Flat sheets are open on purpose and not checked.
- A follow-up that adds things keeps each as its own object: the request's note says so when it names an
  object only as a place (`intent.target_note`), and `chat_run._apart` makes a new group (an empty with geometry)
  that a step parented to an older object a root where it stands. An edit's new pieces still join its target.
- With the visual check on, an edit ends with a look through the scene camera and a round to put what was asked
  for where the camera sees it.
- EEVEE fits about 12 shadow-casting lights. `read_scene` reports more, and `end_stage` turns off the shadows of
  the weakest lights past it (`shadows_turned_off`). When any light of the chat's casts shadows it also raises
  the scene's EEVEE shadow pool from 512 to 1024 MB: six large area lights already overflowed the default one.
- **A follow-up keeps the camera move.**
  - `read_scene` (`camera.move_m`) and `camera_view` (`camera_move_m`) give how far the scene camera moves from the
    first to the last frame, read from its location keys.
  - A step that changes the frame range and leaves the run's camera keys alone gets its two keys moved to the new
    first and last frame, and is told so.
  - A step that stops a move of 0.1 m or more is told so. The camera and check stages get the problem by name, and
    are told to shift both keys by one offset when they reframe.
  - Before this, a follow-up's reframe keyed one position at both frames, and the camera stood still.

**Follow-up prompts change the current scene.** A prompt in the same file and scene continues the last
run's `SceneBuild`: same run tag, same collection, and `read_scene` lists everything the chat built so far.

| Case | Next prompt |
|---|---|
| A scene was built here, its collection exists | follow-up: same collection |
| **New scene** pressed (`eachlabs.chat_new_scene`) | new `SceneBuild`, new collection; nothing deleted |
| The collection was deleted, another scene is active, or a file was opened | new scene |
| *Retry stage* | the same scene, with the same prompt |

- A follow-up's stages get change instructions: keep what fits, change or remove what the request
  changes, add what it asks for, do not rebuild. A stage with nothing to change answers with one
  sentence and no tool calls, so it pushes no undo step.
- The user message starts with `Change request:` and lists up to **3** earlier prompts of this scene,
  most recent first, each cut to 200 characters.
- A follow-up does not move the view when `layout` ends.
- A stage ends when the model answers with text and no tool calls.
- Units are metres, Z is up, the ground is at z = 0.

| Limit | Default | When reached |
|---|---|---|
| Rounds per run | **15**, the sum of the stage budgets | the run stops: `Stopped after 15 rounds. What was built is kept.` |
| Rounds per stage | the table above | the next stage starts, so `camera` always runs |
| Failures of one tool in a row | **3** | the run stops: `Stopped: <tool> kept failing: <error>`; a step that returns an error counts |
| Seconds per step | **20** (5-120), `chat_step_seconds` | the step is stopped and answers a `TimeoutError`; the worker waits 15 s longer |
| Seconds per model reply | **120** (30-600), `model_reply_wait_seconds` | the stage counts it as a failed round; the texture (240 s), concept picture (120 s) and download (120 s) waits are preferences too |
| Code check refusals in a row | **3** | the run stops: `Code check stopped the run: <reason>` |
| Tool calls per reply | **8** | the rest are answered with an error asking for them in the next reply |

Rounds per run (5-16: the stage budgets plus the one extra light round), seconds per step, failures and Code check are in the add-on preferences
(*Chat*); the per-stage rounds and the three refusals are constants. Code check is also a checkbox in
the sidebar.
A bad tool argument goes back to the model as an error it can act on. An HTTP error ends the run
with one line; a rejected key shows `API key was rejected (HTTP 401).`

> **Why fresh context per stage:** resending the history grows every round. A stage that carries only
> the scene read stays small, and reading the scene back is what lets `check` fix it.

### Running the model's code

> **This is not a sandbox.** The filter refuses the obvious ways out of the scene. Code that passes it
> runs inside Blender with Blender's full access. Blender's Python can reach files and the network in
> ways a source check cannot see.

Every `run_python` step goes through the same path:

```text
consent (start) -> [Code check] -> rule filter -> code runner -> summary -> redact -> model
```

| Part | What it does |
|---|---|
| **Consent** | `chat_code_consent` is `UNSET` or `ALLOWED`. `chat_run.start()` refuses to start while it is `UNSET` and opens the consent card. Send, Retry stage and the sidebar all call `start()`. |
| **Rule filter** (`code_check.check`) | Reads the step as source without running it. Refuses with the name of the rule and the line, so the model can rewrite the step. A refused step does not run. |
| **Code check** (`code_review.review`) | **Turned off and hidden** (`tokens.CODE_CHECK_AVAILABLE`): it blocked ordinary build steps after the layout. One extra model call reads the step before it runs. See below. |
| **Code runner** (`code_runner.run`) | Runs the step in a fresh namespace under the step time limit, on Blender's main thread only. Empties the API key in the preferences while the step runs and checks the add-on's settings after it. |
| **Redaction** (`code_check.redact`) | Replaces exact copies of the API key in every result and in the saved code. |

**What the filter allows**

| Allowed | Refused |
|---|---|
| Imports of `bpy`, `bmesh`, `mathutils`, `math`, `random` | Any other import, relative imports, `os`, `sys`, `subprocess`, `socket` and similar |
| `bpy.data`, `bmesh`, and `bpy.ops.` `object`, `mesh`, `curve`, `material`, `node`, `transform`, `view3d`, `anim`, `scene` | Other `bpy.ops` modules, and import, export, save, load or pack operators |
| Plain attribute access and calls | `open`, `eval`, `exec`, `compile`, `getattr` with a name that is not a string literal |
| `except Exception` and named built-in errors | `except` with nothing, `BaseException`, `KeyboardInterrupt`, `return` or `break` inside `finally` (the time limit must be able to stop a step) |
| Defining functions and classes | Names and attributes that start with `_` (except `__name__`, `__init__`, `__repr__`, `__str__`) and frame or code internals |
| Own materials, nodes, lights, cameras and keyframes | `bpy.ops.wm`, preferences, add-ons, `bpy.app.handlers`, `bpy.app.timers`, drivers and expressions, `bpy.data.texts`, file paths and `save` calls |
| | Names that contain `api_key`, `token`, `secret` or `password`, and any use of the add-on's preferences |
| | On Blender 4.2 only: `temp_override`, and `bpy.ops.object.quick_fur`, `quick_explode`, `quick_smoke` and `quick_liquid`, which use it inside (see [Blender 4.2 and threads](#blender-42-and-threads)) |

- The filter allows a fixed set of code shapes and names and refuses everything else. A module value
  such as `bpy.ops` may only start an attribute chain, be called, or get a plain alias (`ops = bpy.ops`).
- It is a check for honest mistakes and obvious misuse. It does not stop a determined author.

**Code check** (`chat_code_check`, off by default)

- Runs only for a step that already passes the filter.
- Gets the step, the name of the chat's collection and the names of the chat's objects (at most 200).
  The add-on does not send it the person's object names. A step's code can still contain names the
  model learned from printed output or an error message.
- Allows a step only on a clear `allow: true`. An error, an unreadable reply or a missing object list
  **refuses** the step.
- A refused step does not run. The model is told why and writes it again.
- **Three refusals in a row** stop the run: `Code check stopped the run: <reason>`, with *Retry stage*
  offered.
- Its model calls count in the run's cost, because the cost is the balance difference.
- It is a second model reading code, not a guarantee. It can be wrong in both directions.

**The namespace and the time limit**

- A step gets `bpy`, `bmesh`, `mathutils`, `math` and `random`, and `scene`, the run's scene. Nothing
  else carries over from the step before.
- `math` and `random` are copies that hold only public functions and constants.
- `open`, `eval`, `exec`, `compile` and the other blocked names are removed from the step's builtins, and
  `import` allows the same five modules.
- The time limit is `chat_step_seconds` (default 20 s). A helper thread raises `StepTimeout` in the step.
  It is not an `Exception`, so a step's own `except Exception` cannot keep running. The step answers
  `TimeoutError`.
- Python checks for that exception only between Python lines. One long call into Blender, such as a
  heavy mesh operator, runs to its end, and Blender waits for it. The worker gives up after the limit
  plus 15 s and counts the step as failed, even when the call later changes the scene.
- The filter refuses the known ways to make Blender run a step's code later: handlers, timers, drivers
  and expressions.

**What the runner records**

- Objects the step creates move into the run's collection and get the run tags.
- Other new data (meshes, materials, lights, cameras, curves, node groups, images, worlds) gets the run tag.
- Empty collections the step made are removed.
- The result is a summary: `new_objects`, `removed_objects`, `new_materials`, `new_lights`, and the
  `world` or camera when the step changed them. Lists show at most 40 entries.
- **`touched_other`** is the number of the person's objects the step changed or deleted, found by
  comparing their position, parent, data, materials and visibility before and after. They are counted
  and never named. A scene with more than 5000 other objects is sampled, and the summary says so.
- A step that touched some gets a note not to change them. The check runs after the step, so it
  cannot undo the change; the stage's undo step can.
- Printed output (its first 2000 characters) and a trimmed traceback (20 lines) go back to the model.

**Privacy**

- The add-on sends only a **count** of the person's objects (`other_objects`). It does not send their
  names, materials, worlds or cameras.
- **The gap:** a step's own printed output and error messages go back to the model. A step that reads
  the person's objects and prints them, or fails on one, shows the model their names.
- The API key, from the preferences and from `EACHLABS_API_KEY`, is replaced by `[redacted]` in every tool
  result, in Code check's input and in the code shown to the person. This replaces exact copies only. An
  encoded or reversed key passes. The filter also refuses the code shapes it knows that read the
  add-on's settings. Both catch mistakes; neither is a guarantee.
- The prompt, the chat's own object names and the scene summaries are sent to the chat model, and
  Code check sends the step's code to it as well.
- **The visual check sends pictures.** With it on (the default), small renders of the scene go to the chat
  model. A render shows everything in the frame, **the person's own objects included**. The text sent with it
  names none of them. The PNG exists only in a temporary folder until it is read, and the debug log keeps a
  short mark instead of the picture.

**The key and the add-on's settings during a step**

- While a step runs, the API key field in the add-on preferences is **empty**. Every other preference
  whose value is one of the add-on's credentials is emptied too. Code that reads the preferences sees `""`.
- Each one is put back right after the step, on its own: after a normal step, an error, the time limit,
  and when the run was stopped meanwhile. The values from before live only in a local variable of `settings_guard.run_hidden`.
- Before the step the runner reads **every** add-on setting: the key, the API address, Code check, the
  consent, the round, step and failure limits, the video defaults. After the key is back it compares them.
- If the step changed any of them, every value is put back and the run stops:
  `A step changed the add-on's settings. They were put back and the run was stopped.` The model gets no
  answer to that step. The bar offers *Show code* and *New scene*.
- While the key is empty, Blender handles no UI event, timer or preferences save, because the step runs
  on Blender's main thread. The filter refuses the add-on's own operators and file loading, so a step
  cannot start a job, a catalog load or an MCP check.
- One read can still happen: a step that changes the model chosen in the add-on's scene settings makes
  the add-on fetch that model's price. That read sees the emptied key, so the key is not sent.
- What this does not cover:
  - **The add-on's own Python memory.** The run's API client is made when the run starts and keeps the
    key. Only the filter stands between a step and that copy.
  - **The `EACHLABS_API_KEY` environment variable.** It is not a preference; only the filter keeps a step
    away from it.
  - **The preferences file on disk.** Blender stores the key unencrypted in `userpref.blend`. Only the
    filter keeps a step from reading that file.
  - **The visual check's pictures.** `redact` works on text only. A picture shows what is in the scene, so
    anything a step managed to put on screen (the key written into a text object or into geometry) would be
    seen by the model. Only the filter keeps the key out of the scene.
  - **The filter itself** has not had an independent attempt to break it. Code that gets past it can do
    anything Blender's Python can. This is a check, not a sandbox.

**Show code**

- `chat_run.code_text()` writes the run's steps to the text `Eachlabs code`, one section per step, with
  its stage and whether it ran, failed or was refused.
- *Show code* opens it in a Text Editor: an open one, else a new window.

### Threads

```text
main thread                                   chat worker thread
-----------                                   ------------------
Enter in the bar -> chat_run.start ------->   balance, then per stage:
                                                model call (HTTPS)
dispatcher hook drains the chat queue <----   tool call queued, worker waits for its result
  -> scene_build runs it (code_runner, bpy.data)
  -> result handed back to the worker ----->  next tool call or next round
                                              balance again -> cost
```

- **The worker never touches `bpy`.** It posts events (stage, round, tool row, reply) and tool
  calls to a queue in `chat_run.py`.
- **A main-thread hook drains that queue.** It runs on every dispatcher tick and applies at most
  10 ms of queued work per tick, so Blender stays responsive while the scene grows.
- **Presses on the unfocused bar come through an invisible gizmo** (`EACHLABS_GGT_bar`, persistent
  in every 3D view). Its `test_select` hit-tests the bar, so it is highlighted only while the mouse is
  over it. Its own keymap sends left, right and middle presses to `gizmogroup.gizmo_tweak`; the
  gizmo acts on a left press and holds the press until its release. The tweak operator runs only
  while the button is down.
- A `LEFTMOUSE` press item in the 3D View keymap runs `eachlabs.bar_click` as the fallback for a
  press the gizmo did not see. It hit-tests the bar and passes the press through when it misses, so
  Blender's selection works everywhere else.

Which handler gets a `LEFTMOUSE` press on the bar first, probed in 4.2.23 and 5.2.3 with
`--enable-event-simulate`:

| Handler | 3D Cursor tool | Annotate tool | Sculpt brush (4.2) |
|---|---|---|---|
| Keymap item in `Window`, `Screen`, `3D View`, `3D View Generic` or `Object Non-modal` | runs, but the cursor also moves | never runs | never runs |
| Gizmo in the 3D view's main region | runs; the cursor stays | runs | runs |

> **Why a gizmo:** a region's handlers run in order: interface, gizmos, the active tool's keymap,
> then the editor keymaps. `Window` and `Screen` keymaps run after the region. A keymap item cannot
> come before the tool, and a modal operator at idle would turn autosave off.

- In sculpt and paint modes on 5.x, the asset shelf covers the bottom of the view. The bar sits
  above it.
- **The modal operator runs only while the bar has focus** (or a press on it is held). It takes the
  keys a text field owns and passes everything else through. It ends on `Esc`, on a click outside
  the bar, or when focus moves away. After a click outside, it ends on the next event that is not
  a mouse button: ending on the press or release would mark the click handled, and Blender would
  then send no `CLICK`, so click-select would not select.

> **Why not one modal operator all the time:** Blender postpones autosave while any window has a
> modal operator (`wm_autosave_timer` retries every 10 ms), so an always-running one turns autosave
> off for everyone with the add-on enabled.

- **`Esc` in the focused bar stops a running run** and gives the keys back. Unfocused, `Esc` is Blender's.
- **Stop** sets the run's cancel event. The worker checks it between rounds and between tool calls;
  what was built stays. Opening a file or disabling the add-on also cancels the run, and opening a
  file also clears what the bar shows about the last run (the prompt history stays).
- **Each model call asks for at most 5000 tokens** (`max_tokens`): replies that long took 28-35 s. The cap also
  counts the model's hidden reasoning, which can run to several thousand tokens before a stage's first
  step. The Eachlabs chat API ends a call at 60 s, and long code replies took about 40 s. The model is told to keep
  each step to about 80 lines, one per reply. A reply cut off at the limit does not run: the
  model is told so and the stage goes on. A reply that used all 5000 tokens counts as cut off, whatever its
  `finish_reason` says.
- **Anthropic models (`anthropic/*`) get 3000 tokens and steps of about 50 lines** (`chat_loop.REPLY_CAPS`).
  They write 90-130 tokens a second, so a full reply stays at 25-35 s. Every other model gets 5000 and 80 lines.
- **After a cut-off reply, the rest of that stage asks for no hidden reasoning.** A cut-off reply was usually
  all reasoning, with no text and no call, and asked again the model filled the cap again. In one follow-up, 9 of
  15 replies were like that, and the light stage ran nothing. Without reasoning, the same request came back in
  6-11 s with a step. The next stage starts with reasoning again.
- **The check stage and Code check reviews ask for no hidden reasoning**
  (`"reasoning": {"enabled": false}`), which the chat endpoint accepts for this model. Without it a call
  carried a few hundred to several thousand reasoning tokens and took up to twice as long. The camera stage keeps
  its reasoning: without it the model often sent the camera code as text, and no camera was built. An endpoint that
  answers that parameter with HTTP 400 gets the call again without it, and no longer gets it for the rest of the run.
  Anthropic models (`anthropic/*`) answer it with 400 "Reasoning is mandatory", so they never get it
  (`chat_loop.REASONING_REQUIRED`).
- A call that fails with HTTP 502, 503 or 504 is sent once more after 2 s, with the same messages; Code
  check reviews too. A review that fails again refuses the step. The
  lost call may still be billed, and the cost shown includes it.
- Any other error of the model call (HTTP, network, a body that breaks off), or a second failure, ends the
  run at that stage with one line and offers *Retry stage*. A rate limit shows
  `The model is busy, try again in a moment.`
- **A run that ends done but changed nothing says so.** `code_runner.fingerprint` is taken at the start and at
  the end: every datablock id, and the state of the run's objects, lights and world, the camera and the frame
  range. When they match, the done bar shows `Nothing in the scene changed. Try again or reword the request.`
  above the model's reply, and offers *Retry*, which runs every stage again with the same prompt in the same
  scene. The model's reply alone is not enough: it can describe what it meant to build.
- The cost is the balance before the run minus the balance after it.

### Scene ownership and undo

- Objects a step creates are moved into the run's own collection, `Eachlabs scene`.
- Every created object is tagged `eachlabs_id` (the id the model sees) and `eachlabs_run`.
- Objects are found again by their tags on every call, never by a kept Python reference. Undo and
  the person's edits replace datablocks.
- **The model is told to change only the run's own objects.** `read_scene` gives only a count of the
  person's objects (`other_objects`) and never names them, their materials, worlds or cameras. A step
  that changes some anyway is answered with that count (`touched_other`) and a note not to change
  them. This is a check after the step, not a guard.
- **The one exception is Blender's untouched startup Cube.** When a run starts a new scene, the add-on
  itself (not model code) deletes an object that is exactly the startup file's Cube, once the person
  pressed Build (`startup_cube.matches`: name, mesh used by it alone, 8 vertices at ±1, 6 faces, identity transform, no modifiers,
  parent, children, constraints or animation, and only Blender's default material), when nothing but its
  scenes and collections uses it. The person chose this: at the origin it stood in the middle of every shot. It runs on the main thread before the first step, so it is
  part of the layout stage's undo step, never counts as `touched_other`, and the model learns no name.
- The model makes its own world and assigns it. When a step replaces a world that no one uses any more,
  the build sets `use_fake_user = True` on it, because a world with no users is dropped on save.
- The collection is linked under the scene collection once. When the person moves it under another
  collection, it stays there.
- While any object is outside Object Mode, a step does not run and answers
  `Blender is busy in edit mode; try again in a moment.`
- A step whose own code leaves Blender in Edit, Sculpt or another mode is put back in Object Mode
  (`SceneBuild.leave_modes`, with no undo step of its own), and its result tells the model (`mode`).
- Each step gets `scene`, the run's scene, so the model does not depend on `bpy.context.scene`.
- A step that uses an object the person deleted gets the `KeyError` back as its error; no Python error
  reaches Blender. `read_scene` finds the run's objects by tag, so a renamed object is listed by its
  new name and a copy the person made is listed once.
- **One undo step per stage that changed the scene** (`ed.undo_push` with the stage name). *Retry
  stage* runs the stopped stage and the ones after it again.
- *Undo stage* runs `ed.undo` once, which undoes whatever step is active. So it is offered only while
  the active step is the chat's last stage, named `Eachlabs: <stage>`. The operator reads it again
  right before undoing and refuses otherwise.
- Python has no reader for the undo stack. `WindowManager.print_undo_steps()` prints it with C
  `printf` (`*` marks the active step; same format in 4.2 and 5.2). `undo_steps.py` points file
  descriptor 1 at a temporary file for that call, after `fflush`. It reads again after any
  `depsgraph_update_post`, `undo_post` or `redo_post`, and at least once a second while the pill shows.
- When the stack cannot be read (background mode, no standard output), tracking hides the pill
  instead: `undo_post`, `redo_post` and the person's edits seen in `depsgraph_update_post` (a moved
  object, a changed selection, active object or object count). The chat's own updates are told apart
  by tag during a run and by a short quiet window after each of its own changes.
- **Material Preview** once per run, when `light` ends: in the window the run was started from,
  every 3D view whose shading is `SOLID` switches to `MATERIAL`, so emission and lights show.
  `RENDERED`, `WIREFRAME` and `MATERIAL` are left as they are.
- **Framing** never touches the selection: the view is centred on the bounding box of the run's
  buildings and lamps and zoomed to fit, keeping its rotation. It happens once when `layout` ends
  (skipped while the view looks through the camera) and on *Frame result*.

### Detail stage

- **Where**: `chat_loop.ORDER` puts `detail` after `layout`. `chat_loop.run` runs it only when the caller passes
  a `detail` function (preference *Detail rounds* above 0); its rounds come on top of the total cap, and its
  step summaries join the run's, so later stages hear what it built.
- **Pick** (`detail.PICK`): one call without hidden reasoning gets the scene and the plan's main objects and
  answers JSON: root objects with a level (`high`, `medium`, or `light` for secondary things) and the parts to
  add. Only roots of the scene are kept (`detail.parse_pick`), at most 6 high or medium and 6 light. The add-on
  holds no list of kinds of objects. On a follow-up the choices are the roots the run made and the roots it
  points at.
- **Light** objects get *Secondary detail rounds* and no close-up.
- **Copies** (`chat_run._detail_copies`): after the rounds, a root whose name differs from a detailed one only
  in its trailing number, of a similar size and with fewer parts, is replaced by a duplicate of the detailed
  tree that shares its meshes, scaled and stood where the copy stood.
- **Rounds** (`detail.improve`): a conversation per object, `run_python` only, one step per reply. High gets
  *Detail rounds*, medium one less, and the close-up one more. Up to *Objects at once* conversations run on
  worker threads (counted by `thread_safety`); their steps go through the one `Executor`, so Blender runs them
  one at a time. One object's failure leaves it partly done and never stops the others.
- **Each step** (`chat_run._detail_step`, main thread): focus and an `EditGuard` on the object's tree for that
  one step, so a step that changes another object of the chat's has it put back and is told (`put_back`).
  New objects without a parent are parented to the object's root where they stand.
- **Close-up** (`visual_check.render_object`): Workbench, studio light, material colours (each material's Base Color, put back after), cavity; the object's
  tree alone (every other object `hide_render` for the frames), from four sides, 512 x 384. Everything is put
  back in a `finally`. `SceneBuild.part_gaps` measures the parts' surfaces (with modifiers) and lists the parts
  that miss the rest of the object by 1 to 30 cm, and small parts that stand off a part at least twice their size
  along their thinnest side with nothing in front (`stands_off`: a window frame in front of its wall, even when
  another part joins them). The close-up message names them and the object's `open_holes`.
- **Reference pictures** (on by default): the plan's high-detail code items (at most 4) get a `nano-banana-pro`
  picture ($0.15) of the object alone after *Build*, one thread each while the layout is built. The detail stage
  waits for the one whose item name its object is named after, up to the concept picture's wait limit.
- **Building to the picture** (`detail_compare`): after each detail round with rounds left, a close-up of the
  object and its picture go to the scene's quick model, which lists at most five differences (proportions,
  missing parts, colours, pose) or answers `MATCHES`; the list is the next round's note. The final close-up shows
  the picture first.
- **Instructions**: `chat_loop.SHAPES` (subdivision, inset and extrude, mirror, array, cone and spin, curves,
  solidify) goes to the layout, detail, complete and edit stages; every example runs in `tests/smoke.py` on
  both Blenders.

### Generated 3D objects

- **Only solid pieces**: a generated model is one closed shell, so the plan (`plan3d.INSTRUCTIONS`) offers 3D
  only for a solid single piece with no parts (a statue, a boulder). Every item carries `solid`; only a solid
  one moves between 3D and code (`Plan.toggle`), and "realistic" words move only a solid one (`bind`). An
  upgrade in place (`upgrade`) returns `None` for anything with parts, and the change adds detail in code.
- **Plan** (`plan3d`): with *3D objects* not *Off* or *Reference pictures* on, a full run starts with one model
  call without hidden reasoning that answers JSON: the 3D items with a tier, and the code items with a detail
  level. The plan is shown only when it has something to decide or pay for (`Plan.asks`). The worker waits on
  the plan until *Build* or *Cancel*; Stop on the plan is its Cancel. On *Build* the add-on queues a job for
  every approved 3D item itself (the model has no tool for it), so nothing approved depends on the model
  asking.
- **Workflow** (`workflow_3d`): one per API URL, id and version in `workflow-3d.json` in the user folder.
  Every version carries `metadata.addon` and `metadata.def`; `ensure` makes a new workflow or version when the
  stored one is gone or older, and a trigger answered 404 makes a new one and tries once more. Tier settings
  are trigger inputs (`octree`, `steps`), referenced as whole values so they stay numbers. The picture prompt
  is the chat's own, one per item from the plan (`picture_prompt`); the workflow only adds "plain white
  background, no floor, no shadow, no other objects". The add-on keeps no knowledge of kinds of objects.
- **Size**: the plan gives each item `size_m` along `measure` (height or length); the swapped-in model takes
  exactly that size, every copy alike. Without it, the code version's longest side. Wrong sizes are for the
  visual check to catch, not for code.
- **Jobs** (`generation`): one 3D run at a time, from a queue, large tier first, then the plan's order: runs at
  the same time were each 3-8 times slower. Each job's wait limit (preference, 20 min) counts from its
  trigger, not from when it was queued. One worker thread per job, polling every 4 s, never touching `bpy`. It
  downloads the zip at once (the provider's link expires), takes `*_pbr.glb`, and stores it in the cache
  (`asset_cache`, key = lowercase description + tier, 2 GB, least recently used go first).
- **Import** (`glb`, `objects_3d`): the GLB is parsed in plain Python and built with `bpy.data` on the main
  thread between steps, so no import operator runs (the Blender 4.2 `temp_override` rule does not apply).
  One mesh scaled to the first code version, base at z = 0; each copy is a linked duplicate. A step that changes a generated object's materials or modifiers is undone.
- **Placeholders**: the layout stage is told to build a code version of each approved object, one root object
  per copy named after the item ("Trees", "Trees 2"). The add-on finds them by that name and tags them, parts
  included, `eachlabs_placeholder`. A ready model waits for its code version; the model swaps in at each code version's place (footprint middle, lowest point), turn and longest side, lined
  up with its long side, then the code versions are removed and an undo step is pushed. A job that fails
  leaves its code versions as ordinary objects; the model is told at the next stage start, and the reply has
  one line per such object.
- **Every plan item in the scene**: after the layout and after the check, the add-on lists the plan's items
  that are not in the scene (a 3D item by its code version's exact name or its arrived model, a code item by
  an object named after it). What is missing gets a `complete` stage of up to 2 rounds within the total cap;
  the check stage is told too, so its reply does not describe them. The reply gets `<item> was not built.`
  for each one still missing.
- **Free space** (geometry only): `read_scene` gives the extent of the chat's flat ground pieces and the three
  biggest empty rectangles on it, measured on a grid from the footprints of everything else of its own. On a
  change, the add-on keeps the names of what existed before; a new thing whose footprint shares more than 10%
  with one of them is in `overlaps` as `overlaps_existing` (with `no free area fits … extend the ground` when
  no empty rectangle takes it), and the check stage counts it as clearly wrong.
- **Waiting**: the stages never wait. After the check stage the worker waits until no job is queued or
  running (each job ends at its limit), with the queue in the bar; Stop cancels the jobs.

### Visual check

`visual_check.render` makes a small frame on the main thread; `chat_loop` decides when and sends it.

| When | Frames | Then |
|---|---|---|
| `layout`, `light`, `camera` end | first; `camera` also the last when the camera moves | one more round of that stage, with the picture |
| `check` starts (2 rounds or more left) | first, and the last when the camera moves | the picture goes with the scene and `camera_view` |

- The message is the picture with one line: `This is what the camera sees now. Fix anything clearly wrong: …`.
  Two frames are labelled `Frame <n>:`. The add-on judges nothing in the picture; the model does.
- **Limits:** one render per stage, at most two frames. With the check on, the total cap is raised by
  `LOOK_ROUNDS` (3), one per extra round. At the person's cap alone, the extra rounds used the camera's and the
  check's share, and those two stages got no picture. A stage gets its render only while the cap leaves a round
  for it. A render that fails or finds nothing to show is skipped.
- **The layout's picture** has no materials or lights yet, so it adds one line: judge only the shapes. Without
  it the model lit the scene in the layout stage.
- **Camera:** the chat's own scene camera; else a temporary overview camera, 30° up and 30° round from the
  front, fitted to `frame_targets`, removed in a `finally`. The model is told it is an overview.
- **Settings:** EEVEE, the long side 640 px with the scene's aspect, at most 8 samples, no motion blur,
  compositor, sequencer, border or transparent film, PNG to a temporary folder. All are put back in a
  `finally`, with the scene camera and the current frame.
- **Measured** (EEVEE, 5.2.3, two frames, Part B scenes): 1.1-1.3 s per frame on a street of 2,401 objects,
  0.4-0.5 s on a room of 374. The first frame of a session on 4.2 took 4 s, mostly shader compiling.
- **A model that refuses pictures:** a call with a picture answered with HTTP 400 is sent again without
  pictures (a render becomes a text check, the concept picture is dropped), and the run sends no more. The model
  id is kept for the session: no visual check and no concept picture for it.
- **Threads:** the stage loop asks for the render through the executor, so it runs in the main-thread queue
  while the worker waits. It calls `bpy.ops.render.render(write_still=True)` with no `temp_override`, which is
  safe on Blender 4.2 (see below). The UI pauses for the frame. A render the person started skips the check.

### Scene review

A separate call judges the finished scene; `chat/review.py` decides (no `bpy`), `chat/review_run.py` renders and
undoes on the main thread.

| Step | What happens |
|---|---|
| When | once, after the check stage and any complete stage after it; only on a full run (no find, edit or retry) |
| Pictures | the visual check's camera frame, and three `look_around` views (Workbench, 384 px) fitted to the plan's main things, everything shown |
| Call | the scene's model, no tools: the person's request and earlier requests, the inventory lines, the pictures; JSON only |
| Guards | at most 3 problems; the thing must be an exact inventory name; a fix that removes, deletes, drops or erases is dropped; no JSON or nothing valid is no review |
| Fix | one fix stage (2 rounds) with the problems next to the measured ones, only when both rounds fit the person's limit; not counted against `FIX_MAX` |
| Second look | the same four views again; the quick model gets both sets and answers `solved` per problem and `worse` |
| Worse | `ed.undo` once, only when the fix stage is the one undo step pushed since the review and the active step |
| Reply | the check's reply stays; one line `Review: … — fixed.` or `(not fixed)`, two problems then `and N more` |

- The review's `missing` list goes to the debug log only: building from an unchecked list would add duplicates.
- **Undo during a run:** `ed.undo` needs a window, so it runs under `temp_override`. On Blender 4.2 that is never
  done during a run (see [Blender 4.2 and threads](#blender-42-and-threads)): the fix stays, and the line says Undo
  stage takes it back. Background mode has no undo steps, so the smoke test checks the
  request and the GUI check the undo itself.

### The prompt bar

The bar is drawn with Skia into an RGBA image. That image becomes a GPU texture, drawn as one quad
in a `POST_PIXEL` handler with premultiplied alpha. It is re-rasterized only when the bar changes.

> **Why Skia:** the bar needs smooth pills, shadows, real typography and icons. Blender's `gpu` and
> `blf` modules would need a hand-written shader per effect and cannot lay out rich text.

- **Fonts are loaded by path only.** The bundled Inter and Geist Mono come first. Characters they lack
  (symbols, emoji, CJK) use Blender's own font files, also by path.
- **Never use system font matching.** It can crash `skia-python` on macOS.
- Without Skia the overlay is not registered, and the sidebar shows a plain prompt instead.
- Any error while drawing or handling input is printed and the event passes through.
- **The done card folds to one line** `FOLD_AFTER` (4 s) after it first shows. After that it opens while the
  mouse is on the bar and folds as soon as it leaves. `bar_state.foldable` keeps every card that waits for a
  choice open; `viewport/fold.py` notes when the card first showed and redraws once for the first fold.

### Highlights

`viewport_marks.py` draws in 3D space in a `POST_VIEW` handler. New objects flash with an orange
outline for 1.2 s. Once the scene camera is the chat's and its location is keyed, its path from the first
to the last frame shows as a dashed orange line.
The GPU state is restored after each draw.

### MCP line

The sidebar shows the MCP connection, checked with the API key as Bearer. The public API
`https://api.eachlabs.ai` pairs with `https://mcp.eachlabs.ai/mcp`. Any other API URL needs
`EACHLABS_MCP_URL`. The run does not depend on it: MCP tools are not sent to the model.

### Packaging

- Skia ships as `skia-python` wheels, pinned in `scripts/build.sh`.
- The build makes **one zip per platform**: `macos_arm64`, `macos_x64`, `windows_x64`, `linux_x64`.
- Each zip holds wheels for Python 3.11 (Blender 4.2) and 3.13 (Blender 5.2).
- The wheels are downloaded at build time and checked against `scripts/skia-wheels.sha256`. They are not committed.
- They use the numpy Blender ships.

## Version differences

Sequencer and video output. Every row was verified by probe scripts on Blender 4.2.23 LTS and
5.2.2 LTS; the rows that `tests/smoke.py` exercises (strip collection, effect strips, video output,
timing names, strip speed by Speed Control) were checked again on 5.2.3 LTS. The two retiming-key
crashes were seen on 4.2.23 and 5.2.2 only:

| Concern | 4.2 | 5.x | Handling |
|---|---|---|---|
| Strip collection | `sequence_editor.sequences`, `MovieSequence` | `sequence_editor.strips`, `MovieStrip` | `compat.strips()` |
| Effect strips | `new_effect(..., seq1=)` | `new_effect(..., length=, input1=)` | `compat.new_speed_effect()` |
| Video output | `image_settings.file_format = 'FFMPEG'` | set `image_settings.media_type = 'VIDEO'` first | `compat.set_video_output()` |
| Strip timing names | `frame_final_start/end/duration`, `frame_duration` | `left_handle`, `right_handle`, `duration`, `content_duration` (old names removed in 6.0) | `compat.strip_start()` and friends |
| Strip speed | `retiming_keys.add()` crashes Blender | retiming keys resolve to the wrong strip when the sequencer holds more than one strip, then crash on write | both: set the movie strip's length to `N` and add a *Speed Control* effect in *Stretch* mode |
| Sequencer scene | the active scene | a workspace may show a separate `sequencer_scene` | import into the workspace's sequencer scene when set, else the rendered scene |

Scene building and the prompt bar. Every row was verified on Blender 4.2.23 LTS and 5.2.3 LTS
(not on 5.2.2) and is checked by `tests/smoke.py` and `scripts/gui-check.sh` on both. The model's
instructions carry the Blender 4 or the Blender 5 notes, chosen by `bpy.app.version`; `test_version_notes`
runs each of their API lines through the rule filter on both versions:

| Concern | 4.2 | 5.x | Handling |
|---|---|---|---|
| Sky Texture type | `NISHITA`, `HOSEK_WILKIE`, `PREETHAM` | `NISHITA` removed; `SINGLE_SCATTERING`, `MULTIPLE_SCATTERING`, `PREETHAM`, `HOSEK_WILKIE` | the instructions list this version's types |
| F-curves of an object | `action.fcurves`; no `Action.layers` | `action.fcurves` removed; curves live in the action slot's channelbag | `compat.object_fcurves()` reads the camera keys; the instructions say to animate with `keyframe_insert(..., frame=)`, and on 4.x that the keys are in `action.fcurves` |
| World colour | the Background node; `World.diffuse_color` does not exist | same | the instructions give the Background node lines |
| Compositor | `scene.node_tree` | removed | the instructions say not to touch the compositor |
| EEVEE engine id | `BLENDER_EEVEE_NEXT` | `BLENDER_EEVEE` | the instructions name this version's id |
| Material and world nodes | new materials and worlds have no node tree until `use_nodes = True` | always have a node tree; `use_nodes` deprecated (removed in 6.0) | the instructions say to set `use_nodes` only when `node_tree` is `None` |
| Python for the Skia wheels | 3.11 | 3.13 from 5.1 (5.0 still 3.11) | both wheels in every platform zip; Blender picks the one for its Python |
| Undo step from a script | `ed.undo_push` crashes in background mode | same | skipped when `bpy.app.background` |
| Bar shortcut | `Shift+Alt+Space` is unbound in the default keymaps | same | the add-on maps it to focus the bar in the 3D view |
| Autosave | postponed while any modal operator runs | same | the bar's modal operator runs only while the bar has focus |

The Speed Control mechanism is checked in `tests/smoke.py` on both versions by rendering the
sequencer over a clip whose frames have unique gray levels: the stretched (60-frame), compressed
(24-frame) and unchanged (48-frame) strips show the same source frame at the same proportional
positions. The retiming-key crashes are Blender bugs worth reporting upstream; the Python retiming
API can replace the effect strip once they are fixed.

## Blender 4.2 and threads

Blender 4.2 runs Python 3.11. There, an operator called through `bpy.ops` inside
`context.temp_override(...)` can read Python data without holding the GIL. If another Python thread
runs at that moment, Python's memory is damaged and Blender crashes. The crash is in Blender, not in
the add-on, and it was reproduced without the add-on. Python 3.12 fixed the check, so Blender 5.x is
not affected.

While a chat run is going, the chat's worker thread runs Python. So do the generation workers of its 3D objects
and textures (`eachlabs-gen-*`), and they can outlive the run: a stopped worker ends at its next status read or
download chunk. `thread_safety` counts both kinds from just before they start until they return. On Python before
3.12, while any of them runs, the add-on therefore never calls `bpy.ops` under `temp_override` itself:

| Path | During a chat run on 4.2 |
|---|---|
| Show code | opens the new window from the button's own window, with no override; with no window, it opens nothing and says the code is in the text `Eachlabs code` |
| Model-written steps | the rule filter refuses `temp_override`, and the instructions tell the model to call operators without it or to use `bpy.data` and `bmesh` |
| Blender's own operators that use `temp_override` | the filter also refuses `object.quick_fur`, `object.quick_explode`, `object.quick_smoke` and `object.quick_liquid`. Blender 4.2 runs their Python with operators inside `temp_override`. They are the only such operators in the modules the filter allows |
| Viewport snapshot for Generate | refused with `Wait for the scene chat and its 3D objects to finish, then try again.` |
| Clip packaging after a video render | waits until the chat run ends |
| Showing a result image | uses an open Image Editor only; with none, the job says to open the image once the chat finishes |
| Visual check render | runs on the main thread with `bpy.ops.render.render` and no override, so it is not affected |
| Scene review's undo | `ed.undo` under `temp_override` only while the chat worker that waits for it is the only worker; else the fix stays and the reply says so |

Operators called without `temp_override`, such as Blender's own clicks and draws, are not affected.

**Remaining limits**, on Blender 4.2 only. Blender 5.x is not affected.

- Another add-on, or a script of your own, that calls operators inside `temp_override` while a chat
  run is building can still crash Blender 4.2.
- Outside a chat run, a Generate job's worker thread checks the job's progress in the background.
  A viewport snapshot, or a new Image Editor opened for a result, uses `temp_override` while that
  thread may run. This is the same crash in principle. The chance is small, because the worker
  mostly waits for the network.

## Adding depth, normal or mask passes

Render export produces named *conditioning inputs*, not fixed files. An input set is a mapping from
a source role (`still`, `clip`, `first_frame`, `last_frame`) to a file plus its media kind; bindings
map request fields to roles. Adding a pass means:

1. Add a role (for example `depth_clip` or `mask_first_frame`) and its exporter in
   `render_export.py`, typically by enabling the pass on the view layer and writing it through the
   compositor's File Output node during the same frame-range render.
2. Register the role's label and media kind in `capabilities.SOURCES` so it appears in the binding
   selectors.

The job worker, uploads, re-run storage and bindings already treat roles generically, so nothing
else changes. Pass-specific options (depth normalization, mask object selection) would live in a
collapsible *Conditioning* panel.

## Errors and panel states

Every failure reaches the panel as one readable line: API errors show the HTTP status and the API's
own `error`/`message` text; an empty 401 body becomes "Invalid or missing API key (HTTP 401)";
network failures show the cause; a failed prediction shows the prediction's error or logs. The
panel shows each job's action, target, state, elapsed time and error, with Cancel while active.
When online access is off, both sidebars show how to enable it and every network operator stops
with that message instead of raising.

## Testing

- `tests/test_*.py` (standard `unittest`, no Blender): API client against a local HTTP server
  (paging, auth header, presign and PUT, error text, cancel, downloads), capability filtering and
  binding, fps math, file naming, and the job worker with a fake client (success, failure,
  cancellation).
- `tests/smoke.py` (`blender --background --python tests/smoke.py`): registers the add-on, builds a
  48-frame camera orbit, exports a still, a clip and first/last frames, imports an image, sets the
  camera background, imports a clip at a different fps and checks the strip's start, channel and
  length, checks the gray-level timing, and checks that offline mode yields a message, not an
  exception. No network.
- The unit tests also cover the chat: the stage loop with a fake model (caps, failures, cancel,
  malformed replies), scene tool arguments, the chat and MCP clients, the text field and the bar
  drawn to pixels. These need `skia-python` in the environment.
- `tests/smoke.py` also builds a street with the scene tools on both Blender versions: tags, copies,
  deleted objects, undo per stage, the chat run with a fake model, and the highlights.
- `scripts/gui-check.sh` runs `tests/gui_check.py` in a real Blender window. Its `bar` mode drives the
  prompt bar with simulated clicks and keys and a fake model.
- `scripts/` holds the build, validate and clean-profile install checks and an opt-in live
  end-to-end script that needs an API key.

## Default video model, inputs and duration

Most generations use one model, so the add-on preferences hold a *default video model*: a slug, a
JSON map of input bindings and a JSON map of parameter overrides (shipped:
`bytedance-seedance-2-5-reference-to-video`, `{"video_urls": "clip"}`,
`{"resolution": "480p", "draft": true}`). It is applied when the catalog loads and the video target
is empty, or on demand; bindings and parameters the model lacks are skipped and reported. This is
configuration, not capability inference: the model list and its fields still come from the API.

A binding can also take a **user-picked file** (`capabilities.SOURCES["file"]`). Its upload role is
`file:<field>`, so several fields can carry different files; rendered inputs are reused across
re-runs, picked files are uploaded again.

**Matching duration.** When the target has a `duration` input and the user has not overridden it,
the request asks for the rendered length: the shortest enumerated value that covers it (Seedance
takes strings `"4"` to `"30"`), or a rounded, clamped number. Results then need no retiming, which keeps
generated audio in sync.

## Audio and export

Imported clips get a sound strip on the next free channel (`importers._add_sound`). A file without an
audio stream yields a one-frame strip, which is removed. Sound strips have no speed property and
their retiming keys crash Blender from Python, so when the picture is stretched the sound is added
muted. Generators often return a frame or two past the request (Seedance 2.5 gives 241 frames for
10 s), so a surplus of up to `timing.TAIL_TOLERANCE` frames is trimmed instead of stretched and the
sound stays live. Importing audio switches a *Play Every Frame* scene to *Sync to Audio* for live playback.

*Export movie* renders the sequencer over the span of its strips to H.264 MP4 with AAC sound, using
the same settings snapshot and restore as input renders (FFmpeg settings included), as a job in the
panel.

## Decisions

| Topic | Decision |
|---|---|
| Input binding | Manual for multi-input models until the API declares media kinds and frame roles; never by field name |
| Default video model | Seedance 2.5 reference-to-video, draft, 480p |
| Timing | *Fit to range*, with *Match duration* on so most results need no stretch |
| Audio | Imported as sound strips; muted when the picture is stretched |
| License | GPL-3.0-or-later, as Blender's FAQ requires for published add-ons; distributed from a self-hosted extensions repository, since extensions.blender.org excludes add-ons that need a key or payment |
| Packaging | One zip per platform, because the bar needs Skia wheels; see [Packaging](#packaging) |
| Chat model | `openai/gpt-6-sol` by default, which writes Blender Python through three tools; editable in the preferences |
| Running the model's code | Consent first, a rule filter, optional Code check; documented as **not a sandbox** |
| Key storage | Add-on preferences (unencrypted `userpref.blend`) or the `EACHLABS_API_KEY` environment variable |
