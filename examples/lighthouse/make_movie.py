"""Generate "The Last Light" through the add-on, shot by shot, and export the finished movie.

    blender --background --online-mode <dir>/lighthouse.blend --python examples/lighthouse/make_movie.py -- \\
        [--fake] [--base-url https://api.eachlabs.ai] [--key-file ~/.config/eachlabs/api-key] \\
        [--budget 25] [--concurrency 4] [--shots 1-13]

This drives the same pipeline as the panel buttons, the way an agent would:
1. Generate Image from View on the style camera (p-image-edit) to get one style frame.
2. For each shot, Generate Video from Camera Move with the default video model (Seedance 2.5
   reference-to-video, draft, 480p): the shot's previs clip goes in as @Video1, the style frame as @Image1,
   and the duration matches the 10 s shot, so results land on the timeline unstretched with their audio.
3. Export movie: the sequencer, with sound, as one MP4 next to the .blend.

PAID unless --fake. Spending stops before a shot would push the estimate past --budget; the first shot
runs alone so its settled cost calibrates the estimate. --fake routes every call to a local stand-in
that returns the previs itself, to rehearse the whole run for free.
"""

import argparse
import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]

import shots  # noqa: E402
import generation  # noqa: E402
import eachlabs  # noqa: E402
from eachlabs import catalog, jobs, pipeline  # noqa: E402

IMAGE_MODEL = generation.FakeClient.IMAGE_MODEL


def style_frame(scene):
    """Generate Image from View from the style camera; returns the job."""
    scene.eachlabs.image.target = catalog.MODELS[IMAGE_MODEL].label
    scene.eachlabs.image.prompt = shots.STYLE_PROMPT
    scene.eachlabs.open_in_editor = scene.eachlabs.camera_background = False
    markers = [(m.name, m.frame, m.camera) for m in scene.timeline_markers]
    scene.timeline_markers.clear()  # Markers would switch away from the style camera.
    scene.camera = bpy.data.objects["Cam style"]
    scene.frame_set(shots.STYLE_FRAME)
    error = pipeline.start_image(bpy.context)
    for name, frame, cam in markers:
        scene.timeline_markers.new(name, frame=frame).camera = cam
    if error:
        raise SystemExit("style frame: %s" % error)
    job = generation.latest_job()
    generation.drive(lambda: not job.active, 600)
    if job.state != jobs.DONE:
        raise SystemExit("style frame failed: %s" % job.error)
    generation.log("style frame %s ($%s)" % (os.path.basename(job.outputs[0][0]), job.cost))
    return job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--base-url", default="https://api.eachlabs.ai")
    parser.add_argument("--key-file", default="~/.config/eachlabs/api-key")
    parser.add_argument("--budget", type=float, default=25.0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--shots", default="1-%d" % len(shots.SHOTS))
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    first, last = (int(v) for v in args.shots.split("-"))

    generation.connect(args.fake, args.key_file, args.base_url)
    eachlabs.register()
    scene = bpy.context.scene
    receipt = {"base_url": "fake" if args.fake else args.base_url, "budget_usd": args.budget,
               "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    out_dir = os.path.dirname(bpy.data.filepath)
    generation.load_catalog()
    style = style_frame(scene)
    receipt["style_frame"] = {"job_id": style.job_id, "remote_id": style.remote_id, "cost_usd": style.cost}
    generation.configure_video(bpy, scene, style.outputs[0][0])
    plan = []
    for index in range(first - 1, last):
        start, end = shots.frame_range(index)
        plan.append({"name": shots.SHOTS[index]["name"], "first": start, "last": end,
                     "seconds": shots.SHOT_SECONDS, "prompt": shots.prompt(shots.SHOTS[index])})
    done, entries, spent, stopped = generation.run_shots(bpy, scene, plan, args.budget, args.concurrency,
                                                         spent=style.cost or 0.0)
    receipt.update(shots=entries, spent_usd=round(spent, 4), stopped=stopped)
    if done:
        error = pipeline.export_movie(bpy.context)
        export = generation.latest_job()
        generation.drive(lambda: not export.active, 1800)
        receipt["movie"] = export.outputs[0][0] if export.outputs else None
        generation.log("movie %s %s" % (export.state, export.message or export.error or error))
    bpy.ops.wm.save_mainfile()
    receipt["blend"] = bpy.data.filepath
    receipt["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(os.path.join(out_dir, "movie-receipt.json"), "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2)
    eachlabs.unregister()
    generation.log("%d/%d shots, spent $%.2f, receipt %s" % (len(done), len(plan), spent,
                                                            os.path.join(out_dir, "movie-receipt.json")))
    sys.exit(0 if len(done) == len(plan) and receipt.get("movie") else 1)


main()
