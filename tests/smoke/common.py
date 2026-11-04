"""What every smoke module shares: the check list, the work folder and the step helpers."""

import tempfile

import bpy

from tests import blender_fakes


SKIA_ERROR = blender_fakes.ensure_skia()


RESULTS = []
WORK = tempfile.mkdtemp(prefix="eachlabs-smoke-")


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    print("%s  %s%s" % ("PASS" if condition else "FAIL", name, ("  (%s)" % detail) if detail else ""))


class _FakeLayout:
    """Records labels and operators; any other call returns a new layout."""

    def __init__(self, log):
        self.log = log
        self.alert = False

    def label(self, text="", **kwargs):
        self.log.append(("label", text))

    def operator(self, idname, text="", **kwargs):
        self.log.append(("operator", idname))
        return type("Props", (), {})()

    def __getattr__(self, name):
        return lambda *args, **kwargs: _FakeLayout(self.log)


def _chat_tree(build):
    """The run's collection and the things' collections in it."""
    top = bpy.data.collections[build.collection_name]
    return [top] + list(top.children_recursive)


def _step(build, code):
    """Run one model step through the tool path; the result as the model sees it."""
    return build.execute("run_python", {"code": code})


BOX_CODE = '''# Code versions of the 3D objects
def box(name, size, at):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0, 0, size[2] / 2), verts=bm.verts)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = at
    scene.collection.objects.link(obj)
    return obj
'''
