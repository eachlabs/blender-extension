# Eachlabs for Blender

A Blender 4.2+ extension that sends what you already make in Blender to Eachlabs models and
workflows and brings the generated images and videos back into your file:

- **Generate Image from View**: render the current frame (or snapshot the viewport), send it with a
  prompt, and get the result as an image in the Image Editor and, optionally, as the camera's
  background for A/B comparison.
- **Generate Video from Camera Move**: render the frame range, package it as MP4 plus first and
  last frames, send what the model takes, and get the clip back as a sequencer strip at the render's
  start frame, timed to the rendered range.
- **Re-run**: send the last rendered inputs again with another model, prompt, seed or parameters,
  without rendering.
- **Export movie**: render the sequencer, with sound, to one MP4 you can play or share.

Video defaults to **Seedance 2.5 reference-to-video** in draft mode at 480p, with your camera move
as its reference video. `examples/lighthouse/` builds a 2 min 10 s film this way.

The add-on talks to the Eachlabs API directly over HTTPS. It adds a sidebar tab; it does not
change your viewport or scene beyond the images, strips and camera background it creates.

## Install

The step-by-step guide, with screenshots, is at
[docs.eachlabs.ai/integrations/blender](https://docs.eachlabs.ai/integrations/blender).

1. In *Edit > Preferences > Get Extensions*, open *Repositories*, press **+**, choose *Add Remote
   Repository* and enter `https://github.com/eachlabs/blender-extension/releases/latest/download/index.json`. Then search for
   **Eachlabs** and press **Install**. Blender keeps it updated with your other extensions.
   Alternatively, download the zip from [Releases](https://github.com/eachlabs/blender-extension/releases/latest)
   (or build it, below) and drag it into a Blender window.
2. Allow online access when Blender asks, or later in *Preferences > System > Network > Allow
   Online Access*. Without it the Eachlabs tab explains what to enable and makes no requests.

## Set your API key

1. Create a key at [eachlabs.ai](https://www.eachlabs.ai) under *Settings > API Keys*.
2. In *Preferences > Add-ons > Eachlabs*, paste it into **API key** and press **Test connection**.
   A working key shows your balance; a rejected one shows the API's error.

Blender keeps add-on preferences, including this key, unencrypted in `userpref.blend`. To keep the
key out of Blender, leave the field empty and set the `EACHLABS_API_KEY` environment variable before
starting Blender.

## Use it

Open the sidebar (`N`) in the 3D Viewport or the Video Sequencer and pick the **Eachlabs** tab.
Press the refresh button once per session to load models and, with a key, your workflows.

### Generate Image from View

1. Pick a model or workflow in the search field. Only targets that take an image and return an
   image are listed; tick *All URL-input models* to widen the list.
2. Check the listed price, type a prompt and, if the model has one, set a seed.
3. Under **Send render to**, make sure the model input that should receive your frame is set to
   *Rendered still*. It is pre-selected when the model has a single image input.
4. Choose *Render* (scene resolution, your render engine) or *Viewport* (fast snapshot of the
   view), then **Generate Image**.

The job appears under **Jobs** with its state and elapsed time. When it finishes, the result opens
in an Image Editor and, with *Camera background* on, shows over the camera view (look through the
camera with `Numpad 0` and adjust its opacity in the camera's *Background Images*).

### Generate Video from Camera Move

1. Animate your camera. After the model list loads, the default video model is selected:
   `bytedance-seedance-2-5-reference-to-video` with your clip in `video_urls`, `resolution` 480p
   and `draft` on (the ★ button next to the model field restores it; change it in the add-on
   preferences under *Default video model*). Draft returns a fast, cheaper 480p preview whose
   `draft_id` can be finished at 1080p later. An API URL that does not offer draft skips it with a
   note.
2. Write the prompt. Seedance cites its inputs by token: `@Video1` is your camera move, `@Image1`
   the first image you send. For example: *"Follow the camera movement of @Video1. A white
   lighthouse at dusk in the style of @Image1."* Avoid *add*, *remove*, *replace*, *extend* and
   *continue*: they switch Seedance to video editing, which ignores the requested duration.
3. Under **Send render to**, bind each input you want filled: *Clip (MP4)*, *First frame*, *Last
   frame*, or *File…* for anything else, such as a style frame or character sheet in `image_urls` or
   music in `audio_urls`. Eachlabs does not yet say which input is the first or last frame, so for
   models with several image inputs you choose (for example `image_url` → *First frame*,
   `end_image_url` → *Last frame*).
4. Keep *Scene range* or set your own start and end, and choose a preview resolution for the clip
   you send. *Match duration* asks the model for the rendered length (a 10 s range requests 10 s),
   so the result fits the range without retiming. **Timing** decides what happens when it does
   not: *Fit to range* stretches the result to the rendered frames; *Keep timing* plays it in real
   time.
5. Press **Generate Video**. The clip is added on the first free channel at the render's start
   frame, with its sound on the next channel when *Import audio* is on. Playback switches to *Sync to
   Audio* so you hear it live. A result at most two frames longer than the range is trimmed, which
   keeps its sound. When the picture had to be stretched, a *Speed* strip sits above it
   and the sound is added muted, because Blender cannot stretch sound from a script; unmute it or use
   *Keep timing*.

### Export movie and open results

**Export movie** renders everything in the sequencer, picture and sound, to
`eachlabs/<file name>/<id>_movie.mp4` and lists it under **Jobs**. The ▶ button on any finished job
opens its file in your system player.

### Re-run and parameters

The ↺ button next to each Generate button re-sends the last rendered inputs with whatever is now
selected in the panel, without rendering. Uploaded files are reused for up to six days.

*Parameters* lists the model's other options (aspect ratio, duration, resolution and so on). Tick an
option to send your value; unticked options use the model's defaults. *JSON* accepts extra inputs
the list cannot show, such as arrays.

### Cancel

The **×** on a running job stops it. For models Eachlabs marks the run cancelled, but work already
running at the provider may still finish and be billed. Workflow runs cannot be cancelled through
the API yet, so cancelling only stops waiting for them. A render in progress keeps going until you
press `Esc` in the render window; nothing is uploaded afterwards.

## Files

Inputs and results are saved next to your file in `eachlabs/<file name>/`, every name prefixed with
the job ID (`20261019-153012-a1b2_still.png`, `..._clip.mp4`, `..._result_1.mp4`, plus a `.json`
record of what was sent). Unsaved files use a temporary folder; save first to keep everything with
the project. *Open folder* under **Jobs** shows it.

## Known limitations

- **Input binding is manual for multi-input models.** The API does not declare which input takes
  an image, a video or a first/last frame, so only single-input targets are pre-bound.
- **Workflows** are listed only when their inputs declare `image` or `video` types; a workflow's
  output type is not declared, so results are imported by file type.
- **No per-request quote.** The panel shows each model's listed price; the settled cost appears
  on the job when it finishes. Workflows have no listed price.
- **Cancel** cannot stop provider work already running, or workflow runs at all (see above).
- **Rendering blocks briefly** while the frames are encoded to MP4 after the render job finishes.
- **Stretched clips keep their sound muted**; Blender's sound strips cannot be retimed from a script.
- **Drafts are not finalized automatically**; each `draft_id` is kept for 1080p completion.
- **Uploads** are limited to 100 MB per file; lower the preview resolution or range for long shots.
- Depth, normal and mask passes are not sent yet; `docs/architecture.md` describes how they plug in.

## License

Copyright (c) 2026 Eachlabs. Released under the GNU General Public License, version 3 or later
(`LICENSE`), as Blender requires for published add-ons that use its Python API. Generating images
and videos needs an Eachlabs account and is billed by Eachlabs.

## Develop

```bash
python3 -m unittest discover -s tests -t .                      # API client, capabilities, timing, naming, jobs
blender --background --factory-startup --python-exit-code 1 --python tests/smoke.py   # export and import, no network
BLENDER=/path/to/blender scripts/build.sh                        # validate and build dist/eachlabs-<version>.zip
BLENDER=/path/to/blender scripts/verify-install.sh               # install the zip in a fresh profile
BLENDER=/path/to/blender scripts/gui-check.sh                    # real Blender window, fake API, screenshots
BLENDER=/path/to/blender scripts/tutorial-shots.sh <dir>         # tutorial images from the built zip, no predictions
BLENDER=/path/to/blender scripts/build-listing.sh <dir>          # release listing: upload index.json and the zip
```

`scripts/e2e_live.py` runs the real flow against the API and makes paid predictions; see its
docstring. `docs/architecture.md` explains the modules, threading and data flow.
