"""Which thing each object belongs to, in a Blender scene: declaring a thing, giving every object its thing's id,
the inventory, and removing a whole thing when its root goes. Main thread only.

A thing's **root** is the object carrying its kind (``ids.KIND``). An object belongs to the nearest root among
itself and its Blender parents; an object with no root above it keeps the id it was given, and one with none at all
is an orphan until the model attaches it or declares it."""

from . import ids

SKIP_TYPES = ("LIGHT", "CAMERA")  # stage-level objects: they belong to the scene, not to a thing


def is_root(obj):
    return bool(obj.get(ids.KIND)) and bool(obj.get(ids.THING))


def root_of(obj):
    """The root of the thing ``obj`` belongs to by hierarchy: itself or its nearest parent that is a root."""
    seen = set()
    while obj is not None and obj.as_pointer() not in seen:
        if is_root(obj):
            return obj
        seen.add(obj.as_pointer())
        obj = obj.parent
    return None


def thing_of(obj):
    value = obj.get(ids.THING)
    return value if isinstance(value, str) else ""


def _taken(objects):
    return {thing_of(o) for o in objects if thing_of(o)}


def declare(obj, kind, labels="", parent=None, objects=()):
    """Make ``obj`` the root of a thing (or describe the thing it already roots); returns the id. ``parent``: an
    object of the parent thing, its name's object, or a thing id."""
    tid = thing_of(obj) if is_root(obj) else ids.new_id(_taken(objects))
    obj[ids.THING] = tid
    obj[ids.KIND] = ids.clean_word(kind) or ids.kind_from_name(obj.name)
    obj[ids.LABELS] = ", ".join(ids.labels(labels, obj[ids.KIND]))
    if parent is not None:
        obj[ids.PARENT] = parent_id(parent, objects)
    elif ids.PARENT not in obj:
        obj[ids.PARENT] = ""
    return tid


def parent_id(parent, objects=()):
    """A thing id from an object, an object's name or an id."""
    if isinstance(parent, str):
        named = next((o for o in objects if o.name == parent), None)
        if named is None:
            return parent if any(thing_of(o) == parent for o in objects) else ""
        parent = named
    root = root_of(parent) if parent is not None else None
    return thing_of(root) if root is not None else ""


def parent_of(root, roots):
    """The parent thing's id: the one the model gave, else the nearest root above it in the hierarchy."""
    given = root.get(ids.PARENT)
    if isinstance(given, str) and given and given in roots and given != thing_of(root):
        return given
    above = root_of(root.parent) if root.parent is not None else None
    return thing_of(above) if above is not None else ""


def roots(objects):
    """``{id: root object}``."""
    return {thing_of(o): o for o in objects if is_root(o)}


def snapshot(objects):
    """What ``cascade`` compares against: each thing's root and parent, and each object's thing."""
    found = roots(objects)
    return {"roots": {tid: o.session_uid for tid, o in found.items()},
            "parents": {tid: parent_of(o, found) for tid, o in found.items()},
            "members": {o.session_uid: thing_of(o) for o in objects if thing_of(o)}}


def refresh(objects, new_uids, context=None):
    """After a step: copies of a thing become things of their own, every object takes its root's id, a new loose
    object joins ``context`` (the root a detail step or a one-target edit works on), and the new objects left with
    no thing are returned (top-most first), as orphans."""
    shared = {}  # a copy of a root (copy_thing, scatter, obj.copy()) carries the original's id
    for obj in objects:
        if is_root(obj):
            shared.setdefault(thing_of(obj), []).append(obj)
    taken = _taken(objects)
    for tid, group in shared.items():
        if len(group) < 2:
            continue
        old = [o for o in group if o.session_uid not in new_uids]
        keep = old[0] if old else min(group, key=lambda o: o.session_uid)
        for obj in group:
            if obj is keep:
                continue
            new = ids.new_id(taken)
            taken.add(new)
            obj[ids.THING] = new
            for part in obj.children_recursive:
                if thing_of(part) == tid:
                    part[ids.THING] = new
    alive_roots = roots(objects)
    context_id = thing_of(context) if context is not None and is_root(context) else ""
    orphans = []
    for obj in objects:
        root = root_of(obj)
        if root is not None:
            obj[ids.THING] = thing_of(root)
            continue
        if obj.session_uid not in new_uids or obj.type in SKIP_TYPES:
            continue
        if context_id:
            obj[ids.THING] = context_id
        elif thing_of(obj) not in alive_roots:
            orphans.append(obj)
    ids_of = {o.session_uid for o in orphans}
    return [o for o in orphans if o.parent is None or o.parent.session_uid not in ids_of]


def _world(obj):
    """An object's world matrix from its own data: one made in this step reads as the identity until the view
    layer updates."""
    matrix, seen = obj.matrix_basis.copy(), {obj.as_pointer()}
    while obj.parent is not None and obj.parent.as_pointer() not in seen:
        matrix = obj.matrix_parent_inverse @ matrix
        obj = obj.parent
        seen.add(obj.as_pointer())
        matrix = obj.matrix_basis @ matrix
    return matrix


def gather(objects):
    """Put every loose part of a thing (one that carries the thing's id but stands outside its root's hierarchy)
    under that root, where it stands, so whatever moves the thing moves all of it. Returns how many moved."""
    found = roots(objects)
    moved = 0
    for obj in objects:
        tid = thing_of(obj)
        if tid not in found or obj is found[tid] or obj.type in SKIP_TYPES or root_of(obj) is not None:
            continue
        root = found[tid]
        if obj in root.children_recursive or root in obj.children_recursive:
            continue
        world = _world(obj)
        obj.parent = root
        obj.matrix_parent_inverse = _world(root).inverted()
        obj.matrix_basis = world
        moved += 1
    return moved


def cascade(objects, before):
    """The objects to remove because a step removed the root of their thing or of a thing above it: the rest of
    that thing and its child things, among the objects that existed before the step and have no root now."""
    alive = {o.session_uid for o in objects}
    gone = [tid for tid, uid in before["roots"].items() if uid not in alive]
    doomed = set()
    for tid in gone:
        doomed.update(ids.subtree(before["parents"], tid))
    if not doomed:
        return []
    out = []
    for obj in objects:
        if obj.session_uid not in before["members"] or before["members"][obj.session_uid] not in doomed:
            continue
        root = root_of(obj)
        if root is not None and thing_of(root) not in doomed:
            continue  # the step moved it under a thing that stays
        out.append(obj)
    return out


def loose(objects):
    """Objects that belong to no living thing (lights and cameras aside), top-most first."""
    found = roots(objects)
    out = [o for o in objects if o.type not in SKIP_TYPES and root_of(o) is None and thing_of(o) not in found]
    uids = {o.session_uid for o in out}
    return [o for o in out if o.parent is None or o.parent.session_uid not in uids]


def adopt_orphans(orphans, objects):
    """Orphans left at the end of a stage become things of their own, named after themselves."""
    for obj in orphans:
        if obj.session_uid in {o.session_uid for o in objects} and not is_root(obj):
            declare(obj, ids.kind_from_name(obj.name), objects=objects)
            for part in obj.children_recursive:
                if root_of(part) is obj:
                    part[ids.THING] = thing_of(obj)


def migrate(objects, is_area):
    """Give things to objects built before things existed: one thing per top object (an area for a zone), parts by
    hierarchy, and a thing placed in an area gets the area as its parent thing."""
    mine = {o.session_uid for o in objects}
    for obj in objects:
        if is_root(obj) or obj.type in SKIP_TYPES:
            continue
        top = obj.parent is None or obj.parent.session_uid not in mine or is_area(obj.parent)
        if top or is_area(obj):
            declare(obj, "area" if is_area(obj) else ids.kind_from_name(obj.name), objects=objects)
    found = roots(objects)
    for obj in objects:
        root = root_of(obj)
        if root is not None:
            obj[ids.THING] = thing_of(root)
    for tid, root in found.items():
        if not root.get(ids.PARENT):
            root[ids.PARENT] = parent_of(root, found)


def inventory(objects):
    """One entry per thing: id, name (its root's), kind, labels, parent's name and id, part count."""
    found = roots(objects)
    counts = {}
    for obj in objects:
        tid = thing_of(obj)
        if tid in found and obj is not found[tid]:
            counts[tid] = counts.get(tid, 0) + 1
    out = []
    for tid, root in found.items():
        pid = parent_of(root, found)
        out.append({"id": tid, "name": root.name, "kind": root.get(ids.KIND) or "",
                    "labels": [w for w in str(root.get(ids.LABELS) or "").split(", ") if w],
                    "parent": found[pid].name if pid in found else "", "parent_id": pid,
                    "parts": counts.get(tid, 0)})
    return out


def link_owned(objects, pairs):
    """The plan's "belongs to" pairs (``(thing word, owner word)``: a gate in a fence, a sign on a shop) as parent
    links: each thing a word names that has no parent thing yet gets the owner's thing. Returns the names linked."""
    entries = inventory(objects)
    found = roots(objects)
    linked = []
    for word, owner_word in pairs:
        owner = next((e for e in entries if ids.matches(e, owner_word)), None)
        if owner is None:
            continue
        for entry in entries:
            if entry["id"] == owner["id"] or entry["parent_id"] or not ids.matches(entry, word):
                continue
            if owner["id"] in ids.subtree({e["id"]: e["parent_id"] for e in entries}, entry["id"]):
                continue  # the owner already belongs to it: no loop
            found[entry["id"]][ids.PARENT] = owner["id"]
            entry["parent_id"] = owner["id"]
            linked.append(entry["name"])
    return linked


def subtree_objects(objects, names, children=True):
    """Every object of the things the named objects belong to, with their child things unless ``children`` is
    False: what an edit, a removal, a find or a selection of these names means."""
    found = roots(objects)
    parents = {tid: parent_of(r, found) for tid, r in found.items()}
    by_name = {o.name: o for o in objects}
    tids = set()
    for name in names:
        obj = by_name.get(name)
        root = root_of(obj) if obj is not None else None
        if root is not None:
            tids.update(ids.subtree(parents, thing_of(root)) if children else [thing_of(root)])
    return [o for o in objects if thing_of(o) in tids]


def thing_root_name(obj):
    """The name of the root of ``obj``'s thing, or ``obj``'s own name when it belongs to none."""
    root = root_of(obj)
    return root.name if root is not None else obj.name
