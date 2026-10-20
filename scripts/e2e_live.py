"""Live end-to-end check against the Eachlabs API. Makes PAID predictions; run only when authorized.

    blender --background --factory-startup --online-mode --python scripts/e2e_live.py -- \\
        --out <dir> --base-url <API URL> [--cancel-test]

The API key is read from the file named by EACHLABS_API_KEY_FILE, which must be readable only by you
(chmod 600). It is never printed.
Each paid run is submitted once; a receipt without secrets is written to <dir>/receipt.json.

Runs, in order: invalid-key check (free), Test connection (free), catalog refresh (free),
Generate Image from View with p-image-edit (about $0.01), Generate Video from Camera Move on a
48-frame orbit with minimax-h3-max-turbo-image-to-video at 480P (about $0.03), and with
--cancel-test a re-run that is cancelled while running (up to about $0.03 if the provider finishes).
"""

import argparse
import json
import os
import stat
import sys
import time

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import eachlabs  # noqa: E402
from eachlabs import api_client, catalog, compat, jobs, main_thread, pipeline, preferences  # noqa: E402

IMAGE_MODEL = "p-image-edit"
VIDEO_MODEL = "minimax-h3-max-turbo-image-to-video"
RESULTS, RECEIPT = [], {"runs": []}


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition)))
    print("%s  %s%s" % ("PASS" if condition else "FAIL", name, ("  (%s)" % detail) if detail else ""), flush=True)


def read_key():
    if not os.environ.get("EACHLABS_API_KEY_FILE"):
        raise SystemExit("set EACHLABS_API_KEY_FILE to a chmod 600 file holding the key")
    path = os.path.expanduser(os.environ["EACHLABS_API_KEY_FILE"])
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise SystemExit("%s must be chmod 600 (is %o)" % (path, mode))
    with open(path, encoding="utf-8") as handle:
        key = handle.read().strip()
    if not key:
        raise SystemExit("%s is empty" % path)
    return key


def drive(until, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline and not until():
        main_thread.tick()
        time.sleep(0.1)
    main_thread.tick()
    return until()


def label_for(slug):
    target = catalog.MODELS.get(slug)
    return target.label if target else None


def run_job(start, timeout):
    error = start()
    if error:
        return None, error
    job = list(pipeline.REGISTRY.jobs.values())[-1]
    drive(lambda: not job.active, timeout)
    RECEIPT["runs"].append({"job_id": job.job_id, "action": job.action, "target": job.label, "state": job.state,
                            "remote_id": job.remote_id, "cost_usd": job.cost, "error": job.error,
                            "outputs": [os.path.basename(p) for p, _ in job.outputs]})
    return job, None


def orbit(scene):
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {
        e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} else "BLENDER_EEVEE"
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = 16
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.fps = 24
    scene.frame_start, scene.frame_end = 1, 48
    pivot = bpy.data.objects.new("Orbit", None)
    scene.collection.objects.link(pivot)
    scene.camera.parent = pivot
    scene.camera.constraints.new("TRACK_TO").target = bpy.data.objects["Cube"]
    pivot.keyframe_insert("rotation_euler", index=2, frame=1)
    pivot.rotation_euler[2] = 6.283185
    pivot.keyframe_insert("rotation_euler", index=2, frame=49)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--cancel-test", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    os.makedirs(args.out, exist_ok=True)
    os.environ["EACHLABS_API_KEY"] = read_key()
    os.environ["EACHLABS_BASE_URL"] = args.base_url
    RECEIPT.update(base_url=args.base_url, blender=bpy.app.version_string, started=time.strftime("%Y-%m-%dT%H:%M:%S%z"))

    eachlabs.register()
    scene = bpy.context.scene
    orbit(scene)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.out, "e2e.blend"))
    check("online access is on", compat.online_problem() is None, compat.online_problem() or "")

    bad = api_client.EachlabsClient("invalid-key-for-e2e", args.base_url, preferences.user_agent())
    try:
        bad.get_balance()
        check("invalid key is rejected with a readable error", False)
    except api_client.ApiError as exc:
        check("invalid key is rejected with a readable error", exc.status == 401, exc.message)

    balance = preferences.client().get_balance().get("balance_usd")
    check("Test connection reads the balance", isinstance(balance, (int, float)), "$%.2f" % balance)
    RECEIPT["balance_before_usd"] = balance

    catalog.refresh()
    drive(lambda: catalog.STATUS["state"] in ("READY", "ERROR"), 120)
    check("catalog loads", catalog.loaded() and label_for(IMAGE_MODEL) and label_for(VIDEO_MODEL), catalog.STATUS["message"])

    image = scene.eachlabs.image
    image.target = label_for(IMAGE_MODEL)
    image.prompt = "Turn the grey cube into a glossy red ceramic cube on a studio backdrop"
    check("image model pre-binds the still", [(b.name, b.source) for b in image.bindings] == [("images", "still")])
    drive(lambda: catalog.COSTS.get(IMAGE_MODEL) not in (None, "loading"), 30)
    check("listed price shown before running", "$" in catalog.price_text(catalog.resolve(image.target)),
          catalog.price_text(catalog.resolve(image.target)))
    job, error = run_job(lambda: pipeline.start_image(bpy.context), 600)
    loaded = job and any(img.get("eachlabs_job") == job.job_id for img in bpy.data.images)
    check("Generate Image from View completes and imports", job and job.state == jobs.DONE and loaded,
          error or (job and (job.error or job.message)))

    video = scene.eachlabs.video
    video.target = label_for(VIDEO_MODEL)
    for binding in video.bindings:
        binding.source = {"image_url": "first_frame", "end_image_url": "last_frame"}.get(binding.name, "NONE")
    for param in video.params:
        if param.name == "resolution":
            param.enabled, param.value_enum = True, "480P"
    video.prompt = "A slow cinematic orbit around a glossy cube, soft studio light"
    scene.eachlabs.preview_height = "720"
    job, error = run_job(lambda: pipeline.start_video(bpy.context), 1200)
    strip = job and next((s for s in compat.all_strips(scene.sequence_editor) if s.name == "EL " + job.job_id), None)
    top = strip and next((s for s in compat.all_strips(scene.sequence_editor) if s.name == strip.name + " speed"), strip)
    check("Generate Video places a strip at the render start spanning the 48-frame range",
          job and job.state == jobs.DONE and strip and compat.strip_start(top) == 1 and compat.strip_length(top) == 48,
          error or (job and (job.error or job.message)))

    if args.cancel_test:
        error = pipeline.rerun(bpy.context, "VIDEO")
        job = list(pipeline.REGISTRY.jobs.values())[-1]
        drive(lambda: job.state in (jobs.RUNNING, jobs.QUEUED) and job.remote_id or not job.active, 120)
        pipeline.cancel(job.job_id)
        started = time.time()
        drive(lambda: not job.active, 30)
        check("cancelling a running job stops it promptly", job.state == jobs.CANCELLED and time.time() - started < 10,
              error or job.message)
        RECEIPT["runs"].append({"job_id": job.job_id, "action": "VIDEO (cancelled re-run)", "state": job.state,
                                "remote_id": job.remote_id, "message": job.message})

    RECEIPT["checks"] = [{"name": n, "ok": ok} for n, ok in RESULTS]
    with open(os.path.join(args.out, "receipt.json"), "w", encoding="utf-8") as handle:
        json.dump(RECEIPT, handle, indent=2)
    eachlabs.unregister()
    failed = [n for n, ok in RESULTS if not ok]
    print("E2E %s: %d checks, %d failed%s" % (bpy.app.version_string, len(RESULTS), len(failed),
                                             (": " + ", ".join(failed)) if failed else ""), flush=True)
    sys.exit(1 if failed else 0)


main()
