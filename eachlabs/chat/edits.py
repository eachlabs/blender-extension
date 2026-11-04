"""A targeted edit: one stage that changes only the objects a request points at, with the guard that puts the rest back."""

import traceback
from dataclasses import replace

from .. import chat_loop, edit_guard, plan3d, scene_build
from .live import chat_run
from . import budget, object_jobs, plan_flow, removal


def _edit(run, prompt, label, llm, quick_llm, execute, review, cap, post, before):
    """Worker thread: a request that only changes the objects it points at. One short stage sees only them, and
    the chat's other objects are put back after each step; an upgrade to 3D runs no step at all: plan, queue, wait
    and swap."""
    names = list(run.targets)
    post({"type": "stages", "stages": [chat_loop.EDIT]})
    chat_run._call_soon(lambda: _begin_edit(run, names))  # before the first step
    plan = None
    if run.plan_step and run.objects_3d and plan3d.asks_real(prompt):
        size = chat_loop.Executor(chat_run._call_soon, 30.0, execute=lambda name, args: object_jobs._target_size(run))("size", {})
        found = (plan_flow._plan(run, prompt, quick_llm, post) or plan3d.Plan()) if size else None
        # Only a solid piece is upgraded to a 3D model; anything with parts gets its detail in code, below.
        item = plan3d.upgrade(found, label, names, size) if found is not None else None
        if item is not None:
            plan = found
            item = object_jobs._picture(run, item)
            plan.items = [item]  # an edit adds nothing: the plan is the upgrade alone
            post({"type": "plan", "plan": plan})
            while not run.plan_event.wait(0.25) and not run.cancel.is_set():
                pass
            if run.cancel.is_set() or run.plan_answer != "build":
                chat_run._call_soon(lambda: plan_flow._plan_cancelled(run))
                return
            run.plan = plan
            # Waited for, not only queued: the wait below needs the jobs, and no step comes first to delay it.
            chat_loop.Executor(chat_run._call_soon, 30.0, execute=lambda name, args: object_jobs.queue_plan(run) and None)("queue", {})
    if plan is not None:  # the code version stays exactly as it is until its model replaces it
        post({"type": "stage", "stage": chat_loop.EDIT, "state": "active"})
        result = chat_loop.RunResult("done", "", 0, None)
    else:
        try:
            executor = chat_loop.Executor(chat_run._call_soon, run.step_seconds + chat_run.EXECUTOR_MARGIN, execute=execute)
            # With the visual check, the edit ends with a look through the scene camera and a round to fix it.
            look = chat_loop.EDIT_LOOK_ROUNDS if run.visual is not None else 0
            limits = replace(run.limits, total_rounds=min(run.limits.total_rounds, chat_loop.EDIT_ROUNDS + look))
            resting = chat_loop.Executor(chat_run._call_soon, 30.0, execute=lambda name, args: removal._resting_on(run, names))(
                "resting", {}) or {}
            result = chat_loop.run(prompt, llm, executor, post, run.cancel, limits, (chat_loop.EDIT,),
                                   run.earlier, run.secrets, review if run.code_check else None,
                                   run.blender, quick_llm, cap, None, visual=run.visual)
            if result.status == "done" and not run.cancel.is_set():
                result = removal._after_removal(run, names, resting, llm, quick_llm, executor, post, review, cap, limits,
                                        result)
        except Exception as exc:  # A worker must always report back.
            result = chat_loop.RunResult("stopped", str(exc) or type(exc).__name__, 0, None)
    if run.jobs and result.status in ("done", "stopped") and not run.cancel.is_set():
        post({"type": "objects_wait", "state": "on"})
        object_jobs._wait_objects(run, run.cancel)
        post({"type": "objects_wait", "state": "off"})
    if plan is not None:
        post({"type": "stage", "stage": chat_loop.EDIT, "state": "done"})
    after = budget._balance(run.client) if before is not None else None
    cost = round(before - after, 4) if before is not None and after is not None else None
    chat_run._call_soon(lambda: chat_run._finish(run, result, cost))



def _begin_edit(run, names):
    """Main thread: read_scene sees only the targets, and the guard watches the chat's other objects."""
    if run is not chat_run._run:
        return
    build = run.build
    try:
        build.focus = edit_guard.target_uids(build, names)
    except (RuntimeError, ReferenceError):
        return
    build.focus_names = list(names)
    build.guard = edit_guard.EditGuard(build, build.focus)
    roots = []
    for name in names:
        obj = build.scene.objects.get(name)
        while obj is not None and not scene_build.is_root(obj) and build.owns(obj.parent):
            obj = obj.parent
        if obj is not None and obj.name not in roots:
            roots.append(obj.name)
    run.edit_roots = roots
    build.context_root = roots[0] if len(roots) == 1 else None  # one target: new loose pieces join its thing



def _end_edit(build):
    """Main thread: the edit is over; the guard's copies go."""
    guard, build.guard, build.focus, build.focus_names = build.guard, None, set(), []
    build.context_root = None
    if guard is not None:
        try:
            guard.close()
        except Exception:  # the copies are unused data; they go when the file is saved
            traceback.print_exc()
