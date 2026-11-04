"""The scene a chat builds, and the three tools the model calls on it. Main thread only.

The model builds with ``run_python`` (``code_runner``). Every object a step creates is adopted into the run: it
carries ``eachlabs_run`` (the run) and ``eachlabs_id``, and lives in the run's collection. Objects are always
found again by those tags, never by a Python reference kept between calls, because undo and the person's edits
replace or delete datablocks. ``read_scene`` and ``camera_view`` only read the scene; ``camera_view`` changes the
current frame while it measures and puts it back.
"""

import re
import uuid

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from . import api_lookup, chat_loop, code_runner, compat, scene_tools, solids, startup_cube, textures
from .things import after_step as things_after, ids as thing_ids
from .scene.common import FLAT, GENERATED, GEOMETRY, _box, extent, is_root  # noqa: F401
from .checks.placement import PlacementChecks  # noqa: F401
from .checks.mesh_health import MeshHealth  # noqa: F401
from .checks.gaps import PartGaps  # noqa: F401
from .scene.camera_view import CameraView  # noqa: F401
from .checks.lights import ShadowLimit  # noqa: F401
from .scene.generated import GENERATED_KEPT_NOTE, GeneratedLooks, PLACEHOLDER  # noqa: F401
from .scene.report import SceneReport  # noqa: F401
from .scene.new_scene import blank_scene, cube_facts  # noqa: F401

COLLECTION = "Eachlabs scene"

RUN = "eachlabs_run"
ID = "eachlabs_id"


TOUCHED_NOTE = "Your step changed %d object%s you did not create; do not change them."


class SceneBuild(SceneReport, GeneratedLooks, ShadowLimit, CameraView, PartGaps, MeshHealth, PlacementChecks):
    def __init__(self, scene, run_id):
        self.run_id = str(run_id)
        self._scene_uid = scene.session_uid
        self._scene_name = scene.name
        self._ids = []  # creation order
        self._created = []  # the id of each object, in creation order
        self._tagged = set()  # session_uid of each datablock the add-on adopted or tagged; a step cannot write it
        self._changes = 0  # steps that changed the scene since the last end_stage
        self.pushes = 0  # undo steps end_stage pushed: the scene review undoes its fix only when it is the last
        self.prompts = []  # the prompts sent to this build, newest first
        self.code_runs = []  # {"prompt", "steps"} for each run of this build, oldest first, for Show code
        # Generated 3D objects by job id, oldest first: description, tier, status (pending | ready | failed), copies;
        # chat_run keeps it up to date and read_scene shows it as generated_3d.
        self.generated = {}
        # On a change, the names of the chat's objects from before it: a new thing that overlaps one of them is
        # listed in read_scene's overlaps. Set by chat_run when a run starts.
        self.existing = set()
        # session_uid of the person's objects the person selected and pointed at ("make this one red"): this run may
        # change them. Set by chat_run for one run.
        self.allowed = set()
        # A targeted edit ("make this red"), for one run: read_scene lists only the target objects (``focus``, by
        # session_uid; ``focus_names``, the target roots), and ``guard`` puts back the chat's other objects.
        self.focus = set()
        self.focus_names = []
        self.guard = None
        self.world_guard = None  # a follow-up not about the light: puts the world back after each step
        self.context_root = None  # a detail step's object or a one-target edit's: new loose objects join its thing
        # Generated textures by job id: the material, the description, the status (pending | ready | failed).
        self.textures = {}
        self.since = 0  # ``mark()`` when the current run started: read_scene checks the footing of what came after
        self.shadows_off = []  # lights whose shadow end_stage turned off to stay within SHADOW_LIGHTS_MAX
        self.closed_ends = []  # meshes whose small open ends end_stage closed
        self.textures_rescaled = []  # materials end_stage moved to world placement (texture_scale listed them)

    @classmethod
    def resume(cls, scene, file_runs=frozenset(), builds=()):
        """A build for the chat's work already in ``scene``, or ``None`` when there is none. ``file_runs``: the run
        tags the opened file had when it was loaded; ``builds``: this session's builds. Several builds in one scene
        become one, the largest."""
        sizes = {}
        for coll in scene.collection.children_recursive:
            if _trusted(coll, file_runs, builds):
                sizes[coll[RUN]] = sizes.get(coll[RUN], 0) + len(coll.all_objects)
        if not sizes:
            return None
        main = max(sorted(sizes), key=sizes.get)
        build = next((b for b in builds if b.run_id == main and b._scene_uid == scene.session_uid), None)
        build = build or cls(scene, main)
        build.take(scene, file_runs, builds)
        return build

    def take(self, scene, file_runs=frozenset(), builds=()):
        """Make the chat's other work in ``scene`` part of this build, under this build's tag.

        A tag in the opened file is trusted as it was loaded, since nothing records who wrote it; a tag written in
        this session counts only for what that build adopted or tagged, so a step cannot copy one onto the
        person's data."""
        builds = [b for b in builds if b is not self] + [self]
        present = {c.get(RUN) for c in scene.collection.children_recursive if _trusted(c, file_runs, builds)}

        def own(block):
            if block.get(RUN) not in present or not _trusted(block, file_runs, builds):
                return False
            if block.get(RUN) != self.run_id:
                block[RUN] = self.run_id
            self._tagged.add(block.session_uid)
            return True

        for coll in scene.collection.children_recursive:
            if not own(coll):
                continue
            for obj in coll.all_objects:
                oid = obj.get(ID)
                if isinstance(oid, str) and oid and own(obj) and oid not in self._ids:
                    self._ids.append(oid)
        for kind in code_runner.TAGGED_KINDS:
            for block in getattr(bpy.data, kind):
                own(block)

    # Lookups -------------------------------------------------------------------------------------

    @property
    def scene(self):
        for scene in bpy.data.scenes:
            if scene.session_uid == self._scene_uid:
                return scene
        scene = bpy.data.scenes.get(self._scene_name)
        if scene is None:
            raise RuntimeError("The scene this run builds in no longer exists.")
        return scene

    def _mine(self, idblock):
        # The tag alone is not enough: a step could copy it onto the person's data. Only datablocks the add-on
        # adopted or tagged in this session count, and a step cannot write to that set.
        return idblock is not None and idblock.get(RUN) == self.run_id and idblock.session_uid in self._tagged

    def _visible(self, obj):
        """The chat's own object, or one of the person's they selected for this run."""
        return self._mine(obj) or obj.session_uid in self.allowed

    def _groups(self):
        """``{id: [objects]}`` for this run, oldest first; a list longer than one holds copies."""
        groups = {}
        for obj in sorted(self.scene.objects, key=lambda o: o.session_uid):
            if self._mine(obj) and obj.get(ID) in self._ids:
                groups.setdefault(obj[ID], []).append(obj)
        return groups

    def _objects(self):
        """This run's objects, without copies the person made of them."""
        return [objs[0] for objs in self._groups().values()]

    def _find_collection(self):
        return next((c for c in bpy.data.collections if self._mine(c) and not c.get(thing_ids.THING)), None)

    def _collection(self):
        """The run's collection, made on first use. It is linked under the scene collection only when it
        is in none of the scene's collections, so a collection the person moved stays where they put it."""
        scene = self.scene
        coll = self._find_collection()
        if coll is None:
            coll = bpy.data.collections.new(COLLECTION)
            coll[RUN] = self.run_id
            self._tagged.add(coll.session_uid)
        if coll not in scene.collection.children_recursive:
            scene.collection.children.link(coll)
        return coll

    @property
    def collection_name(self):
        """The run's collection name, or ``None`` before the run made one. Never makes one."""
        coll = self._find_collection()
        return coll.name if coll is not None else None

    # Ownership -----------------------------------------------------------------------------------

    def _new_id(self):
        while True:
            oid = uuid.uuid4().hex[:8]
            if oid not in self._ids:
                self._ids.append(oid)
                return oid

    def adopt(self, obj):
        """Take an object made by run code into the run: fresh tags, and linked into the run's collection only.

        The tags are always replaced, because ``obj.copy()`` of a run object carries the original's id."""
        oid = self._new_id()
        obj[RUN], obj[ID] = self.run_id, oid
        self._tagged.add(obj.session_uid)
        coll = self._collection()
        if obj.name not in coll.objects:
            coll.objects.link(obj)
        for other in list(obj.users_collection):
            if other != coll:
                other.objects.unlink(obj)
        self._created.append(oid)
        return oid

    def tag(self, idblock):
        """Mark a datablock other than an object or a collection as made by this run."""
        idblock[RUN] = self.run_id
        self._tagged.add(idblock.session_uid)

    def owns(self, idblock):
        return self._mine(idblock)

    def busy_mode(self):
        """The mode an object of the scene is in when it is not Object Mode, else ``None``."""
        mode = next((o.mode for o in self.scene.objects if o.mode != "OBJECT"), None)
        if mode is None:
            return None
        return "edit" if mode.startswith("EDIT") else mode.lower().replace("_", " ")

    def leave_modes(self):
        """Put Blender back in Object Mode after a step's code left it in Edit, Sculpt or another mode. Every
        object was in Object Mode before the step (``busy_mode``), so the mode is the step's. Returns the mode it
        left, or ``None``. Plain ``bpy.ops`` on the main thread, never inside ``temp_override``, and with no undo
        step of its own: the stage's undo step stays the top one."""
        mode = self.busy_mode()
        if mode is None:
            return None
        layer = bpy.context.view_layer
        active = layer.objects.active
        if active is None or active.mode == "OBJECT":
            layer.objects.active = next(o for o in self.scene.objects if o.mode != "OBJECT")
        try:
            bpy.ops.object.mode_set("EXEC_DEFAULT", False, mode="OBJECT")
        except RuntimeError:  # the poll failed: the next step is refused and the model is told why
            pass
        return mode

    def drop_startup_cube(self):
        """Delete Blender's untouched startup Cube from this scene; returns whether it did. Called by the add-on when
        a new scene's stages start, never by the model's code. The delete joins the layout stage's undo step, so
        undoing that stage brings the Cube back. A Cube the person changed in any way is theirs and stays."""
        scene = self.scene
        cube = scene.objects.get("Cube")
        if cube is None or self._mine(cube) or not startup_cube.matches(cube_facts(cube, scene)):
            return False
        users = bpy.data.user_map(subset=[cube]).get(cube, set())
        if any(not isinstance(u, (bpy.types.Collection, bpy.types.Scene)) for u in users):
            return False  # something of the person's points at it (a camera's target): it is in use
        bpy.data.objects.remove(cube)
        self.note_change()
        return True

    def note_change(self):
        """Count a change, so ``end_stage`` makes its undo step."""
        self._changes += 1

    # Tools ---------------------------------------------------------------------------------------

    def execute(self, name, args, limit_s=None):
        """Apply one tool call and return a JSON-safe result; ``ToolArgError`` for bad arguments."""
        if name == "chat_context":  # for Code check, not a tool of the model
            return self.chat_context()
        args = scene_tools.validate(name, args)
        if name == "read_scene":
            return self.read_scene()
        if name == "camera_view":
            return self.camera_view()
        if name == "blender_api":
            return api_lookup.lookup(args["name"])
        world = self._scene_world()
        camera = self._camera_keys()
        looks = self._generated_looks()
        try:
            result = code_runner.run(args["code"], self, limit_s or code_runner.LIMIT_S)
        finally:  # also when the step stops the run
            self._keep_world(world)
            kept = self._keep_generated_looks(looks)
        notes = [result.pop("note")] if result.get("note") else []  # the edit guard's
        if kept:
            notes.append(GENERATED_KEPT_NOTE % (kept, "" if kept == 1 else "s"))
        touched = (result.get("summary") or {}).get("touched_other")
        if touched:
            notes.append(TOUCHED_NOTE % (touched, "" if touched == 1 else "s"))
        moved = self._keep_camera_move(camera)
        if moved:
            notes.append(moved)
        if notes:
            result["note"] = " ".join(notes)
        return result


    # Stages and the UI ---------------------------------------------------------------------------

    @staticmethod
    def undo_name(stage):
        return "Eachlabs: %s" % stage

    def end_stage(self, stage):
        """One undo step per stage that changed the scene; returns whether it did.

        ``undo_push`` crashes in background mode, so it is skipped there.
        """
        changed, self._changes = self._changes > 0, 0
        if changed and not self.focus:
            try:
                self.limit_shadows()
            except (RuntimeError, ReferenceError):  # a light removed while it was read; the next stage tries again
                pass
        if changed:
            try:  # small flat open ends (a tube end, a post top) the model left: closed here, bigger ones are reported
                made = set(self.created_since(self.since))
                self.closed_ends += solids.close_small_ends([o for o in self._objects() if o.name in made])
            except (RuntimeError, ReferenceError):
                pass
            try:  # orphans left become things of their own; every thing gets its collection
                things_after.end_of_stage(self, self._collection(), self.tag)
            except (RuntimeError, ReferenceError):
                pass
            try:  # patterns placed per object read stretched or blown up on big things: placed per metre here
                self.textures_rescaled += [n for n in textures.rescale_reported(self._objects(), self._mine)
                                           if n not in self.textures_rescaled]
            except (RuntimeError, ReferenceError):
                pass
        if changed and not bpy.app.background:
            bpy.ops.ed.undo_push(message=self.undo_name(stage))
            self.pushes += 1
        return changed

    @property
    def created_count(self):
        return len(self._created)

    def mark(self):
        return len(self._created)

    def created_since(self, mark):
        """Names of the objects created after ``mark`` that still exist, for highlighting."""
        names = {o.get(ID): o.name for o in self._objects()}
        return [names[key] for key in self._created[mark:] if key in names]

    def frame_targets(self):
        """The objects to frame: the run's geometry without the flat pieces (the ground), or the flat
        pieces when there is nothing else."""
        objects = [o for o in self._objects() if o.type in GEOMETRY]
        raised = [o for o in objects if o.dimensions.z >= FLAT * max(o.dimensions.x, o.dimensions.y)]
        return raised or objects


def _trusted(block, file_runs, builds):
    """Whether ``block``'s run tag is the chat's: from the opened file, or adopted by one of ``builds``."""
    run = block.get(RUN)
    if not isinstance(run, str) or not run:
        return False
    return run in file_runs or any(b.run_id == run and block.session_uid in b._tagged for b in builds)
