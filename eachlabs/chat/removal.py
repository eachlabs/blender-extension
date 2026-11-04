"""After a removal: what rested on the removed thing, and the follow-up step that clears or lowers it."""

from dataclasses import replace

from .. import chat_loop, scene_build
from .live import chat_run
from . import selection


STRANDED_PROMPT = ("%s was removed. These things of yours rested on it and now stand on nothing: %s. Remove each "
                   "that was a part of what was removed (stones on a wall, a roof's tiles); move the others down onto "
                   "what is below them now. Tell the person in one plain sentence what you did.")
RESTING_ROOTS_MAX = 400  # roots of the chat's checked for what they rest on, before an edit



def _resting_on(run, names):
    """Main thread, before an edit: ``{root name: target root name}`` for the chat's other things whose base rests
    on one of the targets (measured with a ray down from under their middle)."""
    build = run.build
    scene = build.scene
    targets = {}
    for name in names:
        obj = scene.objects.get(name)
        if obj is not None:
            for part in [obj] + list(obj.children_recursive):
                targets[part.session_uid] = obj.name
    if not targets:
        return {}
    boxes = [scene_build._box(scene.objects[n]) for n in names if n in scene.objects]
    low = [min(b[0][i] for b in boxes) - 1.0 for i in range(2)]
    high = [max(b[1][i] for b in boxes) + 1.0 for i in range(2)]
    depsgraph = build._depsgraph(scene)
    out = {}
    roots = [o for o in build._objects() if o.parent is None and o.session_uid not in targets
             and o.type not in ("LIGHT", "CAMERA")][-RESTING_ROOTS_MAX:]
    for root in roots:
        parts = [root] + list(root.children_recursive)
        geo = [scene_build._box(o) for o in parts if o.type in scene_build.GEOMETRY]
        if not geo:
            continue
        lo = [min(b[0][i] for b in geo) for i in range(3)]
        hi = [max(b[1][i] for b in geo) for i in range(3)]
        x, y = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        if not (low[0] <= x <= high[0] and low[1] <= y <= high[1]):
            continue
        own = {o.session_uid for o in parts}
        origin = scene_build.Vector((x, y, lo[2] + min(0.3, (hi[2] - lo[2]) / 2)))
        hit = build._first_other(scene, depsgraph, origin, scene_build.Vector((0, 0, -1)), own, 1.0)
        if hit is not None and hit[0].session_uid in targets:
            out[root.name] = targets[hit[0].session_uid]
    return out



def _after_removal(run, names, resting, llm, quick_llm, executor, post, review, cap, limits, result):
    """Worker thread, after an edit: what rested on a removed target gets one more edit, and the chat's other
    objects that still match a removal are offered on the done card."""
    def removed_and_stranded():
        scene = run.build.scene
        gone = [n for n in names if scene.objects.get(n) is None]
        left = [d for d, under in resting.items() if under in gone and scene.objects.get(d) is not None]
        roots = [o.name for o in run.build._objects() if o.parent is None and o.type not in ("LIGHT", "CAMERA")]
        return gone, left, roots

    gone, stranded, roots = chat_loop.Executor(chat_run._call_soon, 30.0, execute=lambda n, a: removed_and_stranded())(
        "removed", {}) or ([], [], [])
    if not gone:
        return result
    message = result.message
    if stranded and not run.cancel.is_set():
        chat_loop.Executor(chat_run._call_soon, 30.0, execute=lambda n, a: (chat_run._end_edit(run.build),
                                                                  chat_run._begin_edit(run, stranded)))("again", {})
        names[:] = list(dict.fromkeys(names + stranded))
        second = chat_loop.run(STRANDED_PROMPT % (", ".join(gone), ", ".join(stranded)), llm, executor, post,
                               run.cancel, replace(limits), (chat_loop.EDIT,), run.earlier, run.secrets,
                               review if run.code_check else None, run.blender, quick_llm, cap, None)
        message = "\n".join(t for t in (message, second.message) if t)
    # Objects that still match what the person asked to remove: offered on the done card, never removed unasked.
    asked = selection._read_prompt(run, run.request or "", quick_llm) if roots else None
    still = [n for n in (asked or {}).get("names") or [] if n not in gone and n not in stranded]
    if still:
        run.put_back.update(still)
        run.removal = True
    return chat_loop.RunResult(result.status, message, result.rounds, result.failed_stage)
