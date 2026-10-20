"""Interactive check in a real Blender window, with no network. Opens Blender, runs, quits.

Run through scripts/gui-check.sh, which first builds the scene file in background mode:

    blender --background --factory-startup --python tests/gui_check.py -- <dir>
    blender --factory-startup --online-mode <dir>/gui_check.blend --python tests/gui_check.py -- <dir>
    blender --factory-startup --offline-mode <dir>/gui_check.blend --python tests/gui_check.py -- <dir>

Covers what background mode cannot: panels drawing in both editors, the asynchronous render job
and its handlers, the Image Editor, the sequencer, cancellation while the UI keeps ticking, and the
offline message. Results print as PASS/FAIL lines; screenshots go to the given folder.
"""

import os
import shutil
import sys
import time
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import eachlabs  # noqa: E402
from eachlabs import compat, jobs, pipeline  # noqa: E402
from tests.blender_fakes import IMAGE_LABEL, VIDEO_LABEL, FakeClient, load_catalog, offline_api  # noqa: E402

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.path.join(ROOT, ".gui-check")
os.makedirs(OUT, exist_ok=True)
RESULTS = []
STATE = {"gaps": [], "last": None}


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition)))
    print("%s  %s%s" % ("PASS" if condition else "FAIL", name, ("  (%s)" % detail) if detail else ""), flush=True)


def window():
    return bpy.context.window_manager.windows[0]


def area_of(kind):
    return next((a for a in window().screen.areas if a.type == kind), None)


def override(kind="VIEW_3D"):
    area = area_of(kind)
    region = next(r for r in area.regions if r.type == "WINDOW")
    return bpy.context.temp_override(window=window(), area=area, region=region)


def scroll_sidebar(pages):
    """Scroll the 3D Viewport sidebar so panels further down (Jobs) show in screenshots."""
    area = area_of("VIEW_3D")
    region = next(r for r in area.regions if r.type == "UI")
    with bpy.context.temp_override(window=window(), area=area, region=region):
        for _ in range(pages):
            bpy.ops.view2d.scroll_down(page=True)


def screenshot(name):
    path = os.path.join(OUT, name)
    with bpy.context.temp_override(window=window()):
        bpy.ops.screen.screenshot(filepath=path)
    print("SHOT", path, flush=True)


def show_sidebar(area):
    area.spaces.active.show_region_ui = True
    area.tag_redraw()


def panels_in_active_tabs():
    """Scripts cannot pick a sidebar tab (Region.active_panel_category is read-only), so for the
    screenshots the Eachlabs panels join the tab each sidebar opens on. Draw code is unchanged."""
    from eachlabs import panels

    panels.unregister()
    for cls in panels.CLASSES:
        if not getattr(cls, "bl_parent_id", None):
            cls.bl_category = "Item" if cls.bl_space_type == "VIEW_3D" else "Strip"
            cls.bl_order = -1
    panels.register()


def build_scene():
    """Background step: a 48-frame camera orbit, saved so the GUI opens it without the splash."""
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y = 640, 360
    scene.render.fps = 24
    scene.frame_start, scene.frame_end = 10, 57
    pivot = bpy.data.objects.new("Orbit", None)
    scene.collection.objects.link(pivot)
    scene.camera.parent = pivot
    scene.camera.constraints.new("TRACK_TO").target = bpy.data.objects["Cube"]
    pivot.keyframe_insert("rotation_euler", index=2, frame=10)
    pivot.rotation_euler[2] = 6.283185
    pivot.keyframe_insert("rotation_euler", index=2, frame=58)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "gui_check.blend"))


def setup():
    show_sidebar(area_of("VIEW_3D"))
    timeline = area_of("DOPESHEET_EDITOR") or area_of("TIMELINE")
    timeline.type = "SEQUENCE_EDITOR"
    timeline.spaces.active.view_type = "SEQUENCER"
    show_sidebar(timeline)


def wait_for(predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        yield 0.1
    return False


def watch_ticks():
    """Our own timer: if the UI thread blocked, the gap between ticks would grow."""
    now = time.perf_counter()
    if STATE["last"] is not None and STATE.get("measure"):
        STATE["gaps"].append(now - STATE["last"])
    STATE["last"] = now
    return 0.05


def latest_job():
    return list(pipeline.REGISTRY.jobs.values())[-1]


def scenario_online():
    scene = bpy.context.scene
    still_result = os.path.join(OUT, "fake_result.png")
    with offline_api():
        load_catalog()
        scene.eachlabs.image.target = IMAGE_LABEL
        scene.eachlabs.image.prompt = "turn the cube into clay"
        yield 0.5
        screenshot("01-image-ready.png")

        bpy.data.images.new("fake", 320, 180).save_render(still_result)
        FakeClient.results["next"], FakeClient.statuses["next"] = still_result, "success"
        with override():
            bpy.ops.eachlabs.generate_image()
        job = latest_job()
        check("render runs as Blender's render job", job.state == jobs.RENDERING, job.state)
        yield from wait_for(lambda: not job.active, 60)
        yield 0.5
        editors = [a for w in bpy.context.window_manager.windows for a in w.screen.areas if a.type == "IMAGE_EDITOR"]
        shown = [a.spaces.active.image.name for a in editors if a.spaces.active.image]
        check("image job done and shown in an Image Editor",
              job.state == jobs.DONE and any(n.startswith(job.job_id) for n in shown), "%s %s" % (job.state, shown))
        check("camera background holds the result", any(
            bg.image and bg.image.name.startswith(job.job_id) for bg in scene.camera.data.background_images))
        screenshot("02-image-done.png")

        video = scene.eachlabs.video
        video.target = VIDEO_LABEL
        for binding in video.bindings:
            binding.source = "first_frame" if binding.name == "first_frame_url" else "last_frame"
        video.prompt = "slow orbit, golden hour"
        scene.eachlabs.preview_height = "480"
        clip_result = os.path.join(OUT, "fake_result.mp4")
        FakeClient.results["next"], FakeClient.statuses["next"] = clip_result, "processing"
        yield 0.3
        screenshot("03-video-ready.png")
        with override():
            bpy.ops.eachlabs.generate_video()
        job = latest_job()
        # The fake result is the render's own clip; polls report "processing" until it is copied.
        yield from wait_for(lambda: job.state != jobs.RENDERING, 120)
        shutil.copyfile(pipeline.last_inputs(video)["files"]["clip"]["path"], clip_result)
        FakeClient.statuses["next"] = "success"
        yield from wait_for(lambda: not job.active, 60)
        strip = next((s for s in compat.all_strips(scene.sequence_editor) if s.name == "EL " + job.job_id), None)
        check("video job adds a 48-frame strip at frame 10", job.state == jobs.DONE and strip is not None
              and compat.strip_start(strip) == 10 and compat.strip_length(strip) == 48, job.error or job.message)
        workspace = window().workspace
        check("the sequencer shows the scene holding the strip",
              getattr(workspace, "sequencer_scene", scene) == scene, workspace.name)
        viewport = area_of("VIEW_3D")
        viewport.type = "SEQUENCE_EDITOR"
        show_sidebar(viewport)
        yield 0.3
        with override("SEQUENCE_EDITOR"):
            try:
                bpy.ops.sequencer.view_all()
            except RuntimeError:
                pass  # Framing is cosmetic; 5.x polls fail in a freshly switched area.
        yield 0.5
        screenshot("04-video-done.png")
        viewport.type = "VIEW_3D"
        yield 0.3

        FakeClient.statuses["next"] = "processing"
        with override():
            bpy.ops.eachlabs.rerun(action="VIDEO")
        job = latest_job()
        yield from wait_for(lambda: job.state == jobs.RUNNING, 20)
        STATE["measure"] = True
        scroll_sidebar(4)
        yield 2.0
        screenshot("05-running.png")
        with override():
            bpy.ops.eachlabs.cancel_job(job_id=job.job_id)
        yield from wait_for(lambda: not job.active, 10)
        STATE["measure"] = False
        gaps = STATE["gaps"]
        check("cancel ends the job and the remote prediction", job.state == jobs.CANCELLED
              and any(e[0] == "cancel" for e in FakeClient.log), job.message)
        check("UI timer kept ticking while the job ran", gaps and max(gaps) < 0.5,
              "max gap %.3f s over %d ticks" % (max(gaps) if gaps else -1, len(gaps)))
        yield 0.5
        screenshot("06-cancelled.png")

        FakeClient.statuses["next"] = "success"
        FakeClient.fail_create = "Invalid or missing API key (HTTP 401)"
        with override():
            bpy.ops.eachlabs.rerun(action="VIDEO")
        job = latest_job()
        yield from wait_for(lambda: not job.active, 20)
        check("API errors reach the panel", job.state == jobs.FAILED and "HTTP 401" in job.error, job.error)
        FakeClient.fail_create = None
        yield 0.5
        screenshot("07-error.png")


def scenario_offline():
    yield 0.5
    with override():
        try:
            bpy.ops.eachlabs.generate_image()
            message = None
        except RuntimeError as exc:
            message = str(exc)
    check("offline generate reports the online-access message", message and "Online access" in message
          or message and "offline-mode" in message, message)
    check("no job was started while offline", not pipeline.REGISTRY.jobs)
    yield 0.5
    screenshot("01-offline.png")


def run():
    steps = scenario_online() if bpy.app.online_access else scenario_offline()

    def step():
        try:
            return next(steps)
        except StopIteration:
            finish()
        except Exception:
            traceback.print_exc()
            check("scenario ran to completion", False)
            finish()
        return None

    bpy.app.timers.register(step, first_interval=1.0)


def finish():
    failed = [name for name, ok in RESULTS if not ok]
    print("GUI %s: %d checks, %d failed%s" % (bpy.app.version_string, len(RESULTS), len(failed),
                                             (": " + ", ".join(failed)) if failed else ""), flush=True)
    eachlabs.unregister()

    def quit_blender():
        try:
            with bpy.context.temp_override(window=window()):
                bpy.ops.wm.quit_blender()
        finally:
            os._exit(1 if failed else 0)

    bpy.app.timers.register(quit_blender, first_interval=0.5)


if bpy.app.background:
    build_scene()
else:
    eachlabs.register()
    panels_in_active_tabs()
    setup()
    bpy.app.timers.register(watch_ticks, persistent=True)
    run()
