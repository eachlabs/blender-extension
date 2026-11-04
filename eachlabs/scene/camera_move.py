"""The scene camera's keyed move: its location keys, its length, and the notes about it."""

from mathutils import Vector

from .. import compat


CAMERA_STILL_NOTE = ("Your step stopped the camera move: it moved %.1f m from the first to the last frame, now it "
                     "stays still. Unless the request asks for a still camera, key the move again: move both location "
                     "keys by the same offset, so the move stays.")
CAMERA_RETIMED_NOTE = "The camera's move now spans the new frame range, frames %d to %d."
MOVE_CHECKS = (0.25, 0.5, 0.75)  # points of a camera move, between its first and last frame, camera_view also checks



def _location_keys(cam):
    """``{axis: [(frame, value), ...]}`` of the object's location keys."""
    return {fc.array_index: [(round(kp.co[0], 3), round(kp.co[1], 4)) for kp in fc.keyframe_points]
            for fc in compat.object_fcurves(cam) if fc.data_path == "location"}



def _camera_move(cam, scene):
    """Metres the object's keyed location moves from the scene's first to its last frame; 0 without keys."""
    curves = {fc.array_index: fc for fc in compat.object_fcurves(cam) if fc.data_path == "location"}
    if not curves:
        return 0.0
    ends = [Vector([curves[i].evaluate(frame) if i in curves else cam.location[i] for i in range(3)])
            for frame in (scene.frame_start, scene.frame_end)]
    return round((ends[1] - ends[0]).length, 2)
