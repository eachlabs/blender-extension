"""Removing a part's old version when a newer one replaced it. Main thread only.

When the model rebuilds a part of a thing (a better clock dial, a new sign) its code is told to delete the old one,
and does not always: the old version stays behind or in front of the new. After each build stage the add-on looks for
flat parts of one thing that do the same job and lie over each other (``checks.duplicates.stacked``) and removes the
older one with everything under it. Parts of two different things are not touched here: read_scene lists them as
duplicates for the fix stage, because which of two things is the extra one is the model's call.
"""

import bpy

from ..checks import duplicates

_GEOMETRY = ("MESH", "CURVE", "SURFACE", "FONT", "META")


def _remove_tree(obj):
    removed = []
    for part in [obj] + list(obj.children_recursive):
        removed.append(part.name)
    for part in reversed([obj] + list(obj.children_recursive)):
        bpy.data.objects.remove(part, do_unlink=True)
    return removed


def prune(build):
    """Remove the older of each pair of stacked same-job parts within one of the chat's things; returns
    ``[{"thing", "removed", "kept"}]``, also kept on the build as ``replaced_parts`` for read_scene."""
    scene = build.scene
    mine = [o for o in scene.objects if build.owns(o) and o.type in _GEOMETRY and not o.hide_render]
    by_name = {o.name: o for o in mine}
    done = []
    gone = set()
    for older, newer in duplicates.stacked(duplicates.measure(mine)):
        if older["thing"] != newer["thing"] or older["name"] in gone or newer["name"] in gone:
            continue
        if not duplicates.similar_faces(older, newer):
            continue  # a small plaque on a big board is a detail, not an old version
        obj = by_name.get(older["name"])
        if obj is None or obj.name == older["thing"]:
            continue  # never the thing's own root
        removed = _remove_tree(obj)
        gone.update(removed)
        done.append({"thing": older["thing"], "removed": removed[0], "kept": newer["name"]})
    if done:
        build.replaced_parts = (getattr(build, "replaced_parts", None) or []) + done
        for layer in scene.view_layers:
            layer.update()
        build.note_change()
    return done


def replace(old, new):
    """Remove ``old`` and everything under it, keeping ``new``; for a step that rebuilt a part. Given to every step.
    Returns ``new``."""
    if old is not None and old != new and old.name in bpy.data.objects:
        _remove_tree(old)
    return new
