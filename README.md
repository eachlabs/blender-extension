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
- **Build a scene from a prompt**: type one line in a bar in the 3D view. A model writes Blender
  Python, and a scene and a camera move appear, stage by stage.

Video defaults to **Seedance 2.5 reference-to-video** in draft mode at 480p, with your camera move
as its reference video. `examples/lighthouse/` builds a 2 min 10 s film this way.

The add-on talks to the Eachlabs API directly over HTTPS. It adds a sidebar tab and a prompt bar
in the 3D view. It changes your scene only through the images, strips and camera background it
creates, and the objects the scene chat builds in its own collection. The scene chat runs Blender
Python written by a model; see [Build a scene from a prompt](#build-a-scene-from-a-prompt). It is not
a sandbox.

## Install

The step-by-step guide, with screenshots, is at
[docs.eachlabs.ai/integrations/blender](https://docs.eachlabs.ai/integrations/blender).

1. In *Edit > Preferences > Get Extensions*, open *Repositories*, press **+**, choose *Add Remote
   Repository* and enter `https://github.com/eachlabs/blender-extension/releases/latest/download/index.json`. Then search for
   **Eachlabs** and press **Install**. Blender keeps it updated with your other extensions.
   Alternatively, download the zip for your system (`macos_arm64`, `macos_x64`, `windows_x64` or
   `linux_x64`) from [Releases](https://github.com/eachlabs/blender-extension/releases/latest)
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

## Build a scene from a prompt

A prompt bar sits at the bottom of every 3D view. Type a scene, such as
*a street at dusk, slow dolly forward over 5 seconds*, and press **Enter**.
The chat builds it in stages: layout, detail, materials, light, camera, check. Every object is built
from its real parts, so you can move, edit and animate each part.

### The chat runs Blender Python. This is not a sandbox.

The chat model writes Blender Python, and the add-on runs it inside your Blender. That is how it builds
real scenes. Please read this before you agree:

- The code runs with Blender's own access. Blender's Python can reach your files and the network.
- A filter refuses the obvious ways out of the scene, such as files, the network, other programs and
  your add-on settings. It catches honest mistakes. It does **not** make the code safe, and it is
  **not a sandbox**.
- While a step runs, your API key is taken out of the add-on preferences, and a step that changes the
  add-on's settings stops the run. Code that gets past the filter can still find the key elsewhere.
- Every stage is one undo step, and you can read all the code the chat ran with **Show code**.
- Run it in a file you can afford to lose, and save your work first.

### Agreeing

Before the first run the bar shows a card instead of starting.

| Choice | What happens |
|---|---|
| **Build** | Saves your agreement and starts the run |
| **Cancel** | Starts nothing, saves nothing and keeps your prompt |

The agreement is saved in the add-on preferences, so the card shows once. The *Build* button in the
sidebar (when the bar is not shown) asks the same question. Nothing runs before you agree.
To be asked again, press **Ask before building again** in the add-on preferences under *Chat*.

### What the chat sees

- It sees your prompt, the names and sizes of the objects it built, and only the **number** of your other
  objects. The add-on does not send their names.
- **With Visual check on, it also sees small pictures of the scene**, and a picture shows whatever is in the
  frame, **your own objects too**. The text sent with a picture still names none of your objects. Turn Visual
  check off to send no pictures; with Scene review on, the finished scene's four pictures are still sent.
- **When you point at your own objects.** If objects are selected and your prompt points at them ("make this
  one red", "these"), "this" means the selected objects **and their children**: a selected part counts as its
  whole group, from its top parent down. The chat is told the names of those objects, children included, also
  when they are yours, because you pointed at them on purpose, and it may change all of them.
  Objects outside the selected groups are never named. With "this" and nothing selected, the bar says
  `Select the object first, then send again.` and keeps your prompt.
- **Changes to what you point at.** A prompt that only changes the objects you selected or named ("make this
  red", "make this one taller") runs one short stage that sees only those objects. After each step the add-on
  puts back any other object of the chat's that the step moved, reshaped or repainted, and tells the model.
- **Upgrade in place.** Select something, or name it, and ask for it to be real ("make this
  hyper-realistic"): the plan shows it as a 3D item at its current size, and on Build its 3D model replaces it at
  the same place, size and turn, under the same name, as one step you can undo. No code runs on it while it
  waits. The picture the model is made from is described from the object's part names and materials and your
  words. If the model cannot be made, it stays as it was.
- **Find and list.** "Find the church" or "show me the police station" builds nothing: one small call reads
  the request with the names of the chat's own objects, and the add-on selects and frames the match
  (`Found: Church (3 objects)`). "What did you build?" lists the main things. The cost of that call is shown.
- What a step prints, and its error messages, go back to the model. A step that reads your objects
  and prints them, or fails on one, shows the model their names.
- It is told not to change your objects. If a step does change some anyway, it is told how many, and
  you can undo the stage.
- Your API key is replaced by `[redacted]` in what goes back to the model and in the code you can read.
  This guards against accidents, not against code written to hide a key.

### Scene, Assets and Characters

The tabs above the prompt say what it builds, and the line under them says what the next prompt does.

| Tab | Nothing selected | An object selected, or named in the prompt |
|---|---|---|
| Scene | A whole scene and its camera move, or a change to the current scene | The same: Scene reads the prompt as it always has |
| Assets | One new object, placed where it fits in the current scene. Nothing that exists changes, and the light, sky and camera stay as they are | A change to that object only, as a targeted edit. Nothing new is added |
| Characters | One new person or animal, as Assets, built as the scene's main object with full detail | A change to that character only |

With an object selected, the line reads *Changing Barrel* and shows a chip with its name. The chip's **✕** clears
the selection, and the next prompt adds again. A selected part counts as its whole object; a light, a camera, a
hidden object and Blender's untouched startup Cube never count. A name in the prompt counts only when it is of the
tab's kind: *make the cat bigger* on Characters changes the cat, while *a lamp next to the table* on Assets adds a
lamp.

Every control on the bar explains itself: rest the mouse on it for a moment and a tooltip says what it does and
how to use it. The sidebar's buttons show the same texts as Blender tooltips.

On an empty scene, Assets and Characters show the thing on its own: a plain ground, soft light and a slow camera
move around it. The tabs are dimmed while a run is going; Retry keeps the tab its run started with.

### Working with a run

After a run the bar reads `Ask for a change: warmer light, a bigger window…`. The next prompt changes the same scene, in the same
collection: *add windows to the buildings* keeps the street and adds the windows. This also works after
you save and open the file again. Press **New scene** to build the next prompt in a new, empty Blender
scene; the old one stays in Blender's scene list. When you delete the chat's collection, the next prompt
also starts a new scene.

| To | Do |
|---|---|
| Type in the bar | click it with any tool, or press `Shift+Alt+Space` |
| Send | `Enter` or the orange button |
| Start a new line | `Shift+Enter` |
| Reuse an earlier prompt | `↑` and `↓` |
| Give the keys back to Blender | `Esc`, or click outside the bar |
| Stop a run | the stop button, or `Esc` while the bar has focus; what was built is kept |
| Change what was built | type the change, such as *make the lamps warmer*, and press `Enter` |
| Start a new scene | **New scene**; what was built stays in its own scene |
| Run a stopped stage again | **Retry stage** |
| Undo the last stage | **Undo stage** (one undo step per stage) |
| Read the code the chat ran | **Show code**: opens the text `Eachlabs code` in a Text Editor, with every prompt of the current scene, one section per prompt and per step, newest last |
| See everything it built | **Frame result**; your selection stays as it is |
| Watch the camera move | **Play as** *camera*: the 3D view looks through that camera and plays. While it plays the button reads **Pause**; Pause, or stopping playback any other way, puts your view and the scene camera back. The arrow beside it lists every camera in the scene, the chat's own first; pick one to play through it. A scene without a camera shows a plain **Play** |
| Get the finished picture | **Final render**: the scene camera with Cycles (bounced light, denoised, depth of field on the subject), the last frame of an animation; Esc in its window stops it. Saved next to the `.blend` as `<name>-final.png` (an unsaved file: the add-on's `renders` folder). The previews stay EEVEE |

**Show code**, **Final render** and **New scene** are advanced tools. The bar shows them only with **Show advanced
tools** on in the add-on preferences; it is off by default. Without them, a card whose only way on is New scene
still shows it.

**New scene**, **Undo stage**, **Clear generated files**, **Clear finished**, stopping a render job, and Stop
while a 3D object or picture is being made on each::labs ask first. The dialog says what happens and what
stays; **Cancel** changes nothing. Stopping a paid run that already started does not refund it.

Every state of the bar offers a next step besides typing, except when Blender was started with
`--offline-mode`: then the bar says to restart Blender without it.

| The bar shows | Buttons |
|---|---|
| The consent card | Build, Cancel |
| A run in progress | Stop |
| Finished | Play as *camera* with its camera list (Pause while it plays), Frame result, Final render (hidden while it renders), Undo stage, Show code, New scene |
| Finished, but nothing in the scene changed: the bar says so above the reply | Retry, Undo stage, Show code, New scene |
| A stage failed or the run stopped | Retry stage, Undo stage, Show code, New scene |
| Stopped by you | Undo stage, Show code, New scene, Keep the scene |
| Stopped because a step changed the add-on's settings | Show code, New scene |
| A start that was refused, a chat that could not start, or a run that broke off | Retry stage, Show code, and New scene when there is a scene |
| Online access is off | Open preferences (at *System*, where *Allow Online Access* is), Show code, and New scene when there is a scene |
| A missing or rejected API key | Open preferences |

Enter with an empty bar does nothing; the bar keeps showing what to type.

Undo stage shows only when it applies; Show code shows once a step has been written.

**The settings button** (the sliders, left of send) opens the add-on's preferences: the API key, the chat's
models, rounds and checks.

**The quality pill** on the input row shows how much each run builds. Click it to choose; Esc or a click outside
closes the menu. It is dimmed while a run is going. In a narrow bar it sits on its own row above the input.

| Mode | What a run does |
|---|---|
| Prototype (default) | Quick drafts with a plainer look: GPT-6.1 Terra answers every stage, materials and light get 1 round each, main objects 1 detail round, no reference pictures and no generated textures (free textures and node materials instead), and the concept picture comes from Z-Image Turbo. Layout, camera, check, the visual check and the fixes keep their rounds, so nothing is left broken. At most 40 rounds |
| Final (experimental) | Full detail: the rounds, the models, the detail and the reference pictures set in the preferences. Experimental: its results vary more than Prototype's, and it can leave an object misplaced or broken |

The plan card shows a run's price before it builds.

The scene's model is set in the preferences (GPT-6 Sol by default; Prototype uses GPT-6.1 Terra instead unless you
set a model of your own). In Final, the *Light and materials model*
answers light and materials (Sonnet 5.5 by default), and the *Main objects' detail model* details the main
objects (GPT-6 Astra by default). *Best quality* makes GPT-6 Astra the scene's model and switches to Final.

| Model | Good for |
|---|---|
| GPT-6 Sol (default) | Most complete scenes |
| Best quality (GPT-6 Astra) | The most detailed objects, slower |
| Sonnet 5.5 | Richer light and materials |
| Opus 5.5 | Best light, builds less |

### Settings

In *Preferences > Add-ons > Eachlabs*, under *Chat*:

| Setting | Default | Meaning |
|---|---|---|
| Quality mode | Prototype | Prototype or Final, as the bar's quality pill sets it. Prototype caps the settings below (see the table above) |
| Model | `openai/gpt-6-sol` | The language model the chat uses; any model id the chat endpoint accepts. The *Best quality* button next to it sets GPT-6 Astra and Final |
| Light and materials model | Sonnet 5.5 | Final: the model for the light and materials stages; *The scene's model* uses one model for every stage |
| Main objects' detail model | GPT-6 Astra | Final: the model that details the main objects; other objects keep the scene's model. *The scene's model* details every object |
| Show advanced tools | off | Shows Show code, Final render and New scene on the bar |
| Total rounds | 15 (5-16) | Most model replies one message may use; lower it to make runs shorter. The run stops and keeps what was built. 16 leaves room for the one extra light round |
| Visual check | on | The chat looks at small renders of the scene and fixes what it sees (see below) |
| Scene review | on | After the build, a separate look at the whole scene from four sides fixes what makes no sense, in about 2 rounds (see below) |
| Seconds per step | 20 (5-120) | Python code that runs longer is stopped and reported as a time-out. One long Blender operation, such as a heavy modifier, runs to its end, and Blender waits for it |
| Failures allowed | 3 (1-10) | Failed steps of one kind in a row before the chat stops |

Under *Detail*:

| Setting | Default | Meaning |
|---|---|---|
| Detail rounds | 3 (0-8) | Model rounds each main object gets after the layout (one less for a medium one, one more for its close-up); 0 turns the detail stage off |
| Secondary detail rounds | 1 (0-4) | Model rounds each secondary object (a tree, a bench, a rock) gets after the main ones; 0 leaves them as the layout built them |
| Objects at once | 3 (1-6) | Main objects the detail stage works on at the same time; their Blender steps still run one at a time |
| Reference pictures | On | A picture of each main object for the chat to build it to, with its price shown on the plan; after each detail round the object is compared with it. On, every new scene asks for Build first |
| Detail thinking | Normal | *More* asks the model to think longer on each detail step: slower, and a step is cut off more often |

Under *3D objects*:

| Setting | Default | Meaning |
|---|---|---|
| 3D objects | Auto | *Auto* and *Always ask* may generate a solid single piece as a 3D model, after a plan; *Off* builds every object in code (pictures still ask first, see below) |
| 3D limit per scene | 2 (1-12) | Most solid pieces the chat suggests in 3D per scene; pieces you move to 3D on the plan are always allowed |
| 3D wait limit | 20 min (3-60) | Counted from when that object's run starts; one not back by then stays built in code |
| Texture wait (s) | 240 (30-900) | Longest one texture may take; after it the material keeps its colour |
| Concept picture wait (s) | 120 (30-600) | Longest the concept picture may take; after it the scene is built without it |
| Model reply wait (s) | 120 (30-600) | Longest one model reply may take; after it the stage counts it as a failed round |
| Download wait (s) | 120 (30-600) | Longest one result download may take; after it the result is skipped |
| Textures per scene | 6 (0-24) | Most generated photo textures the chat may order for one scene; 0 turns them off |
| Concept picture | On | A new scene starts with a picture of it drawn from your prompt, as a reference for the chat |
| Clear generated files | | Deletes the 3D models, textures and concept pictures kept on this computer; objects already in your scenes stay |

### Detail

- After the layout, the chat picks the main objects of the shot (the subject first) and the parts each one
  still needs, then improves each object in rounds of its own: rounded and bevelled shapes, frames, trims,
  lights and fittings, each a real part of the object. Flat things such as roads and lawns are left to
  their materials.
- Up to three objects are worked on at the same time. Each step may change only its own object: if it
  changes anything else of the chat's, the add-on puts that back and tells the chat. A new part built
  without a parent becomes a part of its object, where it stands.
- After its rounds, the add-on renders the object alone from four sides in plain shading and shows it to the
  chat, with any small gaps it measured between the object's parts. The chat gets one more round to fix what
  still looks like a box from any side, or floats apart.
- Secondary objects such as trees and benches get a short pass of their own, without a close-up.
- Copies of a detailed object (`Pine_001`, `Pine_002` of `Pine_000`) are rebuilt from it, sharing its meshes.
- A change details only the objects it adds and the ones it points at; the rest of the scene is left as it is.
- With **Reference pictures** on, the plan lists the main objects that get a picture, with the price
  (`References: car, church`). Each one is drawn after **Build**, while the layout is built, and the
  chat builds its object to it: after each round the object is compared with the picture and the differences
  go to the next round. The object is still built from parts in code.

### Real 3D objects

- A generated 3D model is one closed shell: doors, windows and wheels are fused into it. So only a **solid
  single piece** with no parts of its own, such as a statue, a boulder or a carved ornament, may be
  generated. Buildings, vehicles, furniture, lamps, people and plants are always built in code.
- When the scene has such a piece, the chat shows a **plan** first: the pieces it will generate as real 3D
  models, with the total price and about how long they take one by one. Click a piece to move it
  between 3D and code; your choice always stands. Objects with parts are listed under code and cannot move.
  Nothing is generated until you press **Build**; **Cancel** puts your prompt back.
- A plan is shown only when there is something to decide or pay for. A solid piece you call realistic,
  hyper-realistic, real, photoreal or 3D is in the 3D list; an object with parts you call realistic gets
  high detail in code instead.
- Each 3D object runs an Eachlabs workflow in your account named *Blender 3D model*: a picture of the
  object, then a textured 3D model of it. The add-on makes the workflow on first use, and again if it is
  deleted. Before each run it compares the workflow's models and their settings with its own; if someone
  edited them, it saves its own as a new version and runs that, so the price on the plan stays true.
- The chat first builds a simple code version of each 3D object at its place and size, then keeps building.
  The 3D models are made one at a time, largest first; the bar shows the one being made and the queue.
- When a 3D model is ready it replaces its code version at the same place, size and turn, as one step you can
  undo. One that fails or passes its wait limit keeps its code version, and the reply says so in one line.
  The run ends only when every 3D model has arrived or passed its limit; Stop ends it at any time.
- **Stop and the wait limit stop the waiting, not the 3D run.** A 3D object whose run already started on
  Eachlabs keeps running there and may still be billed, and its cost may settle after the bar shows the total.
  The bar then says `Stopped — a 3D run already started may still be billed.`
- Generated models are kept in a local cache in the add-on's user folder (up to 2 GB). Asking for the
  same object again uses the cached one, with no new run and no cost.

### Concept picture and textures

- Nothing is drawn before you press **Build** on a plan that shows the price. A plan of objects has one line
  for them: `Looks: a concept picture and up to 6 textures`. When no plan of objects
  is shown (*3D objects* is *Off*, the change adds nothing, or the chat could not make a plan), a plan with only
  that line asks first. **Cancel** draws nothing and puts your prompt back.
- **Concept picture.** When a new scene's stages start, `nano-banana-pro` draws the scene from your prompt.
  The layout and materials stages get the picture as an image, as a reference for layout, colours and mood.
  Show code's text links it. A follow-up draws none unless you ask for a concept picture; a thing called a
  concept, such as a concept car, is not such a request.
- **Textures.** In the materials stage the chat may order a seamless photo texture for one of its own
  materials (a brick wall, a wooden floor). It is drawn while the chat keeps working and then set as that
  material's colour, box-projected at a real-world scale. Textures are kept in the same local cache, so the
  same description again costs nothing. One that cannot be made leaves the material as it was, and the reply
  says so.

### Visual check

- After the layout, the light and the camera stages, and once in the check stage, the add-on renders a small
  frame (640 px wide, EEVEE, 8 samples) and shows it to the chat with one line: fix anything clearly wrong,
  such as things floating, overlapping, the wrong size for real life, cut off, out of frame, too dark, or the
  wrong time of day. Each of those stages then has one more round to fix it. These rounds, at most 3, come on
  top of *Total rounds*.
- It uses the chat's own camera at the first frame, and also at the last frame in the camera and check stages
  when the camera moves. Before the chat has a camera, it uses a view from above at an angle.
- The bar says `Looking at the frame…` while it renders. A frame took about 1 s on a street of 2,400 objects.
  Your render settings are lowered only for that frame and put back right after it.
- **The picture shows your own objects too, when they are in the frame.** It is sent to the chat model like
  the rest of the run, and deleted from your computer once it is read.
- A model that does not take pictures gets the same check as text instead, and no more pictures for the rest
  of the session. Turn it off under *Chat* in the preferences.

### Scene review

Once the check stage is done, a separate call to the scene's model looks at the finished scene: the camera's view
and three views around the main things, with your request and the list of things by name. It looks only for
what makes no sense or does not match the request, such as a ladder that does not reach its door or parts lost
inside other things, never for taste. At most three findings go to one more fix stage of 2 rounds, only when
those rounds fit your round limit. A finding on a name that is not in the scene, or whose fix would remove
something, is dropped. After the fix the same views are rendered again; if the fix made the scene worse, that
stage is undone. The done card says it in one line, for example `Review: the ladder does not reach the door
(not fixed).`, and nothing when the review found nothing. It runs only on a full build, never on a find, a
targeted edit or a retry. The plan's estimate counts its 2 rounds. Turn it off under *Chat* in the preferences.

### Good to know

- **Blender's startup Cube is deleted when a new scene's stages start.** Only when it is exactly the
  startup file's Cube: not moved, scaled, renamed, edited or given another material, and nothing points at
  it (a camera aimed at it keeps it). Undo stage on the layout stage, or Ctrl+Z, brings it back. A follow-up
  never touches it.
- It needs your API key and online access. Without a key the bar says `Add your Eachlabs API key to start.`
- The bar shows each stage, the current step and the round. At the end it shows the reply,
  the rounds used, the time the run took and the cost. The time leaves out how long the plan waited for you
  to press Build.
- Longer prompts take longer to build. The chat builds and checks every object you ask for, so each one adds
  time. Changes to an existing scene also take longer as the scene grows. For example, in Prototype a room
  with ten objects took about 6 minutes, and the same room with a full bookshelf took about 8.
- A prompt holds up to 2000 characters; a longer paste is cut.
- When the layout stage ends, the 3D view moves once to show the new buildings.
- Four seconds after a run ends, the reply folds to one line (`DONE · 34 ROUNDS · 6 MIN · $0.38`), so the scene
  is in full view. After that, resting the mouse on the bar opens the reply and its buttons at once, and moving
  it away folds them at once. It never folds while the bar waits for a choice, such as Retry after a run that
  changed nothing.
- When the light stage ends, the 3D views in that window that use *Solid* shading switch to
  *Material Preview*, so glowing lamps and lights show. *Rendered* and other shading stay as they are.
- **Undo stage** shows only while the chat's last stage is the active step in *Edit > Undo History*.
  Any step of your own after the run, even a selection click, hides it; `Ctrl+Z` still undoes one
  stage at a time.
- What the chat changes in your file:
  - its own collection, `Eachlabs scene`, and the objects in it;
  - the scene's active camera and frame range;
  - the scene's world, which it points at its own world. Your world is not edited.
    When no other scene uses it, the chat turns on its fake user (the shield in the world list),
    so it is kept in the file when you save and you can assign it again under *Scene > World*.

  It is told to leave your objects alone, and a check after each step counts the ones that changed.
  That check reports a change. It cannot prevent one.
- The **Eachlabs** tab shows the MCP connection (`https://mcp.eachlabs.ai/mcp`), with a button to check it again.

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
The bundled Inter and Geist Mono fonts are under the SIL Open Font License 1.1 (`eachlabs/fonts`);
Skia, inside the bundled skia-python wheels, is under the BSD 3-Clause license.

## Develop

The unit tests need Skia (the version pinned in `scripts/build.sh`), in a virtual environment outside the repository:

```bash
python3 -m venv ~/.venvs/eachlabs && ~/.venvs/eachlabs/bin/pip install skia-python==144.1
~/.venvs/eachlabs/bin/python -m unittest discover -s tests -t .  # API client, chat loop, scene tools, bar, text field
blender --background --factory-startup --python-exit-code 1 --python tests/smoke.py   # export, import, scene tools, chat run; no network
BLENDER=/path/to/blender scripts/build.sh                        # download Skia wheels, build dist/eachlabs-<version>-<platform>.zip
BLENDER=/path/to/blender scripts/verify-install.sh               # install this machine's zip in a fresh profile
BLENDER=/path/to/blender scripts/gui-check.sh                    # real Blender window, fake API and model, prompt bar, screenshots
BLENDER=/path/to/blender scripts/tutorial-shots.sh <dir>         # tutorial images from the built zip, no predictions
BLENDER=/path/to/blender scripts/build-listing.sh <dir>          # release listing: upload index.json and the zips
```

`scripts/e2e_live.py` runs the real flow against the API and makes paid predictions; see its
docstring. `docs/architecture.md` explains the modules, threading and data flow.
