"""The sidebar and the job pipeline, online and offline."""

import os
import shutil

import bpy

from eachlabs import compat, jobs, pipeline
from tests.blender_fakes import FakeClient, IMAGE_LABEL, VIDEO_LABEL, load_catalog, offline_api
from tests.gui_check.args import OUT
from tests.gui_check.common import (STATE, area_of, check, latest_job, override, screenshot, scroll_sidebar,
                                    show_sidebar, wait_for, window)


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
