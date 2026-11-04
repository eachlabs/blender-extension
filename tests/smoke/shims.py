"""Version shims for scene building."""

import bpy

from eachlabs import compat
from tests.smoke.common import check


def test_scene_shims():
    scene = bpy.data.scenes.new("eachlabs_shims")
    try:
        obj = bpy.data.objects.new("eachlabs_shims_empty", None)
        scene.collection.objects.link(obj)
        obj.location = (0, 0, 0)
        obj.keyframe_insert("location", frame=1)
        obj.location = (4, 0, 0)
        obj.keyframe_insert("location", frame=120)
        fcurves = list(compat.object_fcurves(obj))
        check("scene shims: object_fcurves finds the location curves", len(fcurves) == 3, str(len(fcurves)))
        bare = bpy.data.objects.new("eachlabs_shims_bare", None)
        check("scene shims: object without animation has no curves", list(compat.object_fcurves(bare)) == [])
    finally:
        bpy.data.scenes.remove(scene)
