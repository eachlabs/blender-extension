"""Keeping versions of one object for the render judge: stash a copy, put a stashed copy back, drop them.

Main thread only. A stash is a copy of the object's whole tree (objects and their mesh data) linked into a scene of
its own, so the build's scene, its checks and the person never see it. Putting a version back removes the live tree
and links fresh copies of the stashed one under the original names, as objects of the chat's own. It all happens
inside the detail stage, so one undo takes the stage back whichever version won.
"""

import uuid

import bpy

from .. import visual_check

STORE = "eachlabs candidates"
STASH_NAME = "~eachlabs stash"  # stashed copies are named after this, never after the object
SHOT_VIEWS = 2  # close-up sides per version sent to the judge: two keep the judge call cheap
_stashes = {}  # key -> [(stashed object name, original name, original parent name, collection names)]


def _store():
    scene = bpy.data.scenes.get(STORE)
    return scene if scene is not None else bpy.data.scenes.new(STORE)


def _tree(build, name):
    root = build.scene.objects.get(name)
    if root is None or not build.owns(root):
        raise ValueError("%s is not one of the chat's objects" % name)
    return [root] + list(root.children_recursive)


def _copy(obj):
    clone = obj.copy()
    if obj.data is not None:
        clone.data = obj.data.copy()
    return clone


def stash(build, name):
    """Copy the object ``name`` and its parts aside; returns the stash's key."""
    store, tree, rows, copies = _store(), _tree(build, name), [], {}
    key = uuid.uuid4().hex[:12]
    for index, obj in enumerate(tree):
        clone = _copy(obj)
        # A name that starts like no object's: a step that removes "every object named like the sofa" would
        # otherwise remove its stashed copies too (seen in a cabin's detail stage).
        clone.name = "%s %s %d" % (STASH_NAME, key, index)
        store.collection.objects.link(clone)
        copies[obj.name] = clone
        rows.append((clone.name, obj.name, obj.parent.name if obj.parent is not None else None,
                     [c.name for c in obj.users_collection]))
    for obj in tree:
        if obj.parent is not None and obj.parent.name in copies:
            copies[obj.name].parent = copies[obj.parent.name]
            copies[obj.name].matrix_parent_inverse = obj.matrix_parent_inverse.copy()
    _stashes[key] = rows
    return key


def restore(build, name, key):
    """Put the stashed version ``key`` of ``name`` back in place of the live one, under the original names."""
    rows = _stashes.get(key)
    if not rows:
        raise ValueError("no stashed version %s" % key)
    scene = build.scene
    live = _tree(build, name)
    if any(bpy.data.objects.get(stashed) is None for stashed, *_rest in rows):
        raise ValueError("the stashed version of %s is incomplete" % name)
    # The new copies are made and linked first; the live object goes only when they all exist, so a failure leaves
    # the live version as it was.
    fresh, made = {}, []
    try:
        for stashed, original, _parent, collections in rows:
            clone = _copy(bpy.data.objects[stashed])
            clone.parent = None
            made.append(clone)
            linked = False
            for cname in collections:
                coll = scene.collection if cname == scene.collection.name else bpy.data.collections.get(cname)
                if coll is not None:
                    coll.objects.link(clone)
                    linked = True
            if not linked:
                scene.collection.objects.link(clone)
            fresh[original] = clone
        for stashed, original, parent, _collections in rows:
            if parent in fresh:
                fresh[original].parent = fresh[parent]
                fresh[original].matrix_parent_inverse = bpy.data.objects[stashed].matrix_parent_inverse.copy()
    except Exception:
        for clone in made:
            try:
                bpy.data.objects.remove(clone)
            except ReferenceError:
                pass
        raise
    for obj in reversed(live):
        data = obj.data
        bpy.data.objects.remove(obj)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
    for original, clone in fresh.items():
        clone.name = original  # free now that the live object is gone
        build._tagged.add(clone.session_uid)  # the chat's own again: the tags came with the copy
    for layer in scene.view_layers:
        layer.update()
    return {"restored": name, "objects": len(fresh)}


def drop(keys):
    """Delete the stashed versions ``keys`` and, when nothing is left in it, their scene."""
    for key in keys:
        for stashed, _original, _parent, _collections in _stashes.pop(key, ()):
            obj = bpy.data.objects.get(stashed)
            if obj is None:
                continue
            data = obj.data
            bpy.data.objects.remove(obj)
            if isinstance(data, bpy.types.Mesh) and data.users == 0:
                bpy.data.meshes.remove(data)
    store = bpy.data.scenes.get(STORE)
    if store is not None and not store.objects and not _stashes:
        bpy.data.scenes.remove(store)


def shot(build, name):
    """A few close-up sides of ``name`` for the judge: ``{"images": [...]}``, empty with a ``reason`` on failure."""
    found = visual_check.render_object(build, name)
    return {"images": (found.get("images") or [])[:SHOT_VIEWS], "reason": found.get("reason", "")}
