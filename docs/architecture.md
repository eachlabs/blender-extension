# Architecture

The Eachlabs Blender extension sends what a Blender user already produces (a rendered frame, a
rendered camera move, later render passes) to an Eachlabs model or workflow and brings the result
back into Blender. Blender is the host and Eachlabs is the service: the add-on calls the public
HTTPS API directly with the standard library and adds no viewport, web UI or MCP server. An agent
can drive the same operators later.

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
| `main_thread.py` | yes | The single `bpy.app.timers` dispatcher, UI redraw tagging and file-load handlers |
| `render_export.py` | yes | Still, viewport and frame-range renders, MP4 packaging and first/last frame export |
| `importers.py` | yes | Image datablocks, Image Editor, camera background, VSE movie strips and fps reconciliation |
| `compat.py` | yes | Version shims for the sequencer and output-format APIs |
| `catalog.py` | yes | Session cache of models and workflows and the window-manager collections the panels search |
| `pipeline.py` | yes | Orchestrates each action: validate, render, start the job, import |
| `preferences.py` | yes | API key, base URL, polling settings, Test connection |
| `props.py` | yes | Scene settings, input bindings, model parameters and the last inputs kept for re-run |
| `operators.py` | yes | Thin operators that validate context and call `pipeline` |
| `panels.py` | yes | The `Eachlabs` sidebar tab in the 3D Viewport and the Video Sequencer |

Modules without `bpy` import nothing from Blender, so the unit tests run under any Python 3.11+.

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

## Version differences

Verified by probe scripts on Blender 4.2.23 LTS and 5.2.2 LTS:

| Concern | 4.2 | 5.x | Handling |
|---|---|---|---|
| Strip collection | `sequence_editor.sequences`, `MovieSequence` | `sequence_editor.strips`, `MovieStrip` | `compat.strips()` |
| Effect strips | `new_effect(..., seq1=)` | `new_effect(..., length=, input1=)` | `compat.new_speed_effect()` |
| Video output | `image_settings.file_format = 'FFMPEG'` | set `image_settings.media_type = 'VIDEO'` first | `compat.set_video_output()` |
| Strip timing names | `frame_final_start/end/duration`, `frame_duration` | `left_handle`, `right_handle`, `duration`, `content_duration` (old names removed in 6.0) | `compat.strip_start()` and friends |
| Strip speed | `retiming_keys.add()` crashes Blender | retiming keys resolve to the wrong strip when the sequencer holds more than one strip, then crash on write | both: set the movie strip's length to `N` and add a *Speed Control* effect in *Stretch* mode |
| Sequencer scene | the active scene | a workspace may show a separate `sequencer_scene` | import into the workspace's sequencer scene when set, else the rendered scene |

The Speed Control mechanism is checked in `tests/smoke.py` on both versions by rendering the
sequencer over a clip whose frames have unique gray levels: the stretched (60-frame), compressed
(24-frame) and unchanged (48-frame) strips show the same source frame at the same proportional
positions. The retiming-key crashes are Blender bugs worth reporting upstream; the Python retiming
API can replace the effect strip once they are fixed.

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
| Key storage | Add-on preferences (unencrypted `userpref.blend`) or the `EACHLABS_API_KEY` environment variable |
