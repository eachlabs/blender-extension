"""What the scene camera sees: framing, the subject through the move, and keeping a camera move intact."""

import bpy
import re
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from .. import chat_loop, compat
from ..checks import framing
from .common import FLAT, GEOMETRY, RAY_REACH, _box, _cap, _r, is_root
from .common import extent as common_extent
from .camera_move import (  # noqa: F401
    CAMERA_RETIMED_NOTE,
    CAMERA_STILL_NOTE,
    MOVE_CHECKS,
    _camera_move,
    _location_keys,
)
from .view_lists import GRID, GROUP_MIN, _empty_share, _grouped, _kind  # noqa: F401


VIEW_MAX = 30  # entries per list in camera_view
# Directions that must all meet one of the run's objects for the camera to count as inside the walls it built;
# not up, since a room is often built without a ceiling.
ENCLOSURE = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0))
BOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
MOVING, STILL = chat_loop.CAMERA_MOVING, chat_loop.CAMERA_STILL


class CameraView:
    def _camera_keys(self):
        """The scene camera's location keys, the frame range and its move, when the camera is the run's."""
        scene = self.scene
        cam = scene.camera
        if cam is None or not self._mine(cam):
            return None
        return {"uid": cam.session_uid, "range": (scene.frame_start, scene.frame_end), "keys": _location_keys(cam),
                "move": _camera_move(cam, scene)}

    def _keep_camera_move(self, before):
        """After a step: stretch the camera's two keys to a frame range the step changed, when the step left the
        keys alone; else say so when the step stopped a camera move. Returns the note for the model, or ``None``."""
        if before is None or before["move"] < MOVING:
            return None
        scene = self.scene
        cam = scene.camera
        new_range = (scene.frame_start, scene.frame_end)
        if (cam is not None and cam.session_uid == before["uid"] and new_range != before["range"]
                and _location_keys(cam) == before["keys"] and new_range[0] < new_range[1]):
            old = before["range"]
            frames = {frame for keys in before["keys"].values() for frame, _value in keys}
            if frames <= set(old):
                for fc in compat.object_fcurves(cam):
                    if fc.data_path != "location":
                        continue
                    for kp in fc.keyframe_points:
                        shift = (new_range[0] - old[0]) if kp.co[0] == old[0] else (new_range[1] - old[1])
                        kp.co[0] += shift
                        kp.handle_left[0] += shift
                        kp.handle_right[0] += shift
                    fc.update()
                return CAMERA_RETIMED_NOTE % new_range
        if cam is None or _camera_move(cam, scene) < STILL:
            return CAMERA_STILL_NOTE % before["move"]
        return None

    def _ray(self, scene, depsgraph, origin, direction, reach, wanted):
        """``(object, distance, normal)`` of the first object a ray meets within ``reach`` for which
        ``wanted(object, normal)`` is true, or ``None``."""
        travelled = 0.0
        for _ in range(32):
            if travelled >= reach:
                return None
            hit, location, normal, _index, obj, _matrix = scene.ray_cast(depsgraph, origin, direction,
                                                                         distance=reach - travelled)
            if not hit or obj is None:
                return None
            travelled += (location - origin).length
            obj = obj.original
            if wanted(obj, normal):
                return obj, travelled, normal
            origin = location + direction * 0.001
            travelled += 0.001
        return None

    def _first_other(self, scene, depsgraph, origin, direction, own, reach):
        """``(object, distance)`` of the first object a ray meets that is not one of ``own`` (session_uid), or
        ``None``."""
        travelled = 0.0
        for _ in range(32):
            hit, location, _normal, _index, obj, _matrix = scene.ray_cast(depsgraph, origin, direction,
                                                                          distance=reach - travelled)
            if not hit or obj is None:
                return None
            step = (location - origin).length
            travelled += step
            obj = obj.original
            if obj.session_uid not in own:
                return obj, travelled
            origin = location + direction * 0.001
            travelled += 0.001
            if travelled >= reach:
                return None
        return None

    def _camera(self, scene):
        cam = scene.camera
        if cam is None:
            return None
        info = {"yours": self._mine(cam), "location": _r(cam.matrix_world.translation)}
        if info["yours"]:
            info["name"] = cam.name
        if cam.type == "CAMERA":
            info["lens"] = round(cam.data.lens, 1)
        target = self._target(cam)
        if target is not None:
            info["target"] = {"location": _r(target.matrix_world.translation)}
            if self._mine(target):
                info["target"]["name"] = target.name
        else:
            info["rotation_degrees"] = _r([v * 57.29578 for v in cam.matrix_world.to_euler()], 1)
        keys = sorted({round(kp.co[0], 2) for fc in compat.object_fcurves(cam) if fc.data_path == "location"
                       for kp in fc.keyframe_points})
        if keys:
            info["location_keys"] = _cap(keys, 12)
        info["move_m"] = _camera_move(cam, scene)
        info["frame_range"] = [scene.frame_start, scene.frame_end]
        return info

    @staticmethod
    def _target(cam):
        return next((c.target for c in cam.constraints if c.type in ("TRACK_TO", "DAMPED_TRACK", "LOCKED_TRACK")
                     and c.target is not None and not c.mute), None)

    def camera_view(self):
        """What the scene camera sees at the first and the last frame of the scene range."""
        scene = self.scene
        cam = scene.camera
        if cam is None:
            return {"camera": None, "note": "The scene has no camera yet; make one and set scene.camera to it."}
        name = cam.name if self._mine(cam) else "(not yours)"
        current, subframe = scene.frame_current, scene.frame_subframe
        first, last = scene.frame_start, scene.frame_end
        move = _camera_move(cam, scene)
        between = []
        if move >= STILL and last - first > 1:
            between = sorted({round(first + (last - first) * t) for t in MOVE_CHECKS} - {first, last})
        views, checks = [], []
        subject = None
        try:
            scene.frame_set(first)
            views.append(self._view_at(scene, cam, first))
            subject = self._subject(scene, cam, views[0])
            if subject is not None:
                views[0]["subject"] = self._subject_at(scene, cam, subject)
            for frame in between:
                scene.frame_set(frame)
                check = {"frame": frame}
                if subject is not None:
                    check["subject"] = self._subject_at(scene, cam, subject)
                checks.append(check)
            if last != first:
                scene.frame_set(last)
                view = self._view_at(scene, cam, last)
                if subject is not None:
                    view["subject"] = self._subject_at(scene, cam, subject)
                views.append(view)
        finally:
            scene.frame_set(current, subframe=subframe)
        for view in views:
            # Only an aimed-at subject is exempt: without an aim, the subject is what the frame's centre meets first,
            # which is the blocker itself when a post stands in front of the lens.
            aimed = subject.name if subject is not None and self._target(cam) is not None else None
            blockers = framing.near_blockers(view.pop("_close"), aimed)
            if blockers:
                view["near_blockers"] = blockers
        seen = [{"visible": [{"name": n} for n in view.pop("_seen")]} for view in views]
        never = framing.never_in_view(seen, self._big_roots(), getattr(self, "subjects", ()))
        out = {"camera": name, "camera_move_m": move, "frames": views}
        if never:
            out["missing_from_view"] = never
        if subject is not None:
            out["subject"] = subject.name
        if checks and subject is not None:
            out["during_move"] = checks
        return out

    def _big_roots(self):
        """``{root name: [its part names]}`` for the chat's things long enough that a shot is likely about them."""
        found = {}
        for obj in self._objects():
            if obj.parent is not None or obj.get("ground") or obj.get("zone") or obj.type in ("CAMERA", "LIGHT"):
                continue
            where = common_extent(obj)
            if where is not None and max(where["size"]) >= framing.BIG_M:
                found[obj.name] = [obj.name] + [c.name for c in obj.children_recursive]
        return found

    def _subject(self, scene, cam, view):
        """The chat's root object the camera is about at the first frame: what its aim meets, else the biggest
        thing in view that is not ground; ``None`` when there is nothing."""
        hit = (view.get("toward_target") or view.get("frame_centre") or {}).get("first_hit")
        obj = scene.objects.get(hit) if isinstance(hit, str) else None
        candidates = []
        if obj is not None and self._mine(obj):
            candidates.append(obj)
        candidates += [scene.objects.get(v["name"]) for v in view.get("visible") or [] if isinstance(v, dict)]
        for obj in candidates:
            if obj is None or not self._mine(obj):
                continue
            while not is_root(obj) and self._mine(obj.parent):
                obj = obj.parent
            tree = [obj] + list(obj.children_recursive)
            boxes = [_box(o) for o in tree if o.type in GEOMETRY and not o.hide_render]
            if not boxes:
                continue
            low = [min(b[0][i] for b in boxes) for i in range(3)]
            high = [max(b[1][i] for b in boxes) for i in range(3)]
            if high[2] - low[2] > FLAT * max(high[0] - low[0], high[1] - low[1]):
                return obj
        return None

    def _subject_at(self, scene, cam, subject):
        """``{"in_frame", "coverage_pct", "hidden_by"}`` of the subject at the current frame: how much of the frame
        its box covers, and the chat's object a ray from the camera to its middle meets first, if not the subject."""
        depsgraph = self._depsgraph(scene)
        cam_eval = cam.evaluated_get(depsgraph)
        near = max(getattr(cam.data, "clip_start", 0.01), 1e-4) if cam.type == "CAMERA" else 0.01
        tree = [subject] + list(subject.children_recursive)
        own = {o.session_uid for o in tree}
        rects, corners = [], []
        for obj in tree:
            if obj.type not in GEOMETRY or obj.hide_render:
                continue
            state, rect, _cut = self._rect(obj, depsgraph, scene, cam_eval, near)
            if state == "visible":
                rects.append(rect)
            corners.extend(_box(obj))
        coverage = round(100.0 * (1.0 - _empty_share(rects)), 1) if rects else 0.0
        out = {"in_frame": bool(rects), "coverage_pct": coverage}
        if corners:
            middle = Vector([(min(c[i] for c in corners) + max(c[i] for c in corners)) / 2 for i in range(3)])
            origin = cam_eval.matrix_world.translation.copy()
            aim = middle - origin
            if aim.length > 1e-6:
                hit = self._hit(scene, depsgraph, origin, aim.normalized(), aim.length)
                found = scene.objects.get(hit[0]) if hit else None
                if found is not None and found.session_uid not in own and self._mine(found):
                    out["hidden_by"] = self._root_label(found)
        return out

    def _depsgraph(self, scene):
        layer = bpy.context.view_layer if bpy.context.scene == scene else None
        return (layer or scene.view_layers[0]).depsgraph

    @staticmethod
    def _rect(obj, depsgraph, scene, cam_eval, near):
        """``("behind" | "outside" | "visible", rect, cut_off)`` for an object's bounding box in the frame."""
        ev = obj.evaluated_get(depsgraph)
        corners = [ev.matrix_world @ Vector(c) for c in ev.bound_box]
        projected = [world_to_camera_view(scene, cam_eval, c) for c in corners]
        front = [p for p in projected if p.z > near]
        if not front:
            return "behind", None, False
        clipped = len(front) < len(projected)
        for a, b in BOX_EDGES:  # where an edge crosses the near plane, so a box the camera is in still counts
            za, zb = projected[a].z, projected[b].z
            if (za > near) != (zb > near):
                t = (za - near) / (za - zb)
                front.append(world_to_camera_view(scene, cam_eval, corners[a].lerp(corners[b], t)))
        x0, x1 = min(p.x for p in front), max(p.x for p in front)
        y0, y1 = min(p.y for p in front), max(p.y for p in front)
        if x1 < 0 or x0 > 1 or y1 < 0 or y0 > 1:
            return "outside", None, False
        cut = clipped or x0 < 0 or x1 > 1 or y0 < 0 or y1 > 1
        return "visible", (max(x0, 0.0), min(x1, 1.0), max(y0, 0.0), min(y1, 1.0)), cut

    def _hit(self, scene, depsgraph, origin, direction, distance=RAY_REACH):
        """``(name, distance)`` of the first object a ray meets, ``"(not yours)"`` for one the run did not
        make, or ``None`` when it meets nothing."""
        hit, location, _normal, _index, obj, _matrix = scene.ray_cast(depsgraph, origin, direction, distance=distance)
        if not hit or obj is None:
            return None
        obj = obj.original
        return (obj.name if self._mine(obj) else "(not yours)"), round((location - origin).length, 2)

    def _view_at(self, scene, cam, frame):
        depsgraph = self._depsgraph(scene)
        cam_eval = cam.evaluated_get(depsgraph)
        near = max(getattr(cam.data, "clip_start", 0.01), 1e-4) if cam.type == "CAMERA" else 0.01
        visible, behind, outside, rects, close = [], [], [], [], []
        origin = cam_eval.matrix_world.translation.copy()
        mine = self._objects()
        for obj in mine:
            if obj.type not in GEOMETRY or obj.hide_render:
                continue
            state, rect, cut = self._rect(obj, depsgraph, scene, cam_eval, near)
            if state == "behind":
                behind.append(obj.name)
                continue
            if state == "outside":
                outside.append(obj.name)
                continue
            rects.append(rect)
            share = (rect[1] - rect[0]) * (rect[3] - rect[2])
            visible.append({"name": obj.name, "coverage_pct": round(share * 100, 1), "cut_off": cut})
            ev = obj.evaluated_get(depsgraph)
            distance = framing.closest_m(origin, [ev.matrix_world @ Vector(c) for c in ev.bound_box])
            if distance <= framing.NEAR_M:
                root = obj
                while root.parent is not None and self._mine(root.parent):
                    root = root.parent
                close.append({"name": obj.name, "root": root.name, "coverage_pct": round(share * 100, 1),
                              "distance_m": distance, "rect": rect, "ground": bool(root.get("ground"))})
        visible.sort(key=lambda v: -v["coverage_pct"])
        own = {o.session_uid for o in mine}
        others = []  # the person's objects in view: only their share and count reach the model, never names
        for obj in scene.objects:
            if obj.session_uid in own or obj.type not in GEOMETRY or obj.hide_render:
                continue
            state, rect, _cut = self._rect(obj, depsgraph, scene, cam_eval, near)
            if state == "visible":
                others.append(rect)
        around = [self._hit(scene, depsgraph, origin, Vector(d)) for d in ENCLOSURE]
        view = {
            "frame": frame,
            "visible": _cap(visible, VIEW_MAX),
            "empty_pct": round(100.0 * _empty_share(rects), 1),
            "behind_camera": _cap(behind, VIEW_MAX),
            "outside_frame": _cap(outside, VIEW_MAX),
            "not_yours_cover_pct": round(100.0 * (1.0 - _empty_share(others)), 1),
            "not_yours_in_view": len(others),
            "camera_enclosed": all(h is not None and h[0] != "(not yours)" for h in around),
            "_close": close, "_seen": {v["name"] for v in visible},
        }
        target = self._target(cam)
        if target is not None:
            aim = target.evaluated_get(depsgraph).matrix_world.translation - origin
            hit = self._hit(scene, depsgraph, origin, aim.normalized(), aim.length) if aim.length > 1e-6 else None
            view["toward_target"] = {"first_hit": hit[0] if hit else None, "hit_distance": hit[1] if hit else None,
                                     "target_distance": round(aim.length, 2)}
        else:
            hit = self._hit(scene, depsgraph, origin, cam_eval.matrix_world.to_quaternion() @ Vector((0, 0, -1)))
            view["frame_centre"] = {"first_hit": hit[0], "distance": hit[1]} if hit else None
        return view

    def camera_path(self):
        """The scene camera's position at the first and the last frame, when it is the run's and its location is
        keyed; else ``[]``."""
        scene = self.scene
        cam = scene.camera
        if cam is None or not self._mine(cam):
            return []
        curves = {fc.array_index: fc for fc in compat.object_fcurves(cam) if fc.data_path == "location"}
        if not curves:
            return []
        return [tuple(float(curves[i].evaluate(frame)) if i in curves else float(cam.location[i]) for i in range(3))
                for frame in (scene.frame_start, scene.frame_end)]

    def camera_look_at(self):
        """The world location the scene camera tracks when it is the run's camera, or ``None``."""
        cam = self.scene.camera
        target = self._target(cam) if cam is not None and self._mine(cam) else None
        return tuple(target.matrix_world.translation) if target is not None else None
