"""The plan before Build: asking, answers and toggles, the outcome lines, and building what is still missing."""

import time
import traceback

from .. import asset_cache, chat_loop, generation, main_thread, plan3d, scene_build, workflow_3d
from .live import chat_run
from . import texture_jobs


NOT_BUILT = "Not built: %s."
HOLLOW_NOTE = ("%s holds no geometry of its own: what the person means are other objects of yours, found by where "
               "they stand and what they are (read_scene lists them). Change those, and attach each to it.")



def _ask_plan(run, plan, post):
    """Worker thread: show ``plan`` and wait for Build; ``False`` (the run ends, the prompt comes back) on Cancel or
    Stop."""
    post({"type": "plan", "plan": plan})
    while not run.plan_event.wait(0.25) and not run.cancel.is_set():
        pass
    if run.cancel.is_set() or run.plan_answer not in ("build", "limit", "raise"):
        chat_run._call_soon(lambda: _plan_cancelled(run))
        return False
    if run.plan_answer == "raise" and plan.rounds_needed:  # for this run only; the setting stays
        run.rounds_cap = plan.rounds_needed
    return True



def _plan(run, prompt, llm, post):
    """Worker thread: ask the model which objects are 3D; ``None`` when the answer holds no plan, so everything is
    built in code. Called with the model without hidden reasoning, for a short answer."""
    existing = [e["description"] for e in list(run.build.generated.values()) if e.get("status") != "failed"]
    limit = max(0, run.objects_limit - len(existing))  # the chat's suggestions only
    post({"type": "planning", "state": True})
    messages = [{"role": "system", "content": plan3d.system(limit, bool(run.earlier), existing)},
                {"role": "user", "content": plan3d.request(prompt, run.earlier)}]
    try:
        reply = llm(messages, [])
        text = reply["choices"][0]["message"].get("content") or ""
    except Exception as exc:  # no plan: the run builds everything in code
        chat_loop.debug_log({"stage": "plan", "error": str(exc)}, run.secrets)
        text = ""
    finally:
        post({"type": "planning", "state": False})
    chat_loop.debug_log({"stage": "plan", "messages": messages, "reply": text}, run.secrets)
    cache = asset_cache.Cache(run.cache_folder)
    if not run.cache_folder:
        plan = plan3d.parse(text, limit)
    else:
        plan = plan3d.parse(text, limit, lambda description, tier: cache.has(description,
                                                                            workflow_3d.cache_tier(tier)))
    if plan is not None:
        plan3d.bind(plan, prompt)  # what the person called real goes in 3D, whatever the chat chose
        if run.cache_folder:
            plan3d.mark_cached(plan, lambda description, tier: cache.has(description, workflow_3d.cache_tier(tier)))
    return plan



def plan_answer(answer):
    """Main thread: Build or Cancel on the plan; Cancel ends the run before anything is built and keeps the prompt."""
    run = chat_run._run
    if run is None or not chat_run.STATE.plan_waiting:
        return False
    chat_run.STATE.plan_waiting = False
    if chat_run.STATE.plan_since is not None:  # the person's time on the plan is not the run's
        chat_run.STATE.plan_waited += time.monotonic() - chat_run.STATE.plan_since
        chat_run.STATE.plan_since = None
    run.plan_answer = answer
    run.plan_event.set()
    main_thread.tag_redraw()
    return True



def plan_toggle(index):
    """Main thread: move a plan item between 3D and code."""
    plan = chat_run.STATE.plan
    if plan is None or not chat_run.STATE.plan_waiting:
        return False
    moved = plan.toggle(index)
    if moved and chat_run._run is not None and chat_run._run.cache_folder:
        cache = asset_cache.Cache(chat_run._run.cache_folder)
        plan3d.mark_cached(plan, lambda description, tier: cache.has(description, workflow_3d.cache_tier(tier)))
    main_thread.tag_redraw()
    return moved



def _plan_cancelled(run):
    """Main thread: the plan was cancelled. Nothing was built; the bar goes back to idle with the prompt."""
    if run is not chat_run._run:
        return
    chat_run.STATE.running, chat_run.STATE.planning, chat_run.STATE.plan, chat_run.STATE.plan_waiting = False, False, None, False
    if run.cancel.is_set():  # the file was closed or the add-on turned off: nothing to give back
        return
    chat_run.STATE.status, chat_run.STATE.stages, chat_run.STATE.error, chat_run.STATE.failed_stage = "idle", {}, "", None
    if run.build.prompts and run.build.prompts[0] == chat_run.STATE.prompt:
        del run.build.prompts[:1]  # the next prompt is not a change to a scene nobody built
    if run.build.code_runs and run.build.code_runs[-1]["steps"] is chat_run.STATE.code_steps:
        run.build.code_runs.pop()
    if chat_run.restore_prompt is not None:
        try:
            chat_run.restore_prompt(chat_run.STATE.prompt)
        except Exception:  # the prompt is a convenience; it is still in the history
            traceback.print_exc()
    main_thread.tag_redraw()



def outcome_lines(run):
    """One plain line per planned item that did not end up as asked: an approved 3D item with no model (built in
    code instead, or not at all), and any item not built."""
    lines = [texture_jobs.TEXTURE_FAILED % (job.name, job.error or "it failed") for job in chat_run._jobs(run)
             if job.kind == "texture" and job.state == generation.FAILED]
    if run.plan is None:
        return lines
    said = set()
    jobs = {job.name: job for job in chat_run._jobs(run)}
    missing = {item.name for item in _missing(run)}
    for item in run.plan.three_d:
        job = jobs.get(item.name)
        if job is not None and job.state == generation.DONE:
            if item.targets:
                lines.append(chat_run.UPGRADED % plan3d.root_name(item.name))
            continue
        name = plan3d.root_name(item.name)
        if item.name in missing:
            reason = job.error if job is not None and job.error else "its 3D model was not made"
            lines.append("%s was not built (%s)." % (name, reason))
        else:
            lines.append(chat_run.FAILED_REPLY % (item.name, job.error if job is not None and job.error else
                                         "it was never ordered"))
        said.add(item.name)
    names = [item.name for item in _missing(run) if item.name not in said]
    if names:
        lines.append(not_built_line(names))
    return lines



MISSING_PROMPT = "Build what is still missing from the scene: %s."



def widen(context):
    """The bar's Also let it change ...: the last request again, as an edit of its targets and what it was kept
    from changing."""
    if chat_run.STATE.running or not chat_run.STATE.blocked or not chat_run.STATE.attempt:
        return False
    chat_run._widen[:] = list(dict.fromkeys(list(chat_run.STATE.last_targets) + list(chat_run.STATE.blocked)))
    chat_run.start(context, chat_run.STATE.attempt)
    return True



def _hollow(run):
    """Main thread: True when every target is an object with no geometry in it or under it."""
    for name in run.targets:
        obj = run.build.scene.objects.get(name)
        if obj is None:
            return False
        if any(o.type in scene_build.GEOMETRY for o in [obj] + list(obj.children_recursive)):
            return False
    return True



def build_missing(context):
    """The bar's Build the missing things: a follow-up that asks for exactly what the last run left out."""
    if chat_run.STATE.running or not chat_run.STATE.missing:
        return False
    names = ", ".join("the " + " ".join(n.split()) for n in chat_run.STATE.missing)
    chat_run.start(context, MISSING_PROMPT % names)
    return True



def not_built_line(names):
    """One plain line for the planned things a run did not build: "Not built: the church, the bandit camp."."""
    return NOT_BUILT % ", ".join("the " + " ".join(name.split()) for name in names)



def _missing(run):
    """Main thread: the plan's items not in the scene; a 3D item whose model arrived is in it."""
    if run.plan is None:
        return []
    try:
        names = [o.name for o in run.build._objects()]
    except (RuntimeError, ReferenceError):  # the scene is gone
        return []
    done = {job.name for job in chat_run._jobs(run) if job.state == generation.DONE}
    names += [n for n in run.targets if n in run.build.scene.objects]  # the person's objects they pointed at
    found = plan3d.missing(run.plan, names, done, placed=lambda item, holder: _on_holder(run.build, item, holder))
    # An item naming what stood in the scene before this prompt, or what the request pointed at, is not new: when it
    # is gone, the request removed it ("remove the lighthouse and put a stall there" plans the stall, never a
    # lighthouse to build).
    before = set(getattr(run.build, "existing", None) or ()) | set(run.targets or ())
    return [item for item in found if not any(plan3d.mentions(name, item.name) for name in before)]


REST_GAP_M = 0.05  # metres between a thing's base and the holder's surface under it that still count as resting
SHOWS_M = 0.02  # metres a thing in a holder (flowers in a vase) must reach above the holder's top to be seen


def _on_holder(build, item, holder):
    """Main thread: True when a visible part of an object named after ``item`` rests on an object named after
    ``holder`` (its base within ``REST_GAP_M`` of the holder's surface right under it) or stands in it and shows above
    its top (flowers in a vase). A thing buried inside the holder's volume does not count. True as well when nothing
    is named after the holder."""
    from mathutils import Vector

    objects = build._objects()
    holders = [o for o in objects if plan3d.mentions(o.name, holder)]
    holder_parts = [o for obj in holders for o in [obj] + list(obj.children_recursive)
                    if o.type in scene_build.GEOMETRY]
    if not holder_parts:
        return True  # the holder itself is missing or unnamed: the item is not listed again for it
    holder_ids = {o.session_uid for o in holder_parts}
    holder_boxes = [scene_build._box(o) for o in holder_parts]
    scene = build.scene
    depsgraph = scene.view_layers[0].depsgraph
    for obj in objects:
        if not plan3d.mentions(obj.name, item):
            continue
        for part in [obj] + list(obj.children_recursive):
            if part.type not in scene_build.GEOMETRY or part.hide_render:
                continue
            low, high = scene_build._box(part)
            x, y = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2
            hit, where, _normal, _index, hit_obj, _matrix = scene.ray_cast(
                depsgraph, Vector((x, y, low[2] + 0.001)), Vector((0.0, 0.0, -1.0)), distance=REST_GAP_M + 0.002)
            if hit and getattr(hit_obj, "original", hit_obj).session_uid in holder_ids:
                return True
            for b_low, b_high in holder_boxes:
                inside = all(b_low[i] <= (x, y)[i] <= b_high[i] for i in range(2)) and b_low[2] <= low[2] <= b_high[2]
                if inside and high[2] >= b_high[2] + SHOWS_M:
                    return True
    return False
