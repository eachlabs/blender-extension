"""Blender smoke test: export, import and the full job pipeline, with no network.

    blender --background --factory-startup --python-exit-code 1 --python tests/smoke.py

The add-on is registered from this checkout. Network calls go to a fake client that serves local
files, so this exercises rendering, MP4 packaging, the worker thread, the main-thread dispatcher,
cancellation, re-run and sequencer timing without an API key.
"""

import os
import shutil
import sys
import tempfile
import time
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import eachlabs  # noqa: E402
from eachlabs import capabilities as caps, catalog, compat, importers, jobs, main_thread, naming, pipeline, render_export, timing  # noqa: E402
from tests.blender_fakes import (IMAGE_LABEL, REFERENCE_LABEL, VIDEO_LABEL, FakeClient, load_catalog,  # noqa: E402
                                 offline_api)

RESULTS = []
WORK = tempfile.mkdtemp(prefix="eachlabs-smoke-")


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    print("%s  %s%s" % ("PASS" if condition else "FAIL", name, ("  (%s)" % detail) if detail else ""))


def orbit_scene(start=10, end=57):
    """Default cube with a camera orbiting it over a 48-frame range."""
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 640, 360, 100
    scene.render.fps, scene.render.fps_base = 24, 1.0
    scene.frame_start, scene.frame_end = start, end
    scene.frame_set(start)
    pivot = bpy.data.objects.new("Orbit", None)
    scene.collection.objects.link(pivot)
    camera = scene.camera
    camera.parent = pivot
    track = camera.constraints.new("TRACK_TO")
    track.target = bpy.data.objects["Cube"]
    pivot.rotation_euler = (0, 0, 0)
    pivot.keyframe_insert("rotation_euler", index=2, frame=start)
    pivot.rotation_euler = (0, 0, 6.283185)
    pivot.keyframe_insert("rotation_euler", index=2, frame=end + 1)
    for fcurve in pivot.animation_data.action.fcurves if hasattr(pivot.animation_data.action, "fcurves") else ():
        for point in fcurve.keyframe_points:
            point.interpolation = "LINEAR"
    return scene


def settings_tuple(scene):
    r = scene.render
    return (r.filepath, r.resolution_percentage, r.image_settings.file_format, r.use_sequencer,
            scene.frame_start, scene.frame_end)


def test_export(scene):
    before = settings_tuple(scene)
    still = os.path.join(WORK, "inputs", "s_still.png")
    done = []
    error = render_export.render_still(bpy.context, scene, still, render_export.STILL, lambda: done.append(1),
                                       lambda m: done.append(m))
    check("still render writes a PNG", error is None and done == [1] and os.path.getsize(still) > 0, error or "")
    check("still render restores render settings", settings_tuple(scene) == before)

    frames = []
    prefix = naming.frame_pattern(os.path.join(WORK, "inputs"), "v")
    pct = timing.preview_percentage(scene.render.resolution_y, 180)
    error = render_export.render_frames(bpy.context, scene, prefix, scene.frame_start, scene.frame_end, pct,
                                        render_export.STILL, frames.extend, lambda m: frames.append(m))
    check("frame range renders 48 PNGs", error is None and len(frames) == 48 and all(os.path.isfile(p) for p in frames),
          error or "%d files" % len(frames))
    check("frame range restores render settings", settings_tuple(scene) == before)
    out = {role: os.path.join(WORK, "inputs", "v_%s.%s" % (role, "mp4" if role == "clip" else "png"))
           for role in ("clip", "first_frame", "last_frame")}
    render_export.package_clip(frames, 24, 1.0, out["clip"], out["first_frame"], out["last_frame"])
    count, fps = importers.probe_movie(out["clip"])
    check("clip is 48 frames at 24 fps", (count, round(fps, 3)) == (48, 24.0), "%d @ %.3f" % (count, fps))
    with open(frames[0], "rb") as a, open(out["first_frame"], "rb") as b:
        first_same = a.read() == b.read()
    with open(frames[-1], "rb") as a, open(out["last_frame"], "rb") as b:
        last_same = a.read() == b.read()
    check("first and last frames match the clip ends", first_same and last_same)
    check("render_frames left use_sequencer as it was", scene.render.use_sequencer == before[3])
    return still, frames, out


def test_import(scene, still, frames):
    image = importers.load_image(still, "job-a")
    check("result loads as an Image datablock", image.name in bpy.data.images and image.size[0] == 640)
    note = importers.set_camera_background(scene, image)
    again = importers.set_camera_background(scene, importers.load_image(still, "job-b"))
    slots = scene.camera.data.background_images
    check("camera background set and slot reused", note is None and again is None and len(slots) == 1
          and scene.camera.data.show_background_images)

    # Like a model returning 2.4 s at 30 fps for a 2 s render at 24 fps: 72 frames, not 48.
    clip30 = os.path.join(WORK, "result30.mp4")
    render_export.encode_mp4(frames + frames[:24], 30, 1.0, clip30)
    sed = scene.sequence_editor_create()
    blocker = compat.strips(sed).new_effect("blocker", "COLOR", 1, 1, frame_end=200) if not hasattr(sed, "strips") \
        else compat.strips(sed).new_effect("blocker", "COLOR", 1, 1, length=199)
    info = importers.add_movie_strip(scene, clip30, 10, 48, timing.FIT_RANGE, "EL fit")
    check("72-frame 30 fps result fitted to the 48-frame render at 24 fps",
          info["frame_start"] == 10 and info["length"] == 48 and info["channel"] == 2 and info["source_frames"] == 72,
          "start %d len %d ch %d via %s" % (info["frame_start"], info["length"], info["channel"], info["method"]))
    check("retimed with a Stretch speed effect above the movie strip",
          info["method"] == "speed_effect" and info["speed_strip"] is not None, info["method"])
    keep = importers.add_movie_strip(scene, clip30, 100, 48, timing.KEEP_TIMING, "EL keep")
    check("keep timing spans the clip's real duration", keep["length"] == 58 and keep["frame_start"] == 100,
          "len %d" % keep["length"])
    same = importers.add_movie_strip(scene, out_clip(frames), 10, 48, timing.FIT_RANGE, "EL same")
    check("matching fps and length needs no retime", same["method"] == "none" and same["length"] == 48)
    compat.strips(sed).remove(blocker)


def out_clip(frames):
    path = os.path.join(WORK, "result24.mp4")
    if not os.path.isfile(path):
        render_export.encode_mp4(frames, 24, 1.0, path)
    return path


def test_timing_content():
    """Stretched, compressed and unchanged strips show the same source frame at the same relative point."""
    size, count = (64, 36), 48
    paths = []
    for index in range(count):
        image = bpy.data.images.new("gray%d" % index, *size)
        value = index / (count - 1)
        image.pixels[:] = [value, value, value, 1.0] * (size[0] * size[1])
        path = os.path.join(WORK, "gray", "g_%04d.png" % (index + 1))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        image.filepath_raw, image.file_format = path, "PNG"
        image.save()
        bpy.data.images.remove(image)
        paths.append(path)
    clip = os.path.join(WORK, "gray30.mp4")
    render_export.encode_mp4(paths, 30, 1.0, clip)
    samples = {}
    for length in (60, 24, 48):
        scene = bpy.data.scenes.new("timing%d" % length)
        scene.render.fps = 24
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = size[0], size[1], 100
        scene.view_settings.view_transform = "Standard"
        compat.set_image_output(scene.render.image_settings, "PNG")
        importers.add_movie_strip(scene, clip, 10, length, timing.FIT_RANGE, "gray")
        row = []
        for fraction in (0.0, 0.5, 1.0):
            frame = 10 + min(length - 1, int(round(fraction * (length - 1))))
            scene.frame_set(frame)
            out = os.path.join(WORK, "gray", "sample_%d_%d.png" % (length, frame))
            scene.render.filepath = out
            # A still render uses the context scene's frame, so make this scene the context.
            with bpy.context.temp_override(scene=scene):
                bpy.ops.render.render(write_still=True)
            image = bpy.data.images.load(out)
            i = (size[1] // 2 * size[0] + size[0] // 2) * 4
            row.append(image.pixels[i:i + 1][0])
            bpy.data.images.remove(image)
        samples[length] = row
        bpy.data.scenes.remove(scene)
    reference = samples[48]
    close = all(abs(samples[n][k] - reference[k]) < 0.03 for n in (60, 24) for k in range(3))
    check("timing stretch maps content proportionally", close and reference[2] - reference[0] > 0.3,
          "; ".join("%d: %s" % (n, ["%.2f" % v for v in samples[n]]) for n in (48, 60, 24)))


def drive(job_id, until, timeout=60):
    """Tick the dispatcher like Blender's timer would; return the longest tick in seconds."""
    longest, deadline = 0.0, time.time() + timeout
    while time.time() < deadline:
        start = time.perf_counter()
        main_thread.tick()
        longest = max(longest, time.perf_counter() - start)
        job = pipeline.REGISTRY.get(job_id)
        if job is not None and until(job):
            break
        time.sleep(0.02)
    return longest


def test_pipeline(scene, still, clip24):
    with offline_api():
        load_catalog()
        labels = [item.name for item in bpy.context.window_manager.eachlabs.video_targets]
        check("catalog fills the searchable lists", VIDEO_LABEL in labels, str(labels))

        image_settings = scene.eachlabs.image
        image_settings.target = IMAGE_LABEL
        image_settings.prompt = "make it clay"
        check("single-input model pre-binds the still",
              [(b.name, b.source) for b in image_settings.bindings] == [("image_url", "still")])
        main_thread.tick()
        check("listed price is shown", catalog.price_text(catalog.resolve(image_settings.target)) == "$0.10 per execution")

        FakeClient.results["next"], FakeClient.statuses["next"] = still, "success"
        bpy.ops.eachlabs.generate_image()
        job = list(pipeline.REGISTRY.jobs.values())[-1]
        drive(job.job_id, lambda j: not j.active)
        check("image job completes and imports", job.state == jobs.DONE and any(
            img.get(importers.TAG) == job.job_id for img in bpy.data.images), job.error or job.message)
        created = [entry for entry in FakeClient.log if entry[0] == "create"][-1]
        check("image request carries the uploaded still and prompt", created[2] == {
            "prompt": "make it clay", "image_url": "https://fake.invalid/%s_still.png" % job.job_id}, str(created[2]))

        video_settings = scene.eachlabs.video
        video_settings.target = VIDEO_LABEL
        check("two-input model is left for the user to bind", all(b.source == "NONE" for b in video_settings.bindings))
        error = pipeline.start_video(bpy.context)
        check("unbound inputs stop the action with a message", error and "receives the render" in error, error or "")
        for binding in video_settings.bindings:
            binding.source = "first_frame" if binding.name == "first_frame_url" else "last_frame"
        video_settings.prompt = "slow orbit"
        FakeClient.results["next"] = clip24
        bpy.ops.eachlabs.generate_video()
        job = list(pipeline.REGISTRY.jobs.values())[-1]
        drive(job.job_id, lambda j: not j.active)
        strip = next((s for s in compat.all_strips(scene.sequence_editor) if s.name == "EL " + job.job_id), None)
        check("video job places a strip at the render start", job.state == jobs.DONE and strip is not None
              and compat.strip_start(strip) == scene.frame_start and compat.strip_length(strip) == 48,
              job.error or (strip and "%d+%d" % (compat.strip_start(strip), compat.strip_length(strip))))
        created = [entry for entry in FakeClient.log if entry[0] == "create"][-1]
        check("video request sends first and last frames and the default duration",
              created[2].get("first_frame_url", "").endswith("_first_frame.png")
              and created[2].get("last_frame_url", "").endswith("_last_frame.png") and created[2].get("duration") == 5,
              str(created[2]))
        folder = naming.output_dir(bpy.data.filepath)
        names = os.listdir(folder)
        check("files carry the job ID", all(any(n.startswith(job.job_id + suffix) for n in names) for suffix in (
            "_clip.mp4", "_first_frame.png", "_last_frame.png", "_result_1.mp4", ".json")), folder)

        uploads_before = len([e for e in FakeClient.log if e[0] == "upload"])
        video_settings.prompt = "faster orbit"
        bpy.ops.eachlabs.rerun(action=caps.VIDEO)
        rerun_job = list(pipeline.REGISTRY.jobs.values())[-1]
        drive(rerun_job.job_id, lambda j: not j.active)
        uploads_after = len([e for e in FakeClient.log if e[0] == "upload"])
        created = [entry for entry in FakeClient.log if entry[0] == "create"][-1]
        check("re-run reuses rendered and uploaded inputs", rerun_job.state == jobs.DONE and uploads_after == uploads_before
              and created[2]["prompt"] == "faster orbit", rerun_job.error)

        FakeClient.statuses["next"] = "processing"
        bpy.ops.eachlabs.rerun(action=caps.VIDEO)
        slow = list(pipeline.REGISTRY.jobs.values())[-1]
        drive(slow.job_id, lambda j: j.state == jobs.RUNNING, timeout=10)
        pipeline.cancel(slow.job_id)
        longest = drive(slow.job_id, lambda j: not j.active, timeout=10)
        check("cancel stops polling and cancels the prediction", slow.state == jobs.CANCELLED
              and ("cancel", slow.remote_id) in FakeClient.log, slow.message)
        check("dispatcher ticks stay short while a job runs", longest < 0.05, "%.4f s" % longest)


def tone_clip(frames, name, fps=24):
    """An MP4 with picture and a 440 Hz stereo tone, made with Blender and the standard library."""
    import math
    import struct
    import wave
    seconds = frames / fps
    wav = os.path.join(WORK, name + ".wav")
    with wave.open(wav, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        samples = (int(6000 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(int(48000 * seconds)))
        handle.writeframes(b"".join(struct.pack("<hh", v, v) for v in samples))
    scene = bpy.data.scenes.new("tone")
    scene.render.fps = fps
    scene.render.resolution_x, scene.render.resolution_y = 64, 36
    collection = compat.strips(scene.sequence_editor_create())
    kwargs = {"length": frames} if hasattr(scene.sequence_editor, "strips") else {"frame_end": frames + 1}
    collection.new_effect("color", "COLOR", 1, 1, **kwargs)
    collection.new_sound("tone", wav, 2, 1)
    scene.frame_start, scene.frame_end = 1, frames
    compat.set_video_output(scene.render.image_settings)
    render_export._h264(scene.render.ffmpeg, audio=True)
    scene.render.filepath = os.path.join(WORK, name + ".mp4")
    scene.render.use_file_extension = False
    bpy.ops.render.render(animation=True, scene=scene.name)
    bpy.data.scenes.remove(scene)
    return os.path.join(WORK, name + ".mp4")


def test_audio():
    scene = bpy.data.scenes.new("audio")
    scene.render.fps = 24
    scene.sync_mode = "NONE"
    synced = importers.add_movie_strip(scene, tone_clip(48, "tone48"), 1, 48, timing.FIT_RANGE, "EL a", with_audio=True)
    check("clip audio imports in sync", synced["audio"] == "synced" and synced["method"] == "none"
          and scene.sync_mode == "AUDIO_SYNC", str(synced))
    stretched = importers.add_movie_strip(scene, tone_clip(72, "tone72"), 100, 48, timing.FIT_RANGE, "EL b",
                                          with_audio=True)
    sound = next(s for s in compat.all_strips(scene.sequence_editor) if s.name == "EL b audio")
    check("retimed clip keeps its audio muted", stretched["audio"] == "muted" and sound.mute
          and compat.strip_length(sound) == 48, str(stretched))
    # Like Seedance returning 241 frames for a 240-frame render.
    tail = importers.add_movie_strip(scene, tone_clip(49, "tone49"), 300, 48, timing.FIT_RANGE, "EL t",
                                     with_audio=True)
    sound = next(s for s in compat.all_strips(scene.sequence_editor) if s.name == "EL t audio")
    check("a one-frame tail is trimmed and the audio stays live", tail["method"] == "trim"
          and tail["length"] == 48 and tail["audio"] == "synced" and not sound.mute
          and compat.strip_length(sound) == 48, str(tail))
    silent = importers.add_movie_strip(scene, out_clip_path(), 200, 48, timing.FIT_RANGE, "EL c", with_audio=True)
    check("silent clip adds no sound strip", silent["audio"] == "none"
          and not any(s.name == "EL c audio" for s in compat.all_strips(scene.sequence_editor)))
    bpy.data.scenes.remove(scene)


def out_clip_path():
    return os.path.join(WORK, "result24.mp4")


def test_reference_flow(scene):
    """Default model, file source, duration matching, draft id, audio, then the movie export."""
    with offline_api():
        scene.eachlabs.video.target = ""
        load_catalog()
        video = scene.eachlabs.video
        enabled = {p.name: getattr(p, "value_" + {"enum": "enum", "bool": "bool"}.get(p.kind, "string"))
                   for p in video.params if p.enabled}
        check("default video model is selected with draft at 480p",
              video.target == REFERENCE_LABEL and enabled == {"resolution": "480p", "draft": True}
              and {b.name: b.source for b in video.bindings}["video_urls"] == "clip", "%s %s" % (video.target, enabled))
        style = os.path.join(WORK, "inputs", "s_still.png")
        for binding in video.bindings:
            if binding.name == "image_urls":
                binding.source, binding.filepath = "file", style
        video.prompt = "Follow the camera motion of @Video1 in the style of @Image1"
        FakeClient.results["next"], FakeClient.statuses["next"] = tone_clip(48, "seedance48"), "success"
        FakeClient.draft_id = "draft-abc"
        bpy.ops.eachlabs.generate_video()
        job = list(pipeline.REGISTRY.jobs.values())[-1]
        drive(job.job_id, lambda j: not j.active)
        created = [entry for entry in FakeClient.log if entry[0] == "create"][-1][2]
        check("reference request: clip, style file, matched duration, draft",
              created.get("video_urls", [""])[0].endswith("_clip.mp4") and created.get("image_urls") == [
                  "https://fake.invalid/s_still.png"] and created.get("duration") == "4"
              and created.get("draft") is True and created.get("resolution") == "480p", str(created))
        check("draft id kept and audio imported", job.state == jobs.DONE and job.extras.get("draft_id") == "draft-abc"
              and "audio on channel" in job.message and "draft draft-abc" in job.message, job.error or job.message)
        FakeClient.draft_id = None

        error = pipeline.export_movie(bpy.context)
        export = list(pipeline.REGISTRY.jobs.values())[-1]
        main_thread.tick()
        movie = export.outputs[0][0] if export.outputs else ""
        frames, _fps = importers.probe_movie(movie) if movie else (0, 0)
        probe = bpy.data.scenes.new("probe")
        sound = compat.strips(probe.sequence_editor_create()).new_sound("m", movie, 1, 1) if movie else None
        editor = scene.sequence_editor
        span = max(compat.strip_end(s) for s in compat.all_strips(editor)) - min(
            compat.strip_start(s) for s in compat.all_strips(editor))
        check("export writes one MP4 with sound spanning the sequencer", error is None and export.state == jobs.DONE
              and frames == span and sound is not None and compat.strip_length(sound) > 1,
              error or "%s frames=%d span=%d" % (os.path.basename(movie), frames, span))
        bpy.data.scenes.remove(probe)


def test_offline():
    if bpy.app.online_access:
        check("offline checks skipped (Blender started with online access)", True)
        return
    message = pipeline.start_image(bpy.context)
    check("offline generate returns the explanatory message", message and "Online access" in message, message or "")
    try:
        bpy.ops.eachlabs.refresh_catalog()
        raised = None
    except RuntimeError as exc:  # Blender turns an operator's ERROR report into RuntimeError for scripts.
        raised = str(exc)
    check("offline refresh reports instead of crashing", raised and "Online access" in raised, raised or "")


def main():
    eachlabs.register()
    try:
        scene = orbit_scene()
        still, frames, outputs = test_export(scene)
        test_import(scene, still, frames)
        test_timing_content()
        test_offline()
        test_pipeline(scene, still, out_clip(frames))
        test_audio()
        test_reference_flow(scene)
    except Exception:
        traceback.print_exc()
        check("smoke test ran to completion", False)
    finally:
        eachlabs.unregister()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n%d checks, %d failed%s" % (len(RESULTS), len(failed), (": " + ", ".join(failed)) if failed else ""))
    print("Blender %s, work dir %s" % (bpy.app.version_string, WORK))
    if failed:
        sys.exit(1)
    shutil.rmtree(WORK, ignore_errors=True)


main()
