"""Generated textures a run orders: the limit per scene, starting a job and putting the finished picture on its material."""

import bpy
import uuid

from .. import asset_cache, generation, textures
from .live import chat_run


TEXTURE_FAILED = "The texture for %s was not made (%s)."
TEXTURE_LIMIT = "this scene has ordered its %d textures; build the rest of the looks with procedural nodes"
TEXTURE_NO_MATERIAL = "you have no material named %s; make it with run_python first, then order its texture"
TEXTURE_ORDERED = ("Ordered. It is set as %s's Base Color when it is ready, in about a minute; keep working, and do "
                   "not rebuild this material.")



def _textures_left(run):
    """Textures this scene may still order (worker or main thread: it only reads counts)."""
    used = sum(1 for t in list(run.build.textures.values()) if t.get("status") != "failed")
    return max(0, run.textures_limit - used)



def queue_texture(run, args):
    """Main thread: the model's generate_texture call as a queued job, or READY at once from the cache."""
    if _textures_left(run) <= 0:
        return {"ok": False, "error": TEXTURE_LIMIT % run.textures_limit}
    mat = bpy.data.materials.get(args["material"])
    if mat is None or not run.build.owns(mat):
        return {"ok": False, "error": TEXTURE_NO_MATERIAL % args["material"]}
    job_id = "tex-%s" % uuid.uuid4().hex[:6]
    job = generation.Job(job_id, "texture", mat.name, args["description"], generation.TEXTURE_TIER,
                         context={"run": run, "material": mat.name, "tile_m": args.get("tile_m", 1.0)},
                         state=generation.QUEUED, priority=(0, len(run.jobs)))
    folder = chat_run.cache_folder()
    chat_run.GEN.add(job)
    run.jobs.append(job_id)
    run.build.textures[job_id] = {"material": mat.name, "description": args["description"], "status": "pending"}
    hit = asset_cache.Cache(folder).get(args["description"], generation.TEXTURE_TIER, hold=True)
    if hit is not None:
        job.cached, job.cost = True, 0.0
        chat_run.GEN.emitter(job_id)({"state": generation.READY, "path": hit["path"]})
    else:
        job.context["spec"] = generation.Spec(
            job_id, "texture", args["description"], generation.TEXTURE_TIER, run.client.api_key,
            getattr(run.client, "base_url", ""), folder, "", getattr(run.client, "user_agent", "eachlabs-blender"),
            timeout_s=run.texture_seconds, download_s=run.download_seconds, cache_folder=folder)
    chat_run._objects_rows(run)
    return {"ok": True, "texture": job_id, "note": TEXTURE_ORDERED % mat.name}



def _apply_texture(run, job):
    """Main thread: a READY texture onto its material."""
    entry = run.build.textures.get(job.job_id)
    try:
        textures.apply(run.build, job.context["material"], job.path, job.context.get("tile_m", 1.0))
    except Exception as exc:  # the material keeps its own colour
        job.apply({"state": generation.FAILED, "error": str(exc) or type(exc).__name__})
        if entry is not None:
            entry["status"] = "failed"
        return
    job.apply({"state": generation.DONE})
    if entry is not None:
        entry["status"] = "ready"
    chat_run._quiet()
