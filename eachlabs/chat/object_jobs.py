"""3D objects a run generates: queueing, claiming placeholders, importing the model in their place, and failures."""

import bpy
import os
import time
import traceback
import uuid
from mathutils import Vector

from .. import asset_cache, chat_loop, generation, objects_3d, plan3d, preferences, scene_build, viewport_marks, workflow_3d
from .live import chat_run
from . import events, texture_jobs, undo_watch


OBJECTS_WAIT_MARGIN = 60.0  # seconds past a job's own time limit before the main thread gives up on it
FAILED_NOTE = ("The 3D model of %s could not be made (%s). Its code version stays: %s. If it is plain, add detail to "
               "it with run_python.")
FAILED_REPLY = "The %s stays built in code: its 3D model was not made (%s)."
UPGRADED = "%s is now a 3D model, at the same place and size."



def _label(description):
    text = " ".join(description.split())[:40].strip()
    return text[:1].upper() + text[1:]



def _jobs(run):
    return [job for job in (chat_run.GEN.get(j) for j in run.jobs) if job is not None]



def queue_plan(run):
    """Main thread, when Build is pressed: queue a job for every approved 3D item, largest first. Nothing the
    person approved depends on the model asking for it."""
    if run is not chat_run._run or run.plan is None:
        return []
    return [queue_item(run, item, place) for place, item in enumerate(run.plan.queue())]



def queue_item(run, item, place):
    """Main thread: one approved 3D item as a queued job (or READY at once from the cache). Its model replaces the
    code version the chat builds under the item's name (``_try_import``)."""
    job_id = "3d-%s" % uuid.uuid4().hex[:6]
    job = generation.Job(job_id, "object", item.name, item.description, item.tier,
                         context={"run": run, "item": item, "placeholders": [], "spots": [], "tints": []},
                         state=generation.QUEUED, priority=generation.priority(item.tier, place))
    folder = chat_run.cache_folder()
    hit = asset_cache.Cache(folder).get(item.description, workflow_3d.cache_tier(item.tier), hold=True)
    chat_run.GEN.add(job)
    run.jobs.append(job_id)
    run.build.generated[job_id] = {"description": item.description, "tier": item.tier, "status": "pending",
                                   "copies": 0, "placeholders": [], "name": plan3d.root_name(item.name)}
    if hit is not None:  # no run and no cost: it waits for its code version like any other
        job.cached, job.cost, job.version = True, 0.0, hit.get("workflow_version") or ""
        chat_run.GEN.emitter(job_id)({"state": generation.READY, "path": hit["path"]})
    else:
        job.context["spec"] = generation.Spec(
            job_id, "object", item.description, item.tier, run.client.api_key, getattr(run.client, "base_url", ""),
            folder, os.path.join(preferences.user_folder(), "workflow-3d.json"),
            getattr(run.client, "user_agent", "eachlabs-blender"), timeout_s=run.objects_timeout, download_s=run.download_seconds, cache_folder=folder,
            picture_prompt=item.picture_prompt)
    chat_run._objects_rows(run)
    return job



def _start_next(run):
    """Main thread: start the next queued job of each kind when none of that kind is running."""
    job = generation.next_queued(_jobs(run))
    if job is None:
        return False
    job.apply({"state": generation.STARTING})
    try:
        chat_run.GEN.start(job, job.context["spec"], chat_run.TEX_WORKER if job.kind == "texture" else chat_run.GEN_WORKER, chat_run.GEN_CLIENT)
    except RuntimeError as exc:  # no thread: the model builds it in code
        job.apply({"state": generation.FAILED, "error": str(exc) or "it could not start"})
    return True



def _picture(run, item):
    """Worker thread: an upgrade's picture prompt, from the target as it is (its parts and materials) and the
    request; the item."""
    looks = chat_loop.Executor(chat_run._call_soon, 30.0, execute=lambda name, args: _target_looks(run))("looks", {})
    if looks is not None:
        parts, materials = looks
        item.picture_prompt = plan3d.upgrade_picture(plan3d.root_name(item.name), run.request, parts, materials)
    return item



def _target_looks(run):
    """Main thread: the part names of the objects a prompt points at, and their materials with a colour word."""
    parts, materials, seen = [], [], set()
    for name in run.targets:
        obj = run.build.scene.objects.get(name)
        for part in [obj] + list(obj.children_recursive) if obj is not None else []:
            parts.append(part.name)
            for slot in part.material_slots:
                mat = slot.material
                if mat is None or mat.session_uid in seen:
                    continue
                seen.add(mat.session_uid)
                colour = mat.diffuse_color
                tree = mat.node_tree
                bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if tree else None
                if bsdf is not None and not bsdf.inputs["Base Color"].is_linked:
                    colour = bsdf.inputs["Base Color"].default_value
                materials.append((mat.name, plan3d.colour_word(tuple(colour))))
    return parts, materials



def _target_size(run):
    """Main thread: (width, depth, height) in metres of the existing objects a prompt points at, with their parts;
    ``None`` when none of them exists."""
    objects = []
    for name in run.targets:
        obj = run.build.scene.objects.get(name)
        if obj is not None:
            objects += [obj] + list(obj.children_recursive)
    corners = [o.matrix_world @ Vector(c) for o in objects if o.type in scene_build.GEOMETRY for c in o.bound_box]
    if not corners:
        return None
    return tuple(max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3))



def _placements_text(job):
    names = job.context.get("placeholders") or []
    return ", ".join(names) if names else "the code version named \"%s\"" % plan3d.root_name(job.name)



def _failed_notes(run):
    """Worker thread: a note per job that failed since the last call, asking the model to build it in code."""
    notes = []
    for job in _jobs(run):
        if job.kind == "texture":
            continue
        if job.state == generation.FAILED and job.job_id not in run.told:
            run.told.add(job.job_id)
            notes.append(FAILED_NOTE % (job.description, generation.without_paths(job.error or "it failed"),
                                        _placements_text(job)))
    return notes



def _wait_objects(run, stop):
    """Worker thread: wait until none of the run's 3D objects is queued or pending. Every job has its own time
    limit and they run one after another, so the wait ends at most one limit per job later."""
    run.final = True
    deadline = time.monotonic() + (len(run.jobs) + 1) * (run.objects_timeout + OBJECTS_WAIT_MARGIN)
    pause = chat_loop.threading.Event()  # never set: a half-second wait made like the executor's
    while time.monotonic() < deadline:
        if not any(job.active for job in _jobs(run)) or stop.is_set():
            return
        pause.wait(0.5)



def _claim(run, job):
    """Main thread: tag the code versions of a job's item, found by name (the item's name, or the name and a copy
    number), as its placeholders: root objects of the chat's own that no other job claimed."""
    item = job.context.get("item")
    build = run.build
    if item is None:
        return
    found = []
    if item.targets:  # an upgrade: the existing objects the person pointed at are its code version
        for name in item.targets:
            obj = build.scene.objects.get(name)
            if obj is not None and not obj.get(scene_build.PLACEHOLDER) and (
                    build.owns(obj) or obj.session_uid in build.allowed):
                found.append(obj)
    words = tuple(plan3d.name_words(item.name)) if not item.targets else ()
    for name in _name_index(run).get(words, []) if words else []:
        obj = build.scene.objects.get(name)
        if (obj is None or obj.get(scene_build.PLACEHOLDER) or obj.get(scene_build.GENERATED) or not build.owns(obj)
                or (obj.parent is not None and build.owns(obj.parent))):
            continue
        found.append(obj)
    if not found:
        return
    for root in found:
        for part in [root] + list(root.children_recursive):
            if (build.owns(part) or part.session_uid in build.allowed) and not part.get(scene_build.PLACEHOLDER):
                part[scene_build.PLACEHOLDER] = job.job_id
    roots = objects_3d.placeholders(build, job.job_id)[0]
    job.context["placeholders"] = sorted(o.name for o in roots)
    entry = build.generated.get(job.job_id)
    if entry is not None:
        entry["placeholders"], entry["copies"] = job.context["placeholders"], len(roots)



def _name_index(run):
    """Main thread: the scene's object names by their words (``plan3d.name_words``), built again only when the
    names change, so a tick does not run the word split over every object for every job."""
    names = tuple(o.name for o in run.build.scene.objects)
    if run.name_key != names:
        index = {}
        for name in names:
            index.setdefault(tuple(plan3d.name_words(name)), []).append(name)
        run.name_key, run.name_index = names, index
    return run.name_index



def _import_object(run, job):
    """Main thread: swap a READY job's model in for its code versions, at their place, size and turn, then remove
    them. One undo step, so the person can bring the code version back."""
    try:
        label = _label(job.description)
        roots, parts = objects_3d.placeholders(run.build, job.job_id)
        spots = [objects_3d.spot(o) for o in roots]
        item = job.context.get("item")
        if item is not None and item.size_m:  # the chat's real size for it, exactly; every copy the same
            mesh, model_size = objects_3d.build_mesh(run.build, job.path, label, item.size_m, item.measure)
            spots = [dict(s, size=0.0) for s in spots]
        else:  # no size given: the code version's longest side
            size = next((s["size"] for s in spots if s.get("size")), 1.0)
            mesh, model_size = objects_3d.build_mesh(run.build, job.path, label, size)
        names = objects_3d.place(run.build, mesh, label, spots, job.job_id, model_size, job.context.get("tints") or ())
        objects_3d.remove(parts)
        if item is not None and len(item.targets) == 1 and len(names) == 1:  # an upgrade keeps the object's name
            obj = run.build.scene.objects.get(names[0])
            if obj is not None and item.targets[0] not in bpy.data.objects:
                obj.name = item.targets[0]
                names = [obj.name]
        job.context["rested"] = objects_3d.rest_on_ground(run.build, names, job.job_id)
    except Exception as exc:  # an unreadable file: the code version stays
        traceback.print_exc()
        job.apply({"state": generation.FAILED, "error": "the model file could not be read (%s)" % (
            str(exc) or type(exc).__name__)})
        return
    job.apply({"state": generation.DONE})
    undo_watch._quiet()  # the chat's own change, not the person's edit
    if not bpy.app.background:  # undo_push crashes in background mode
        try:
            bpy.ops.ed.undo_push(message="Eachlabs: 3D %s" % label)
            undo_watch._changed()
        except RuntimeError:
            traceback.print_exc()
    try:
        viewport_marks.flash(names, time.monotonic())
        viewport_marks.kick()
    except Exception:  # highlights are decoration
        traceback.print_exc()



def _release(run, job):
    """A job that ended without its model: its code versions stop being placeholders and stay as they are."""
    if job.active or job.state == generation.DONE or job.context.get("released"):
        return
    job.context["released"] = True
    try:
        _roots, parts = objects_3d.placeholders(run.build, job.job_id)
    except (RuntimeError, ReferenceError):  # the scene is gone
        return
    for part in parts:
        if scene_build.PLACEHOLDER in part:
            del part[scene_build.PLACEHOLDER]



def _cancel_objects(run, message="Stopped"):
    for job in _jobs(run):  # a 3D run already triggered goes on at Eachlabs after Stop
        if job.kind != "texture" and job.active and job.triggered is not None and not job.cached:
            job.left_running = True
    for job_id in run.jobs:
        chat_run.GEN.cancel(job_id, message)
    for job in _jobs(run):
        _release(run, job)
    chat_run._objects_rows(run)



def _billed(run):
    """True when a 3D run of this run's was left running: by Stop, or past its wait limit."""
    return any(job.kind != "texture" and job.left_running for job in _jobs(run))


def _objects_tick():
    """Main thread: apply job updates, bring finished models in, and give up on a job far past its limit."""
    ready = chat_run.GEN.drain()
    run = chat_run._run
    for job in [j for j in chat_run.GEN.jobs.values() if j.state == generation.READY]:
        if job.context.get("run") is not run or not events._live(run):
            job.apply({"state": generation.CANCELLED, "error": "Stopped"})
            asset_cache.release(job.path)
    if run is None or not (chat_run.STATE.running or ready or any(job.active for job in _jobs(run))):
        return bool(ready)
    for job in _jobs(run):
        if job.kind == "texture":
            if job.state == generation.READY:
                texture_jobs._apply_texture(run, job)
            continue
        if job.active:
            _claim(run, job)
        if job.state != generation.READY:
            continue
        if objects_3d.placeholders(run.build, job.job_id)[0]:
            _import_object(run, job)
        elif run.final:  # the stages are over and no code version of it exists: nothing to replace
            job.apply({"state": generation.FAILED, "error": "no code version of it was built"})
    for job in _jobs(run):
        if job.state in generation.BUSY and job.running_for > run.objects_timeout + OBJECTS_WAIT_MARGIN:
            job.cancel_event.set()
            job.apply({"state": generation.FAILED, "left_running": job.triggered is not None,
                       "error": "it took longer than %d minutes" % round(run.objects_timeout / 60)})
    for job in _jobs(run):
        _release(run, job)
    if events._live(run):
        _start_next(run)
    before = chat_run.STATE.objects
    chat_run._objects_rows(run)
    return bool(ready) or chat_run.STATE.objects != before or any(job.active for job in _jobs(run))
