"""The detail stage's work on the scene: picking roots, reading and running one object's steps, keeping parts inside it, rebuilding copies."""

import bpy
import re
import traceback
from mathutils import Matrix, Vector

from .. import chat_loop, detail, edit_guard, scene_build, solids
from ..things import registry
from .live import chat_run


def _improve(run, prompt, scene, rounds, total, llm, quick_llm, executor, post, review, cap, limit=None, main=None):
    """Worker thread: the detail stage. One quick call picks the objects, then ``detail.run`` improves them."""
    choices = executor("detail_roots", {})
    names = [c["name"] for c in choices]
    if not names:
        return detail.Outcome()
    light = run.detail.light_objects if run.detail.light_rounds > 0 else 0
    messages = detail.pick_messages(run.request or prompt, scene, run.planned, run.detail.objects, choices, light)
    try:
        reply = chat_loop.retried(quick_llm, run.cancel)(messages, [])
        text = reply["choices"][0]["message"].get("content") or ""
    except Exception as exc:  # no pick: the layout's objects stay as they are
        chat_loop.debug_log({"stage": "detail", "pick_error": str(exc)}, run.secrets)
        return detail.Outcome(lines=["Detail: skipped, %s." % chat_loop._llm_error(exc).rstrip(".")])
    chat_loop.debug_log({"stage": "detail", "pick": messages, "reply": text}, run.secrets)
    targets = detail.parse_pick(text, names, run.detail.objects, light)
    for target in targets:
        target.reference = chat_run._reference_for(run, target.name)
    outcome = detail.run(targets, run.request or prompt, llm, quick_llm, executor, post, run.cancel, run.detail,
                         rounds, total, review, run.secrets, cap, run.blender, run.visual, limit, main)
    judged = [t["judge"] for t in outcome.timings if t.get("judge")]
    if judged:  # which version of each compared object was kept, and why
        chat_loop.debug_log({"stage": "detail", "judged": judged}, run.secrets)
    if targets and not run.cancel.is_set():
        try:
            copied = executor("detail_copies", {"objects": [t.name for t in targets]})
        except Exception as exc:  # the copies keep the layout's shape
            copied = {"error": str(exc) or type(exc).__name__}
        chat_loop.debug_log({"stage": "detail", "copies": copied}, run.secrets)
    return outcome



def _detail_roots(build, since=None, targets=()):
    """Main thread: every root object of the chat's with geometry in it: its name, its parts and its size. With
    ``since`` (a ``mark()``), only the roots made after it and the roots of ``targets``."""
    out = []
    scope = made = None
    if since is not None:
        scope = set(build.created_since(since))
        made = set(scope)
        for name in targets:
            obj = build.scene.objects.get(name)
            while obj is not None and not scene_build.is_root(obj) and build.owns(obj.parent):
                obj = obj.parent
            if obj is not None:
                scope.add(obj.name)
    for obj in build._objects():
        if not scene_build.is_root(obj) or obj.get("zone") or obj.type not in ("EMPTY", "MESH", "CURVE"):
            continue  # an area's zone is not one object: the things in it are
        if scope is not None and obj.name not in scope:
            continue
        tree = [obj] + list(obj.children_recursive)
        corners = [o.matrix_world @ Vector(c) for o in tree if o.type in scene_build.GEOMETRY for c in o.bound_box]
        if not corners:
            continue
        size = max(max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3))
        entry = {"name": obj.name, "parts": len(tree) - 1, "size_m": round(size, 1)}
        if made is not None:
            entry["made_now"] = obj.name in made
        out.append(entry)
    return out[:detail.CHOICES_MAX]



def _object_problems(build, name):
    """Main thread: what is measurably wrong with one object of the chat's: gaps between its parts, holes in its
    meshes and parts hidden inside a bigger part of it."""
    try:
        gaps = build.part_gaps(name)
        root = build.scene.objects.get(name)
        parts = [root] + list(root.children_recursive) if root is not None else []
        holes = build.mesh_health(parts)[0] if parts else []
        hidden = solids.hidden_parts(parts, build._depsgraph(build.scene)) if parts else []
    except (RuntimeError, ReferenceError):
        gaps, holes, hidden = [], [], []
    return dict(**({"gaps": gaps} if gaps else {}), **({"holes": holes} if holes else {}),
                **({"hidden": hidden} if hidden else {}))



def _detail_read(build, name):
    """Main thread: ``read_scene`` of one object and its parts."""
    root = build.scene.objects.get(name)
    if root is None or not build.owns(root):
        raise RuntimeError("%s is not one of the chat's objects" % name)
    saved = build.focus, build.focus_names
    try:
        build.focus, build.focus_names = edit_guard.target_uids(build, [name], children=False), [name]
        found = build.read_scene()
    finally:
        build.focus, build.focus_names = saved
    mine = build._objects()
    own = {o.name for o in registry.subtree_objects(mine, [name], children=False)}
    under = {o.name for o in registry.subtree_objects(mine, [name])} - own
    children = [e["name"] for e in registry.inventory(mine) if e["name"] in under]
    return {"objects": found.get("objects"), **({"loose_parts": found["loose_parts"]} if found.get("loose_parts")
                                                else {}), **({"child_things": children} if children else {})}



def _detail_step(build, name, code, limit_s):
    """Main thread: one step of the detail stage. Only the object ``name`` and its parts may change: the guard puts
    back any other object of the chat's. New objects without a parent become parts of it, where they stand."""
    root = build.scene.objects.get(name)
    if root is None or not build.owns(root):
        return {"ok": False, "error": "%s no longer exists; build on its parts by name, or stop" % name}
    saved = build.focus, build.focus_names, build.guard, build.context_root
    build.focus, build.focus_names = edit_guard.target_uids(build, [name], children=False), [name]
    build.guard = edit_guard.EditGuard(build, build.focus)
    build.context_root = name
    mark = build.mark()
    try:
        result = chat_run._execute_marked(build, "run_python", {"code": code}, limit_s)
        _into(build, name, mark)
        return result
    finally:
        guard = build.guard
        build.focus, build.focus_names, build.guard, build.context_root = saved
        try:
            guard.close()
        except Exception:  # the copies are unused data; they go when the file is saved
            traceback.print_exc()



def _into(build, name, mark):
    """Main thread: objects made after ``mark`` without a parent become parts of the root ``name``, where they
    stand (lights and cameras stay apart)."""
    root = build.scene.objects.get(name)
    if root is None:
        return
    for new in build.created_since(mark):
        obj = build.scene.objects.get(new)
        if obj is not None and obj is not root and obj.parent is None and obj.type not in ("LIGHT", "CAMERA"):
            world = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_parent_inverse = root.matrix_world.inverted()
            obj.matrix_world = world



def _apart(build, mark):
    """Main thread: a group the step made (an empty with geometry under it) that it parented to an object from
    before this run becomes a root object of its own, where it stands: a cat added on an armchair is not a part of
    the armchair. Single new parts (a new chair leg) stay where the step put them."""
    made = set(build.created_since(build.since))
    for new in build.created_since(mark):
        obj = build.scene.objects.get(new)
        parent = obj.parent if obj is not None else None
        if obj is None or obj.type != "EMPTY" or parent is None or parent.name in made:
            continue
        if not any(o.type in scene_build.GEOMETRY for o in obj.children_recursive):
            continue
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world



COPIES_OBJECTS_MAX = 4000  # objects the detail stage may add by rebuilding copies; past it the copies stay as built
COPY_SIZE_RANGE = (0.4, 2.5)  # a copy this much smaller or bigger than the detailed object is a different thing



def _copy_key(name):
    """``Shore_Pine_007`` -> ``Shore_Pine``: the name without its trailing number, or ``None`` when it has none."""
    stripped = re.sub(r"[\s_.\-]*\d+$", "", name)
    return stripped if stripped and stripped != name else None



def _tree_box(root):
    tree = [root] + list(root.children_recursive)
    boxes = [scene_build._box(o) for o in tree if o.type in scene_build.GEOMETRY and not o.hide_render]
    if not boxes:
        return None
    return (Vector([min(b[0][i] for b in boxes) for i in range(3)]),
            Vector([max(b[1][i] for b in boxes) for i in range(3)]))



def _detail_copies(build, names):
    """Main thread: rebuild the copies of each detailed object from it. A copy is a root object of the chat's whose
    name differs only in its trailing number (``Shore_Pine_007`` of ``Shore_Pine_000``), of a similar size, with fewer
    parts. The detailed object is duplicated, sharing its meshes and materials, scaled to the copy's size and stood
    where the copy stood; the copy goes. Returns ``{"rebuilt": n, "skipped": n}``."""
    detailed = [build.scene.objects.get(n) for n in names]
    detailed = [o for o in detailed if o is not None and build.owns(o) and o.parent is None]
    done = {o.name for o in detailed}
    rebuilt = skipped = added = 0
    for source in detailed:
        key = _copy_key(source.name)
        box = _tree_box(source)
        if key is None or box is None or source.get(scene_build.GENERATED):
            continue
        tree = [source] + list(source.children_recursive)
        size = max((box[1] - box[0])[:])
        for copy in [o for o in build._objects() if o.parent is None and o.name not in done
                     and _copy_key(o.name) == key and not o.get(scene_build.GENERATED)
                     and not o.get(scene_build.PLACEHOLDER)]:
            other = _tree_box(copy)
            if other is None or len(copy.children_recursive) >= len(tree) - 1:
                continue
            scale = max((other[1] - other[0])[:]) / size if size > 1e-6 else 0.0
            if not COPY_SIZE_RANGE[0] <= scale <= COPY_SIZE_RANGE[1]:
                continue
            if added + len(tree) > COPIES_OBJECTS_MAX:
                skipped += 1
                continue
            old_name = copy.name
            spot = Vector(((other[0].x + other[1].x) / 2, (other[0].y + other[1].y) / 2, other[0].z))
            centre = Vector(((box[0].x + box[1].x) / 2, (box[0].y + box[1].y) / 2, box[0].z))
            turn = (copy.matrix_world.to_quaternion() @ source.matrix_world.to_quaternion().inverted()).to_matrix()
            move = (Matrix.Translation(spot) @ turn.to_4x4() @ Matrix.Scale(scale, 4)
                    @ Matrix.Translation(-centre))
            for obj in list(copy.children_recursive) + [copy]:  # first, so the new parts can take the old names
                bpy.data.objects.remove(obj)
            made = {}
            for obj in tree:
                dup = obj.copy()  # shares the mesh and the materials
                made[obj.session_uid] = dup
                build.adopt(dup)
                dup.name = old_name if obj is source else obj.name.replace(source.name, old_name, 1)
            for obj in tree:
                if obj.parent is not None and obj.parent.session_uid in made:
                    made[obj.session_uid].parent = made[obj.parent.session_uid]
                    made[obj.session_uid].matrix_parent_inverse = obj.matrix_parent_inverse.copy()
            made[source.session_uid].matrix_world = move @ source.matrix_world
            done.add(old_name)
            added += len(tree)
            rebuilt += 1
    if rebuilt:
        build.note_change()
    return {"rebuilt": rebuilt, "skipped": skipped}
