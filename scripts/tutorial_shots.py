"""Screenshots for the public tutorial, taken in a real Blender window. Run through scripts/tutorial-shots.sh.

    blender --background --factory-startup --python scripts/tutorial_shots.py -- <out> scene
    blender --enable-event-simulate --online-mode <out>/tutorial.blend --python scripts/tutorial_shots.py -- <out> listing
    blender --enable-event-simulate --online-mode <out>/tutorial.blend --python scripts/tutorial_shots.py -- <out> panels
    blender --enable-event-simulate --online-mode <out>/tutorial.blend --python scripts/tutorial_shots.py -- <out> results
    blender --background --factory-startup --python scripts/tutorial_shots.py -- <out> crop

Only ``results`` makes predictions (PAID, one image and one video, submitted once each, with a receipt);
with $EACHLABS_TUTORIAL_REHEARSE set it answers them locally instead, at no cost. The model list and
prices are public GETs. The key is read from $EACHLABS_KEY_FILE (chmod 600) into this process after the
no-key shots. Scripts cannot pick a sidebar tab or resize a region, so clicks and drags are simulated.
"""

import json
import math
import os
import shutil
import stat
import sys
import time
import traceback

import bpy

OUT = sys.argv[sys.argv.index("--") + 1]
STAGE = sys.argv[sys.argv.index("--") + 2]
RAW = os.path.join(OUT, "raw")
MODULE = "bl_ext.eachlabs.eachlabs"  # Installed from the repository with id "eachlabs".
IMAGE_MODEL = "nano-banana-pro-edit"
IMAGE_PROMPT = "Turn this into a bronze statue in a museum courtyard at golden hour, soft shadows"
VIDEO_PROMPT = ("Follow the camera movement of @Video1. A bronze monkey statue on a stone plinth in a "
                "museum courtyard at golden hour, slow and smooth. Sound: quiet courtyard ambience and "
                "distant birds; no music, no dialogue.")
VIDEO_RATE = 0.0708  # Listed Seedance 2.5 price per second at 480p, for the budget check only.
ACCENT = (1.0, 0.45, 0.1, 1.0)


def build_scene():
    scene = bpy.context.scene
    for obj in list(scene.objects):
        if obj.type == "MESH":
            bpy.data.objects.remove(obj)
    bpy.ops.mesh.primitive_plane_add(size=8)
    bpy.context.active_object.color = (0.55, 0.52, 0.47, 1)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.9, depth=0.6, location=(0, 0, 0.3))
    bpy.context.active_object.color = (0.75, 0.72, 0.66, 1)
    bpy.ops.mesh.primitive_monkey_add(size=1.4, location=(0, 0, 1.3), rotation=(math.radians(-15), 0, 0))
    monkey = bpy.context.active_object
    monkey.color = (0.72, 0.45, 0.2, 1)
    bpy.ops.object.shade_smooth()
    monkey.modifiers.new("Subdivision", "SUBSURF").levels = 2
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.color_type = "OBJECT"
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.fps = 24
    scene.frame_start, scene.frame_end = 1, 120
    pivot = bpy.data.objects.new("Orbit", None)
    scene.collection.objects.link(pivot)
    camera = scene.camera
    camera.location, camera.rotation_euler = (0, -6.5, 2.4), (0, 0, 0)
    camera.parent = pivot
    camera.constraints.new("TRACK_TO").target = monkey
    pivot.rotation_euler[2] = math.radians(-35)
    pivot.keyframe_insert("rotation_euler", index=2, frame=1)
    pivot.rotation_euler[2] = math.radians(35)
    pivot.keyframe_insert("rotation_euler", index=2, frame=120)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "tutorial.blend"))


# -- window helpers ------------------------------------------------------------------------------

def window():
    return bpy.context.window_manager.windows[0]


def area_of(kind):
    return next((a for a in window().screen.areas if a.type == kind), None)


def region_of(area, kind):
    return next(r for r in area.regions if r.type == kind)


def note_rects(name, area=None, win=None):
    path = os.path.join(OUT, "rects.json")
    rects = json.load(open(path)) if os.path.isfile(path) else {}
    entry = {}
    if area is not None:
        sidebar = region_of(area, "UI")
        entry = {"area": [area.x, area.y, area.width, area.height],
                 "sidebar": [sidebar.x, sidebar.y, sidebar.width, sidebar.height]}
    rects[name] = entry
    with open(path, "w") as handle:
        json.dump(rects, handle, indent=2)


def draw_now(win):
    """Draw and swap twice first: a window capture can otherwise return the frame before last."""
    with bpy.context.temp_override(window=win):
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)


def shot_area(name, area):
    draw_now(window())
    with bpy.context.temp_override(window=window(), area=area, region=region_of(area, "WINDOW")):
        bpy.ops.screen.screenshot_area(filepath=os.path.join(RAW, name))
    note_rects(name, area)
    print("SHOT", name, flush=True)


def shot_window(name, win, area=None):
    draw_now(win)
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=os.path.join(RAW, name))
    note_rects(name, area)
    print("SHOT", name, flush=True)


def simulate(kind, value, x, y):
    window().event_simulate(type=kind, value=value, x=x, y=y)


def activate_tab(area, category):
    """Click down the tab strip on the sidebar's right edge until ``category`` is active."""
    region = region_of(area, "UI")
    unit = int(20 * bpy.context.preferences.system.ui_scale)
    x, y = region.x + region.width - unit // 2, region.y + region.height - unit // 2
    while y > region.y and region.active_panel_category != category:
        simulate("MOUSEMOVE", "NOTHING", x, y)
        simulate("LEFTMOUSE", "PRESS", x, y)
        simulate("LEFTMOUSE", "RELEASE", x, y)
        yield 0.15
        y -= unit // 2
    print("TAB", region.active_panel_category, flush=True)


def widen_sidebar(area, extra):
    """Drag the sidebar's inner edge outwards so long model names and prices fit. With region overlap
    the edge sits a little inside the region, so a few offsets are tried."""
    region = region_of(area, "UI")
    start, y = region.width, region.y + int(region.height * 0.6)
    for offset in (14, 18, 10, 22, 6, 2):
        x = region.x + offset
        simulate("MOUSEMOVE", "NOTHING", x + 1, y)
        yield 0.05
        simulate("MOUSEMOVE", "NOTHING", x, y)
        yield 0.1
        simulate("LEFTMOUSE", "PRESS", x, y)
        yield 0.1
        for step in range(1, 11):
            simulate("MOUSEMOVE", "NOTHING", x - extra * step // 10, y)
            yield 0.03
        simulate("LEFTMOUSE", "RELEASE", x - extra, y)
        yield 0.3
        if region_of(area, "UI").width != start:
            break
    print("SIDEBAR", start, "->", region_of(area, "UI").width, flush=True)


def scroll_sidebar(area, notches):
    """Wheel over the panels, away from the tab strip (the wheel over tabs switches tabs)."""
    region = region_of(area, "UI")
    x, y = region.x + region.width // 3, region.y + region.height // 2
    simulate("MOUSEMOVE", "NOTHING", x, y)
    for _ in range(notches):
        simulate("WHEELDOWNMOUSE", "PRESS", x, y)
        yield 0.05
    simulate("MOUSEMOVE", "NOTHING", area.x + area.width // 4, area.y + area.height // 4)  # No tooltip.
    yield 0.5


def redraw(win):
    for area in win.screen.areas:
        area.tag_redraw()


def wait_for(predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline and not predicate():
        yield 0.2


def read_key(path):
    if stat.S_IMODE(os.stat(path).st_mode) & 0o077:
        raise SystemExit("%s must be chmod 600" % path)
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


# -- stages --------------------------------------------------------------------------------------

def listing():
    """Get Extensions with the Eachlabs repository synced and the extension not yet installed."""
    yield 1.0
    bpy.ops.screen.userpref_show(section="EXTENSIONS")
    yield 1.0
    wm = bpy.context.window_manager
    prefs_window = wm.windows[-1]
    wm.extension_search = "Eachlabs"
    yield 1.0
    # Install stays disabled while Blender checks the repositories for updates (-1 means checking).
    yield from wait_for(lambda: wm.extensions_updates != -1, 30)
    repo_index = next(i for i, r in enumerate(bpy.context.preferences.extensions.repos) if r.module == "eachlabs")
    bpy.ops.extensions.package_show_set(pkg_id="eachlabs", repo_index=repo_index)
    redraw(prefs_window)
    yield 1.0
    shot_window("get-extensions.png", prefs_window)


def prepare_view(view3d):
    """Camera view, a wider sidebar and the Eachlabs tab, with nothing selected."""
    space = view3d.spaces.active
    space.show_region_ui = True
    space.region_3d.view_perspective = "CAMERA"
    space.shading.type, space.shading.color_type = "SOLID", "OBJECT"
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    yield 0.5
    yield from widen_sidebar(view3d, 320)
    with bpy.context.temp_override(window=window(), area=view3d, region=region_of(view3d, "WINDOW")):
        bpy.ops.view3d.view_center_camera()
    yield from activate_tab(view3d, "Eachlabs")
    yield 0.5


def configure(view3d):
    """Key, model list, both targets and prompts, and their listed prices."""
    catalog = sys.modules[MODULE + ".catalog"]
    scene = bpy.context.scene
    key_file = os.environ.get("EACHLABS_KEY_FILE")
    if key_file:
        os.environ["EACHLABS_API_KEY"] = read_key(os.path.expanduser(key_file))
    with bpy.context.temp_override(window=window(), area=view3d, region=region_of(view3d, "WINDOW")):
        bpy.ops.eachlabs.refresh_catalog()
    yield from wait_for(lambda: catalog.STATUS["state"] in ("READY", "ERROR"), 180)
    print("CATALOG", catalog.STATUS["state"], catalog.STATUS["message"][:40], flush=True)
    image, video = scene.eachlabs.image, scene.eachlabs.video
    image.target = next(t.label for t in catalog.MODELS.values() if t.key == IMAGE_MODEL)
    image.prompt, video.prompt = IMAGE_PROMPT, VIDEO_PROMPT

    def priced():
        texts = [catalog.price_text(catalog.resolve(t)) for t in (image.target, video.target)]
        return all(t and not t.startswith("Loading") for t in texts)

    yield from wait_for(priced, 60)
    redraw(window())
    yield 1.0
    print("IMAGE", image.target, "|", catalog.price_text(catalog.resolve(image.target)), flush=True)
    print("VIDEO", video.target, "|", catalog.price_text(catalog.resolve(video.target)), flush=True)


def panels():
    view3d = area_of("VIEW_3D")
    yield from prepare_view(view3d)
    shot_area("first-open.png", view3d)

    bpy.ops.screen.userpref_show(section="ADDONS")
    yield 0.8
    prefs_window = bpy.context.window_manager.windows[-1]
    bpy.context.window_manager.addon_search = "Eachlabs"
    addon = bpy.context.preferences.addons[MODULE]
    addon.preferences.api_key = "x" * 40  # A placeholder, shown masked and never sent.
    bpy.ops.preferences.addon_expand(module=MODULE)
    redraw(prefs_window)
    yield 0.8
    shot_window("preferences.png", prefs_window)
    addon.preferences.api_key = ""
    with bpy.context.temp_override(window=prefs_window):
        bpy.ops.wm.window_close()
    yield 0.5

    yield from configure(view3d)
    shot_area("image-panel.png", view3d)
    shot_window("overview.png", window(), view3d)
    bpy.context.scene.eachlabs.video.show_params = True
    yield 0.3
    yield from scroll_sidebar(view3d, 12)
    yield 0.6
    shot_area("video-panel.png", view3d)


def rehearse(api_client):
    """Answer predictions locally: each result is the last uploaded input. The model list stays live."""
    live = api_client.EachlabsClient

    class Rehearsal(live):
        uploads, requests = {}, []

        def upload_file(self, path, content_type, file_type, cancel_event=None):
            url = "https://rehearsal.invalid/" + os.path.basename(path)
            Rehearsal.uploads[url] = path
            return url

        def create_prediction(self, model, values):
            Rehearsal.requests.append(values)
            print("REHEARSAL", model, sorted(values), flush=True)
            return "rehearsal-%d" % len(Rehearsal.requests)

        def get_prediction(self, prediction_id):
            values = Rehearsal.requests[int(prediction_id.split("-")[1]) - 1]
            sent = [u for key in ("video_urls", "image_urls") for u in (values.get(key) or [])]
            return {"status": "success", "output": {"video_url": sent[0], "draft_id": "draft-" + prediction_id}
                    if values.get("video_urls") else sent[0], "metrics": {"cost": 0}}

        def cancel_prediction(self, prediction_id):
            return {}

        def download(self, url, dest_path, cancel_event=None):
            shutil.copyfile(Rehearsal.uploads[url], dest_path)
            return "video/mp4" if url.endswith(".mp4") else "image/png"

    api_client.EachlabsClient = Rehearsal


def results():
    """PAID: one image and one video generation, submitted once each, for the result screenshots."""
    pipeline, jobs = sys.modules[MODULE + ".pipeline"], sys.modules[MODULE + ".jobs"]
    if not os.environ.get("EACHLABS_KEY_FILE"):
        raise SystemExit("the results stage needs EACHLABS_KEY_FILE")
    budget = float(os.environ.get("EACHLABS_TUTORIAL_BUDGET", "1.2"))
    if os.environ.get("EACHLABS_TUTORIAL_REHEARSE"):
        rehearse(sys.modules[MODULE + ".api_client"])
    scene, wm = bpy.context.scene, bpy.context.window_manager
    view3d = area_of("VIEW_3D")
    yield from prepare_view(view3d)
    yield from configure(view3d)
    receipt = {"budget_usd": budget, "jobs": []}

    def record(job):
        receipt["jobs"].append({"action": job.action, "target": job.label, "job_id": job.job_id,
                                "prediction_id": job.remote_id, "state": job.state, "cost_usd": job.cost,
                                "draft_id": job.extras.get("draft_id"), "error": job.error,
                                "message": job.message, "outputs": [os.path.basename(p) for p, _ in job.outputs]})
        with open(os.path.join(OUT, "receipt.json"), "w") as handle:
            json.dump(receipt, handle, indent=2)
        print("JOB", job.action, job.state, job.remote_id, "cost", job.cost, job.error or job.message, flush=True)

    def submit(operator):
        with bpy.context.temp_override(window=window(), area=view3d, region=region_of(view3d, "WINDOW")):
            operator()
        return list(pipeline.REGISTRY.jobs.values())[-1]

    job = submit(bpy.ops.eachlabs.generate_image)
    yield from wait_for(lambda: not job.active, 900)
    record(job)
    if job.state != jobs.DONE:
        return
    yield 1.5
    editor = next((w for w in wm.windows for a in w.screen.areas if a.type == "IMAGE_EDITOR"), None)
    if editor is not None:
        shot_window("image-result.png", editor)
        if editor != window():
            with bpy.context.temp_override(window=editor):
                bpy.ops.wm.window_close()
            yield 0.5

    seconds = (scene.frame_end - scene.frame_start + 1) / scene.render.fps
    estimate = VIDEO_RATE * 2 * seconds  # The same rate per output second and per reference second.
    if (job.cost or 0) + estimate > budget:
        print("BUDGET the video (about $%.2f) would pass $%.2f" % (estimate, budget), flush=True)
        return
    job = submit(bpy.ops.eachlabs.generate_video)
    yield from wait_for(lambda: not job.active, 1800)
    record(job)
    if job.state != jobs.DONE:
        return
    view3d.type = "SEQUENCE_EDITOR"
    space = view3d.spaces.active
    space.view_type, space.show_region_ui = "SEQUENCER_PREVIEW", True
    space.timeline_overlay.show_strip_source = False  # Strip labels would show the local file path.
    scene.frame_set(scene.frame_start + int((scene.frame_end - scene.frame_start) * 0.6))
    yield 0.5
    yield from widen_sidebar(view3d, 320)
    with bpy.context.temp_override(window=window(), area=view3d, region=region_of(view3d, "WINDOW")):
        try:
            bpy.ops.sequencer.view_all()
        except RuntimeError:
            pass  # Framing is cosmetic.
    yield from activate_tab(view3d, "Eachlabs")
    yield from scroll_sidebar(view3d, 40)
    yield 0.8
    shot_window("video-result.png", window(), view3d)
    shot_area("jobs.png", view3d)


def run(steps):
    def step():
        try:
            return next(steps)
        except StopIteration:
            pass
        except Exception:
            traceback.print_exc()
        bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.5)
        return None

    os.makedirs(RAW, exist_ok=True)
    bpy.app.timers.register(step, first_interval=1.5)


# -- crops ---------------------------------------------------------------------------------------

def crop():
    """Turn the raw window and area captures into the images the tutorial uses."""
    import numpy as np

    def load(name):
        image = bpy.data.images.load(os.path.join(RAW, name))
        width, height = image.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        bpy.data.images.remove(image)
        return pixels.reshape(height, width, 4)  # Row 0 is the bottom, like Blender's region coordinates.

    def save(pixels, name):
        height, width = pixels.shape[:2]
        image = bpy.data.images.new(name, width, height, alpha=True)
        image.pixels.foreach_set(np.ascontiguousarray(pixels, dtype=np.float32).ravel())
        image.filepath_raw, image.file_format = os.path.join(OUT, name), "PNG"
        image.save()
        bpy.data.images.remove(image)
        print("IMAGE", name, "%dx%d" % (width, height), flush=True)

    def half(pixels):
        height, width = (pixels.shape[0] // 2) * 2, (pixels.shape[1] // 2) * 2
        return pixels[:height, :width].reshape(height // 2, 2, width // 2, 2, 4).mean(axis=(1, 3))

    def box(pixels, x, y, width, height, thickness=6):
        pixels[y:y + thickness, x:x + width] = ACCENT
        pixels[y + height - thickness:y + height, x:x + width] = ACCENT
        pixels[y:y + height, x:x + thickness] = ACCENT
        pixels[y:y + height, x + width - thickness:x + width] = ACCENT

    rects = json.load(open(os.path.join(OUT, "rects.json")))
    for name in ("first-open.png", "image-panel.png", "video-panel.png"):
        area_x, area_y = rects[name]["area"][:2]
        x, y, width, height = rects[name]["sidebar"]
        save(load(name)[y - area_y:y - area_y + height, x - area_x:x - area_x + width], name)
    overview = load("overview.png")
    x, y, width, height = rects["overview.png"]["sidebar"]
    box(overview, x, y, width, height)
    save(half(overview), "overview.png")
    # Only the add-on column is kept, without its File row, which shows the local profile path. Both are
    # measured on Blender 5.2 at this window size, so check the image after a Blender upgrade.
    preferences = load("preferences.png")[:, 322:]
    top = preferences.shape[0]
    save(np.concatenate((preferences[:top - 448], preferences[top - 398:])), "preferences.png")
    save(load("get-extensions.png"), "get-extensions.png")
    if "jobs.png" in rects:
        area_x, area_y = rects["jobs.png"]["area"][:2]
        x, y, width, height = rects["jobs.png"]["sidebar"]
        save(load("jobs.png")[y - area_y:y - area_y + height, x - area_x:x - area_x + width], "jobs.png")
        save(half(load("video-result.png")), "video-result.png")
    if os.path.isfile(os.path.join(RAW, "image-result.png")):
        save(load("image-result.png"), "image-result.png")


if STAGE == "scene":
    build_scene()
elif STAGE == "crop":
    crop()
else:
    run({"listing": listing, "panels": panels, "results": results}[STAGE]())
