"""The worker thread of one chat run: reading the prompt, the plan, every stage, detail, 3D objects and the end."""

from dataclasses import replace

from .. import (chat_loop, code_review, detail, edit_guard, generation, intent, look_around, plan3d, thread_safety,
               visual_check)
from ..instructions import targets
from ..placement import settle
from ..scene import replaced
from ..polyhaven import apply as haven_apply, tools as haven_tools
from .live import chat_run
from . import (budget, candidates, concepts, debug_log, detail_budget, detail_steps, edits, events, object_jobs,
               plan_flow, review as scene_review, review_run, selection, stage_models, texture_jobs, undo_watch)


def _main_things(run):
    """The plan's names the scene review's views are fitted to: its main objects, else every planned thing."""
    main = [name for name, level in getattr(run, "planned", None) or () if level == "high"]
    return main or list(getattr(run.build, "subjects", None) or ())


def _work(run, prompt, stages):
    """Worker thread: balance, the stage loop, balance again. Everything it learns goes through the queue."""
    def post(event):
        chat_run._call_soon(lambda: events._apply(run, event))

    cap = chat_loop.reply_cap(run.model)

    def llm(messages, tools):
        return run.client.chat_completion(run.model, messages, tools, timeout=run.reply_seconds, max_tokens=cap.tokens)

    quick_llm = chat_loop.WithoutReasoning(
        lambda messages, tools, reasoning: run.client.chat_completion(
            run.model, messages, tools, timeout=run.reply_seconds, max_tokens=cap.tokens, reasoning=reasoning),
        accepted=chat_loop.reasoning_optional(run.model))

    def execute(name, args):
        if run is not chat_run._run or run.cancel.is_set():
            raise RuntimeError("The chat was stopped.")
        if name == "placement_problems":  # for the stage loop: what a fix stage gets and the reply names
            if run.build.focus:
                return {}  # a targeted edit is checked on its targets only, by its own stage
            return chat_loop.placement_problems(run.build.read_scene())
        if name == "prune":  # for the stage loop: a part's old version that a newer one replaced is removed
            if run.build.focus:
                return []
            return replaced.prune(run.build)
        if name == "settle":  # for the stage loop: small loose props come down onto what is under them
            if not getattr(run, "settle_on", False) or run.build.focus:
                return []
            return settle.settle(run.build)
        if name == "missing_items":  # for the stage loop, not a tool of the model
            return [plan3d.missing_text(item) for item in plan_flow._missing(run)]
        if name == "generate_texture":
            return texture_jobs.queue_texture(run, args)
        if name in ("apply_free_sky", "apply_free_texture"):  # downloaded on the worker by haven_tools
            return _apply_free(run, name, args)
        if name == "render_frames":  # the visual check, for the stage loop
            try:
                return visual_check.render(run.build, bool(args.get("moves")))
            finally:
                undo_watch._quiet()  # its temporary camera and frame changes are not the person's edit
        if name == "review_views":  # the scene review's pictures, for the stage loop
            try:
                return review_run.views(run.build, _main_things(run))
            finally:
                undo_watch._quiet()
        if name == "review_mark":
            return review_run.mark(run)
        if name == "review_undo":
            return review_run.undo_fix(run)
        if name == "detail_roots":  # the detail stage, not tools of the model
            # A change details only what it made and what it points at, never the rest of the scene again.
            return detail_steps._detail_roots(run.build, None if run.fresh else run.build.since, run.targets)
        if name == "detail_read":
            return detail_steps._detail_read(run.build, args["object"])
        if name == "detail_step":
            return detail_steps._detail_step(run.build, args["object"], args["code"], run.step_seconds)
        if name == "detail_look":
            try:
                found = visual_check.render_object(run.build, args["object"])
            finally:
                undo_watch._quiet()
            return dict(found, **detail_steps._object_problems(run.build, args["object"]))
        if name == "detail_measure":  # after the close-up's round: what is still wrong, measured, no render
            return detail_steps._object_problems(run.build, args["object"])
        if name == "detail_copies":
            return detail_steps._detail_copies(run.build, args["objects"])
        if name == "candidate_stash":  # the detail stage's versions for the judge, not tools of the model
            return {"key": candidates.stash(run.build, args["object"])}
        if name == "candidate_restore":
            return candidates.restore(run.build, args["object"], args["key"])
        if name == "candidate_drop":
            candidates.drop(args["keys"])
            return {}
        if name == "candidate_shot":
            try:
                return candidates.shot(run.build, args["object"])
            finally:
                undo_watch._quiet()
        if name == "look_at":  # the model's own look from four sides; temporary cameras only
            try:
                return look_around.render_view(run.build, args.get("object"), args.get("hide") or (),
                                               args.get("mode", "solid"))
            finally:
                undo_watch._quiet()
        mark = run.build.mark()
        result = chat_run._execute_marked(run.build, name, args, run.step_seconds)
        if name == "run_python" and isinstance(result, dict) and isinstance(result.get("put_back"), list):
            run.put_back.update(n for n in result["put_back"] if isinstance(n, str) and not n.startswith("+"))
        if name == "run_python" and run.build.guard is not None and len(run.edit_roots) == 1:
            detail_steps._into(run.build, run.edit_roots[0], mark)  # an edit's new pieces belong to its one target
        elif name == "run_python" and run.build.guard is None and not run.fresh:
            detail_steps._apart(run.build, mark)  # a follow-up's new things stay objects of their own
        return result

    def review(code, chat_objects, collection):
        return code_review.review(code, chat_loop.retried(quick_llm, run.cancel), chat_objects, collection,
                                  run.secrets)

    try:
        before = budget._balance(run.client)  # the balance difference also counts the Code check calls
        objects = None
        full = chat_loop.is_full(stages)  # a retry of later stages is never a question
        target = getattr(run, "target", targets.SCENE)
        adds = target != targets.SCENE  # an asset or a character: one new thing, or a change to a chosen one
        if run.whole and adds:  # not a retry; ``full`` is False once the tab left out the light and camera
            asked = _tab_asked(run, prompt, quick_llm, target)
        else:
            asked = selection._read_prompt(run, prompt, quick_llm) if full and (run.names or run.selected) else None
        if asked is not None and asked["intent"] in (intent.FIND, intent.LIST):
            chat_run._call_soon(lambda: selection._found(run, asked))
            after = budget._balance(run.client) if before is not None else None
            cost = round(before - after, 4) if before is not None and after is not None else None
            chat_run._call_soon(lambda: events._finish(run, chat_loop.RunResult("found", "", 1, None), cost))
            return
        if asked is not None and asked["selection"]:
            if not run.selected:  # "this", and nothing is selected: nothing runs, the prompt comes back
                chat_run._call_soon(lambda: selection._needs_selection(run))
                return
            run.targets = list(run.selected_names)
            selected = set(run.selected)
            chat_run._call_soon(lambda: setattr(run.build, "allowed", selected))  # before the first step
        elif asked is not None and asked["names"]:
            run.targets = list(asked["names"])
            if asked["edit"] and run.selected_names:  # what the person selected is always part of an edit
                run.targets = list(dict.fromkeys(run.targets + list(run.selected_names)))
                selected = set(run.selected)
                chat_run._call_soon(lambda: setattr(run.build, "allowed", selected))
        if chat_run._widen and asked is not None:  # "Also let it change ...": the last edit's targets and what it was kept from
            run.targets, asked = list(chat_run._widen), dict(asked, edit=True)
            chat_run._widen[:] = []
        hollow = bool(run.targets) and asked is not None and asked["edit"] and chat_loop.Executor(
            chat_run._call_soon, 30.0, execute=lambda name, args: plan_flow._hollow(run))("hollow", {})
        if hollow:  # an empty with nothing under it: its parts are other objects, so this is no single-target edit
            asked = dict(asked, edit=False)
        # A follow-up that does not ask for other light, sky or time of day keeps the world it had.
        keep_world = not run.fresh and (adds or asked is not None and asked.get("look") is False)
        world_guard = edit_guard.WorldGuard(run.build) if keep_world else None
        chat_run._call_soon(lambda: setattr(run.build, "world_guard", world_guard))
        run.request = prompt  # the person's words, without the target note
        if not run.targets:  # a change on Assets or Characters is the person's words, as on Scene
            prompt = targets.request(target, prompt, run.fresh)
        if run.concept_allowed and asked is not None and asked.get("concept"):
            run.concept = True  # a follow-up that asks for a concept picture; the plan still shows its price
        if run.targets:
            prompt = "%s\n\n%s" % (prompt, intent.target_note(run.targets, asked["selection"], asked["edit"]))
            if hollow:
                prompt += "\n" + plan_flow.HOLLOW_NOTE % ", ".join(run.targets)
        if run.targets and asked["edit"]:
            edits._edit(run, prompt, asked["label"], llm, quick_llm, execute, review, cap, post, before)
            return
        left = texture_jobs._textures_left(run)
        shown = False  # a plan with the looks line was shown and the person pressed Build
        if run.plan_step:
            plan = plan_flow._plan(run, prompt, quick_llm, post)
            references = []
            if plan is not None:
                if not run.objects_3d:  # 3D objects are off: everything is built in code
                    for item in plan.items:
                        item.mode, item.solid = "code", False
                if target == targets.CHARACTER and plan.code and not any(i.detail == "high" for i in plan.code):
                    plan.code[0].detail = "high"  # the character is the main object
                run.planned = [(i.name, i.detail) for i in plan.code if i.detail in detail.LEVELS]
                references = plan.references() if run.references_on and plan.adds_objects else []
                plan.looks = plan3d.looks_text(run.concept, left, generation.IMAGE_PRICE, [i.name for i in references],
                                               generation.REFERENCE_PRICE,
                                               concept_price=getattr(run, "concept_price", None))
                pictures = plan3d.looks_cost(run.concept, left, generation.IMAGE_PRICE, references,
                                             generation.REFERENCE_PRICE, getattr(run, "concept_price", None))
            if plan is not None and run.objects_3d and run.targets and plan3d.asks_real(prompt):  # a solid piece
                size = chat_loop.Executor(chat_run._call_soon, 30.0, execute=lambda name, args: object_jobs._target_size(run))("size", {})
                upgraded = plan3d.upgrade(plan, asked["label"] if asked else "", run.targets, size) if size else None
                if upgraded is not None:
                    object_jobs._picture(run, upgraded)
            detail_rounds = 0
            if plan is not None and plan.items and plan.adds_objects:
                detail_rounds = detail_budget.estimate(run.planned, len(plan.items) - len(run.planned), run.detail,
                                                       run.visual is not None)
                needed = budget.rounds_needed(run.limits, len(plan.items)) + detail_rounds
                main = detail_budget.estimate([p for p in run.planned if p[1] == "high"], 0, run.detail,
                                              run.visual is not None)
                if needed > run.rounds_cap:  # shown even when nothing is paid: the person decides
                    plan.rounds_needed, plan.rounds_limit = needed, run.rounds_cap
                    cost = budget.estimate_cost(needed, run.limits, run.model, run.light_model, run.detail_model, main)
                    plan.note = budget.BUDGET_TEXT % (needed, detail_rounds, cost, run.rounds_cap)
                if plan.asks():  # only a plan that is shown anyway carries the run's price; it is never a reason to ask
                    # What the run spends unless the person raises the limit, the review's fix stage included.
                    within = min(needed + scene_review.rounds(run.scene_review), run.rounds_cap)
                    plan.looks = budget.with_run(plan.looks, within, budget.estimate_cost(
                        within, run.limits, run.model, run.light_model, run.detail_model, main), pictures)
                if plan.asks():
                    # Shown when there is something to decide or pay for: a solid piece that may go to 3D, a 3D item,
                    # or pictures. Nothing is paid for before Build.
                    if not plan_flow._ask_plan(run, plan, post):
                        return
                    shown = True
                # Shown or not, the plan is the run's list of things: what is still missing gets built at the end.
                run.plan = plan
                run.build.subjects = [i.name for i in plan.items]  # what the shot is about, for camera_view
                run.build.owned = [(i.name, i.part_of) for i in plan.items if i.part_of]  # parent things
                run.build.asked_colours = {i.name: i.colour for i in plan.items if i.colour}  # read_scene checks
                if plan.areas:
                    run.build.area_rules = plan.areas
                run.limits = budget._scaled_limits(run.limits, len(plan.items), run.rounds_cap, detail_rounds)
                # The add-on orders every approved 3D item now, before the first step: the model only builds the
                # code versions. Queued through the same main-thread queue as the steps, so it comes first.
                chat_run._call_soon(lambda: object_jobs.queue_plan(run))
                objects = chat_loop.Generation(brief=plan.brief(), notes=lambda: object_jobs._failed_notes(run), complete=True)
                concepts._draw_references(run, references)
        if not shown:  # no plan was shown: the concept picture and textures are paid for only after Build
            looks = plan3d.looks_plan(run.concept, left, generation.IMAGE_PRICE,
                                      concept_price=getattr(run, "concept_price", None))
            if looks is not None:  # the run's own rounds, so the card is never only the pictures' price
                main = (run.detail.rounds + 1) if run.detail is not None and chat_loop.DETAIL in stages else 0
                rounds = min(run.rounds_cap, run.limits.total_rounds + main + scene_review.rounds(run.scene_review))
                looks.looks = budget.with_run(looks.looks, rounds, budget.estimate_cost(
                    rounds, run.limits, run.model, run.light_model, run.detail_model, main),
                    plan3d.looks_cost(run.concept, left, generation.IMAGE_PRICE,
                                      concept_price=getattr(run, "concept_price", None)))
            if looks is not None and not plan_flow._ask_plan(run, looks, post):
                return
        if run.fresh:  # through the main-thread queue, so before the first step
            chat_run._call_soon(lambda: chat_run._drop_cube(run))
        concept = concepts._concept(run, prompt, post) if run.concept and not run.cancel.is_set() else None
        try:
            executor = chat_loop.Executor(chat_run._call_soon, run.step_seconds + chat_run.EXECUTOR_MARGIN, execute=execute)
            if run.free_assets_on:
                executor = haven_tools.on_worker(executor, run.client, run.cache_folder, run.cancel)
            more = None
            if run.detail_more:
                def more(messages, tools):
                    return run.client.chat_completion(run.model, messages, tools, timeout=run.reply_seconds,
                                                      max_tokens=cap.tokens, effort="high")

            if run.limits.detail_rounds is None:  # no plan scaled the limits: the person's limit still holds
                pool = max(0, run.rounds_cap - run.limits.total_rounds)
                run.limits = replace(run.limits, detail_rounds=pool, extra_rounds=min(run.limits.extra_rounds, pool))

            def call(model, messages, tools, tokens, reasoning):
                return run.client.chat_completion(model, messages, tools, timeout=run.reply_seconds, max_tokens=tokens,
                                                  reasoning=reasoning)
            main = stage_models.detail_route(run.model, run.detail_model, call)

            def improve(scene, rounds, total):
                return detail_steps._improve(run, prompt, scene, rounds, total, more or llm, quick_llm, executor, post,
                                review if run.code_check else None, cap, run.limits.detail_rounds, main)
            routes = stage_models.routes(run.model, run.light_model, call)
            reviewer = None  # a find, an edit and a retry of later stages never get here or are not full
            if run.scene_review and full and (run.visual is None or run.visual.accepted):
                reviewer = scene_review.Reviewer(
                    chat_loop.retried(llm, run.cancel), chat_loop.retried(quick_llm, run.cancel), executor, run.cancel,
                    post, run.request, run.earlier, lambda entry: debug_log.debug_log(entry, run.secrets))
            asked = prompt + ("\n\n" + run.library_offer if getattr(run, "library_offer", "") else "")
            result = chat_loop.run(asked, llm, executor, post, run.cancel,
                                   run.limits, stages, run.earlier, run.secrets,
                                   review if run.code_check else None, run.blender, quick_llm, cap, objects,
                                   left, concept, run.visual, improve if run.detail is not None else None,
                                   assets=run.free_assets_on, routes=routes, scene_review=reviewer)
        except Exception as exc:  # A worker must always report back.
            result = chat_loop.RunResult("stopped", str(exc) or type(exc).__name__, 0, None)
        if run.visual is not None and not run.visual.accepted:
            chat_run._call_soon(lambda: chat_run.NO_PICTURES.add(run.model))
        if run.jobs and result.status in ("done", "stopped") and not run.cancel.is_set():
            # The run ends only when every 3D model has replaced its code version or passed its limit; Stop works.
            post({"type": "objects_wait", "state": "on"})
            object_jobs._wait_objects(run, run.cancel)
            post({"type": "objects_wait", "state": "off"})
        after = budget._balance(run.client) if before is not None else None
        cost = round(before - after, 4) if before is not None and after is not None else None
        chat_run._call_soon(lambda: events._finish(run, result, cost))
    finally:
        chat_run._call_soon(lambda: edits._end_edit(run.build))
        thread_safety.chat_thread_ended()



def _tab_asked(run, prompt, quick_llm, target):
    """Worker thread, on Assets and Characters: a change to the selected things, or to things of the tab's kind that
    the prompt names (the quick call decides); ``None`` adds one new thing, as the tab says."""
    if run.selected_names:
        return intent.selected_edit(run.selected_names)
    if not run.names:
        return None
    return intent.named_edit(selection._read_prompt(run, prompt, quick_llm, targets.KIND_NOTE[target]))


def _apply_free(run, name, args):
    """Main thread: a downloaded Poly Haven sky or texture onto the chat's world or material."""
    try:
        if name == "apply_free_sky":
            target = haven_apply.set_sky(run.build, args["path"], args["strength"], args["rotation_deg"])
        else:
            target = haven_apply.set_maps(run.build, args["material"], args["maps"], args["tile_m"])
    except (LookupError, RuntimeError, OSError) as exc:  # a missing material, an unreadable picture
        return {"ok": False, "error": str(exc) or type(exc).__name__}
    if args["name"] not in run.free_assets:
        run.free_assets.append(args["name"])
    undo_watch._quiet()
    used = {"ok": True, "used": args["name"], "on": target}
    if name == "apply_free_texture":
        used["tile_m"] = round(args["tile_m"], 2)
    return used
