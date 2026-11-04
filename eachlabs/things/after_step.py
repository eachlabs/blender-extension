"""What a step's code did to things, applied by the add-on once the step has run: the ``thing()`` calls, the things
``place()``, ``scatter()`` and ``zone()`` named, every object's thing, orphans, and the rest of a thing whose root
the step removed. Main thread only."""

import bpy

from . import ids, outliner, registry

ORPHANS_NOTE = ("These new objects belong to no thing: %s. For each: attach(obj, root) when it is a part of a thing "
                "(a roof of a house), or thing(obj, \"kind\", \"labels\") when it is a thing of its own.")
ORPHANS_MAX = 20
REMOVED_MAX = 30
KEY = {"thing": "thing", "copy": "thing", "place": "thing", "scatter": "scatter", "zone": "zone"}


def before(build):
    """Taken before a step runs; ``None`` for a build that keeps no things."""
    return registry.snapshot(build._objects()) if hasattr(build, "_objects") else None


def _target(by_name, kind, req):
    name = req.get(KEY.get(kind, ""), "") or ""
    return by_name.get(name) or (by_name.get("Zone " + name) if kind == "zone" else None)


def apply(build, scene, requests, snap, new_objects):
    """Returns the entries for the step's result: ``orphans`` and ``removed_with``."""
    if snap is None:
        return {}
    objects = build._objects()
    by_name = {o.name: o for o in objects}
    ordered = [r for r in requests if r[0] == "thing"] + [r for r in requests if r[0] != "thing"]
    for kind, req in ordered:
        obj = _target(by_name, kind, req)
        if obj is None:
            continue
        if kind == "copy":
            original = by_name.get(req.get("of") or "")
            if original is not None and registry.is_root(original):
                registry.declare(obj, original.get(ids.KIND), original.get(ids.LABELS) or "",
                                 original.get(ids.PARENT) or None, objects)
                obj[ids.COPY_OF] = original.get(ids.COPY_OF) or registry.thing_of(original)
            continue
        if kind == "thing":
            parent = req.get("parent")
            registry.declare(obj, req.get("kind") or "", req.get("labels") or "",
                             by_name.get(parent, parent) if parent else None, objects)
        elif not registry.is_root(obj):  # whatever is placed, scattered or laid out as an area is a thing
            area = kind == "zone"
            registry.declare(obj, "area" if area else ids.kind_from_name(obj.name),
                             req.get("zone", "") if area else "", objects=objects)
    new_uids = {o.session_uid for o in new_objects}
    context = scene.objects.get(build.context_root) if getattr(build, "context_root", None) else None
    orphans = registry.refresh(objects, new_uids, context)
    registry.gather(objects)  # a thing's parts move with it, whatever moves it later
    removed = []
    for obj in registry.cascade(objects, snap):
        try:
            name = obj.name
            bpy.data.objects.remove(obj)
            removed.append(name)
        except ReferenceError:  # already gone with its parent
            pass
    out = {}
    if orphans:
        out["orphans"] = [o.name for o in orphans][:ORPHANS_MAX]
    if removed:
        out["removed_with"] = removed[:REMOVED_MAX]
    return out


def end_of_stage(build, top, tag):
    """At the end of a stage: orphans the model left become things of their own, and the collections follow the
    things. Returns how many objects changed collection."""
    objects = build._objects()
    registry.adopt_orphans(registry.loose(objects), objects)
    registry.link_owned(objects, getattr(build, "owned", ()))
    return outliner.sync(build._objects(), top, tag)


def migrate(build):
    """Things for a scene built before things existed (or objects left without one); nothing when every object of
    the chat's already belongs to a thing."""
    try:
        objects = build._objects()
    except (RuntimeError, ReferenceError):
        return
    if any(not registry.thing_of(o) and o.type not in registry.SKIP_TYPES for o in objects):
        registry.migrate(objects, lambda o: bool(o.get("zone")))


THINGS_MAX = 60  # things read_scene lists, with their kind, labels and parent


def report(objects):
    """read_scene's entries: ``things`` (name, kind, labels, parent thing, parts) and ``orphans`` with what to do."""
    entries = registry.inventory(objects)
    out = {}
    if entries:
        out["things"] = [{k: e[k] for k in ("name", "kind", "labels", "parent", "parts") if e[k]}
                         for e in entries[:THINGS_MAX]]
        if len(entries) > THINGS_MAX:
            out["things_more"] = len(entries) - THINGS_MAX
    loose = [o.name for o in registry.loose(objects)][:ORPHANS_MAX]
    if loose:
        out["orphans"] = loose
        out["orphans_note"] = ORPHANS_NOTE % ", ".join(loose)
    return out


def finish(build):
    """At the end of a run: every thing and part named by one scheme, and the collections renamed with them.
    Returns how many names changed; the run's undo step for it is the caller's."""
    try:
        objects = build._objects()
        changed = outliner.rename(objects)
        if changed:
            outliner.sync(build._objects(), build._collection(), build.tag)
        return changed
    except (RuntimeError, ReferenceError):
        return 0
