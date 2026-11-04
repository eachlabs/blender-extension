"""What a person sees of things in Blender: one collection per thing, nested for child things, and the names the
add-on gives at the end of a run (``Town hall``, ``Clock (Town hall)``, ``Town hall / Roof``). Main thread only."""

import re

import bpy

from . import ids, registry

KEEP_NAME = ("zone", "eachlabs_placeholder", "eachlabs_generated")  # names other code finds these by


def sync(objects, top, tag):
    """Put every object of a thing into that thing's collection, under its parent thing's, under ``top`` (the
    run's collection). ``tag(collection)``: marks a new collection as the chat's. Returns how many objects moved."""
    found = registry.roots(objects)
    if not found:
        return 0
    existing = {c.get(ids.THING): c for c in top.children_recursive if c.get(ids.THING)}
    made = {}

    def collection(tid, depth=0):
        if tid in made:
            return made[tid]
        root = found[tid]
        pid = registry.parent_of(root, found)
        holder = collection(pid, depth + 1) if pid in found and depth < 32 else top
        coll = existing.get(tid)
        if coll is None:
            coll = bpy.data.collections.new(root.name)
            coll[ids.THING] = tid
            tag(coll)
        if coll.name != root.name and not coll.name.startswith(root.name + "."):
            coll.name = root.name
        if coll.name not in holder.children:
            for other in [top] + list(top.children_recursive):
                if other is not holder and coll.name in other.children:
                    other.children.unlink(coll)
            holder.children.link(coll)
        made[tid] = coll
        return coll

    moved = 0
    for obj in objects:
        tid = registry.thing_of(obj)
        if tid not in found:
            continue
        coll = collection(tid)
        if obj.name not in coll.objects:
            coll.objects.link(obj)
            moved += 1
        for other in list(obj.users_collection):
            if other is not coll and (other is top or other in top.children_recursive):
                other.objects.unlink(obj)
    # A thing that is gone leaves an empty collection behind; a gone child thing's collection goes first, so
    # its parent's empties too (a fence removed with its gates).
    gone = {tid: coll for tid, coll in existing.items() if tid not in found}
    while True:
        empty = [tid for tid, coll in gone.items() if not coll.objects and not coll.children]
        if not empty:
            break
        for tid in empty:
            bpy.data.collections.remove(gone.pop(tid))
    return moved


def _number(name, base):
    """3 for ``Base 3`` (or ``base_3.001``), else 0."""
    words = ids.base_name(name), " ".join(str(name).replace("_", " ").split()).rsplit(".", 1)[0]
    tail = words[1][len(base):].strip() if words[0] == base and words[1].lower().startswith(base.lower()) else ""
    return int(tail) if tail.isdigit() else 0


def _numbered(groups, current, order):
    """``{base: [key]}`` -> ``{key: name}``: a lone key takes the base, repeated ones ``Base 1``, ``Base 2``... A
    key already called ``Base 3`` keeps its number, so a name said in the chat still means it; the rest take the
    free numbers in ``order``."""
    names = {}
    for base, keys in groups.items():
        if len(keys) == 1:
            names[keys[0]] = base
            continue
        held = {}
        for key in sorted(keys, key=order):
            number = _number(current(key), base)
            if number and number not in held:
                held[number] = key
        names.update({key: "%s %d" % (base, n) for n, key in held.items()})
        free = (n for n in range(1, 10 ** 6) if n not in held)
        for key in sorted((k for k in keys if k not in names), key=order):
            names[key] = "%s %d" % (base, next(free))
    return names


def _own_name(name, things):
    """A thing's name without the ``(Parent)`` this scheme added, so naming twice gives the same names."""
    while True:
        match = re.search(r" \(([^()]+)\)$", name)
        if not match or match.group(1).lower() not in things:
            return name
        name = name[:match.start()]


def rename(objects):
    """Name every thing and part by one scheme; returns how many names changed. Things, and parts within a thing,
    of the same name get numbers in creation order; zones, 3D placeholders and generated models keep theirs (other
    code finds them by name)."""
    found = registry.roots(objects)
    things = {r.name.split(" (")[0].lower() for r in found.values()}
    bases = {}
    copied = {root.get(ids.COPY_OF) for root in found.values() if root.get(ids.COPY_OF)}
    for tid, root in found.items():
        if any(root.get(key) for key in KEEP_NAME):
            continue
        # A thing with copies, and every copy, go by their kind ("Fir tree 1"), never by a working name the
        # model gave the first one.
        family = root.get(ids.COPY_OF) or (tid if tid in copied else "")
        base = ids.title(root.get(ids.KIND)) if family and root.get(ids.KIND) else ""
        bases.setdefault(base or ids.base_name(_own_name(root.name, things)), []).append(tid)
    names = _numbered(bases, lambda t: _own_name(found[t].name, things), lambda t: found[t].session_uid)
    changed = 0

    def final(tid, depth=0):
        root = found[tid]
        own = names.get(tid, root.name)
        pid = registry.parent_of(root, found)
        if pid in found and pid in names and depth < 32:
            return ids.thing_name(own, final(pid, depth + 1).split(" (")[0])
        return own[:ids.NAME_MAX]

    for tid, root in found.items():
        if tid not in names:
            continue
        name = final(tid)
        if root.name != name:
            root.name = name
            changed += 1
    parts, by_uid = {}, {}
    for obj in objects:
        tid = registry.thing_of(obj)
        if tid not in names or registry.is_root(obj) or any(obj.get(key) for key in KEEP_NAME):
            continue
        root = found[tid]
        name = ids.part_name(root.name.split(" (")[0], obj.name, root.get(ids.KIND) or "")
        base = re.sub(r"(\s\d+)+$", "", name) or name
        parts.setdefault((tid, base), []).append(obj.session_uid)
        by_uid[obj.session_uid] = obj
    groups = {}
    for (tid, base), uids in parts.items():
        groups.setdefault(base, []).extend(uids)  # bases already start with their thing's name
    for uid, name in _numbered(groups, lambda u: by_uid[u].name, lambda u: u).items():
        obj = by_uid[uid]
        if obj.name != name[:ids.NAME_MAX]:
            obj.name = name[:ids.NAME_MAX]
            changed += 1
    return changed
