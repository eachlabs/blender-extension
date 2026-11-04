"""What the model's code finds defined in every step: scene, attach(), replace(), copy_thing(), blend(), thing(),
zone(), place(), scatter() and safe copies of Blender modules."""

import bmesh
import bpy
import builtins
import math
import mathutils
import random
import types

from .. import code_check
from . import blend, replaced


def _public_copy(name, source):
    """A module holding only ``source``'s public, non-module attributes."""
    copy = types.ModuleType(name)
    for attr in dir(source):
        value = getattr(source, attr)
        if not attr.startswith("_") and not isinstance(value, types.ModuleType):
            setattr(copy, attr, value)
    return copy



_MATH = _public_copy("math", math)



def _world_of(obj):
    """An object's world matrix from its own data, without an evaluated scene: an object made in this step has
    no ``matrix_world`` yet (it reads as the identity until the view layer updates)."""
    matrix, seen = obj.matrix_basis.copy(), {obj.as_pointer()}
    while obj.parent is not None and obj.parent.as_pointer() not in seen:
        matrix = obj.matrix_parent_inverse @ matrix
        obj = obj.parent
        seen.add(obj.as_pointer())
        matrix = obj.matrix_basis @ matrix
    return matrix



def attach(part, root):
    """Make ``part`` a child of ``root`` and keep it where it stands in the world. Given to every step."""
    world = _world_of(part)
    part.parent = root
    part.matrix_parent_inverse = _world_of(root).inverted()
    part.matrix_basis = world
    return part



def copy_thing(root, location, turn=0.0, size=1.0, scene=None):
    """A copy of ``root`` and everything under it, sharing their meshes and materials (cheap: a forest of hundreds
    of trees costs little more than one), standing at ``location`` (x, y, z), turned ``turn`` radians about Z and
    scaled ``size``. Returns the copy's root. Given to every step."""
    target = scene if scene is not None else bpy.context.scene
    copies = {}

    def clone(obj, parent):
        dup = obj.copy()  # shares obj.data
        target.collection.objects.link(dup)
        if parent is not None:
            dup.parent = parent
            dup.matrix_parent_inverse = obj.matrix_parent_inverse.copy()
        copies[obj.as_pointer()] = dup
        for child in obj.children:
            clone(child, dup)
        return dup

    top = clone(root, None)
    top.parent = None
    top.matrix_parent_inverse.identity()
    top.matrix_basis = (mathutils.Matrix.Translation(location) @ mathutils.Matrix.Rotation(turn, 4, "Z")
                        @ mathutils.Matrix.Scale(size, 4) @ mathutils.Matrix.LocRotScale(
                            None, root.matrix_basis.to_quaternion(), root.matrix_basis.to_scale()))
    return top



def _placement_calls(requests):
    """zone(), place(), scatter() and thing() for one step: each checks what it was given and queues it in ``requests``;
    the add-on carries them out when the step's code has run."""
    from ..placement import relations

    def zone(name, size=None, ring_m=None, inside=None, around=None, near=None, apart_m=None, gap_m=2.0, holds=None):
        requests.append(("zone", relations.area(name, size, ring_m, inside, around, near, apart_m, gap_m, holds)))
        return name

    def place(thing, zone=None, on="ground", near=None, facing=None, against=None, apart_m=None, around=None,
              row=None, gap_m=relations.GAP_DEFAULT_M):
        name = getattr(thing, "name", thing)
        requests.append(("place", relations.thing(name, zone, on, near, facing, against, apart_m, around, row,
                                                  gap_m)))
        return name

    def scatter(thing, zone, count, gap_m=None, size=(0.8, 1.2), turn=True, seed=0):
        name = getattr(thing, "name", thing)
        requests.append(("scatter", relations.scatter(name, zone, count, gap_m, size, turn, seed)))
        return name

    def thing(obj, kind, labels="", parent=None):
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("thing() needs a kind: a word or two saying what it is, like \"fence\"")
        name = getattr(obj, "name", obj)
        parent = getattr(parent, "name", parent)
        requests.append(("thing", {"thing": name, "kind": kind, "labels": labels if isinstance(labels, str)
                                   else ", ".join(str(w) for w in labels), "parent": parent}))
        return obj

    return {"zone": zone, "place": place, "scatter": scatter, "thing": thing}


def _namespace(scene=None, requests=None):
    """A fresh namespace for one step; ``import`` inside it gives the same modules. ``scene``: the scene the
    step builds in, given to the step under that name. ``requests``: where zone(), place() and scatter() queue
    what they were asked."""
    rng = random.Random()
    methods = {attr: getattr(rng, attr) for attr in dir(rng)
               if not attr.startswith("_") and callable(getattr(rng, attr))}
    modules = {"bpy": bpy, "bmesh": bmesh, "mathutils": mathutils, "math": _MATH,
               "random": _public_copy("random", types.SimpleNamespace(Random=random.Random, **methods))}

    def step_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.partition(".")[0]
        if level or root not in modules:
            raise ImportError("Only these imports work: %s." % ", ".join(code_check.ALLOWED_IMPORTS))
        if root in ("math", "random"):
            return modules[root]
        return builtins.__import__(name, globals, locals, fromlist, level)

    step_builtins = {k: v for k, v in vars(builtins).items() if k not in code_check.BLOCKED_NAMES}
    step_builtins["__import__"] = step_import
    namespace = dict(modules, __name__="__main__", __builtins__=step_builtins, attach=attach, replace=replaced.replace)
    queue = requests if requests is not None else []

    def step_copy_thing(root, location, turn=0.0, size=1.0):
        top = copy_thing(root, location, turn, size, scene)
        queue.append(("copy", {"thing": top.name, "of": root.name}))  # the copy becomes a thing like its original
        return top

    namespace["copy_thing"] = step_copy_thing
    namespace["blend"] = lambda parts, softness=0.5: blend.blend(parts, softness, scene)
    namespace.update(_placement_calls(queue))
    if scene is not None:
        namespace["scene"] = scene
    return namespace
