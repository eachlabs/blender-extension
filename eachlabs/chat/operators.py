"""The chat's Blender operators: Send, Stop, Retry stage, Undo stage, New scene, Frame result, Show code, plan,
Play and its camera."""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from .. import chat_loop, confirm, main_thread, preferences
from .live import chat_run
from ..ui import tokens, tooltips
from . import object_jobs, plan_flow, playback, show_code, stage_log, undo_watch, viewport


def _undoable_stages():
    """Finished stages that changed the scene, oldest first; the last one is the next undo step."""
    return [s for s in chat_run.STATE.changed if chat_run.STATE.stages.get(s) == "done"]



class EACHLABS_OT_chat_send(bpy.types.Operator):
    bl_idname = "eachlabs.chat_send"
    bl_label = "Send"
    bl_description = "Build the described scene with the chat"

    prompt: StringProperty(name="Prompt")
    use_last: BoolProperty(name="Use last prompt", description="Send the last prompt again when Prompt is empty")
    asked: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})
    code_check: BoolProperty(name="Build with code check", default=True, options={"SKIP_SAVE"},
                             description=preferences.CODE_CHECK_TEXT)

    def invoke(self, context, event):
        """The sidebar's Build without the prompt bar asks before the first run, as the bar's card does."""
        if chat_run.STATE.running or preferences.code_allowed(context):
            return self.execute(context)
        self.asked = True
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        from .panels import _wrap

        layout = self.layout
        layout.label(text=tokens.CONSENT_TITLE)
        for line in tokens.CONSENT_BODY.split("\n"):
            _wrap(layout, context, line)
        if tokens.CODE_CHECK_AVAILABLE:
            layout.prop(self, "code_check")
            _wrap(layout, context, tokens.CONSENT_HINT)

    def execute(self, context):
        if chat_run.STATE.running:
            return {"CANCELLED"}  # Enter during a run sends nothing.
        if self.asked:
            preferences.allow_code(context, self.code_check and tokens.CODE_CHECK_AVAILABLE)
        prompt = self.prompt if self.prompt or not self.use_last else chat_run.STATE.prompt
        if not chat_run.start(context, prompt):
            if chat_run.STATE.error:  # no error: the bar's consent card opened instead
                self.report({"ERROR"}, chat_run.STATE.error)
            return {"CANCELLED"}
        return {"FINISHED"}



def paid_running():
    """True while the run has something being made on each::labs that Stop cannot take back: a 3D object or a
    texture whose job is not over, the concept picture, or a reference picture."""
    run = chat_run._run
    if run is None or not chat_run.STATE.running:
        return False
    return (any(job.active for job in object_jobs._jobs(run)) or chat_run.STATE.concept == "drawing"
            or any(entry["state"] == "drawing" for entry in run.references.values()))



class EACHLABS_OT_chat_cancel(bpy.types.Operator):
    bl_idname = "eachlabs.chat_cancel"
    bl_label = "Stop"
    bl_description = "Stop the chat; what was built is kept"

    def invoke(self, context, event):
        if not paid_running():
            return self.execute(context)
        return confirm.ask(self, context, event, *tokens.CONFIRM_STOP_PAID)

    def execute(self, context):
        chat_run.cancel()
        return {"FINISHED"}



class EACHLABS_OT_chat_retry_stage(bpy.types.Operator):
    bl_idname = "eachlabs.chat_retry_stage"
    bl_label = "Retry stage"
    bl_description = tooltips.TEXTS["retry"]  # the sidebar's buttons say what the bar's say

    @classmethod
    def poll(cls, context):
        if chat_run.STATE.running:
            return False
        if chat_run.STATE.failed_stage in chat_loop.ORDER and chat_run._build is not None:
            return True
        if chat_run.STATE.unchanged and chat_run.STATE.status == "done" and chat_run._build is not None:
            return True
        return bool(chat_run.STATE.attempt and chat_run.STATE.error)  # a refused start, or a run that broke off

    def execute(self, context):
        stage_log.retried(chat_run.log_folder(), chat_run.STATE.prompt, chat_run.STATE.failed_stage)
        if chat_run.STATE.unchanged and chat_run.STATE.status == "done" and chat_run._build is not None:
            started = chat_run.start(context, chat_run.STATE.prompt, stages=chat_loop.ORDER)  # every stage, into the same scene
        elif chat_run.STATE.failed_stage not in chat_loop.ORDER or chat_run._build is None:
            started = chat_run.start(context, chat_run.STATE.attempt)
        else:
            started = chat_run.start(context, chat_run.STATE.prompt,
                            stages=chat_loop.ORDER[chat_loop.ORDER.index(chat_run.STATE.failed_stage):])
        if not started:
            if chat_run.STATE.error:  # no error: the bar's consent card opened instead
                self.report({"ERROR"}, chat_run.STATE.error)
            return {"CANCELLED"}
        return {"FINISHED"}



class EACHLABS_OT_chat_undo_stage(bpy.types.Operator):
    bl_idname = "eachlabs.chat_undo_stage"
    bl_label = "Undo stage"
    bl_description = tooltips.TEXTS["undo"]

    @classmethod
    def poll(cls, context):
        return not chat_run.STATE.running and chat_run._build is not None and bool(undo_watch.undoable_stages())

    def invoke(self, context, event):
        stages = undo_watch.undoable_stages()
        title, message, button = tokens.CONFIRM_UNDO_STAGE
        return confirm.ask(self, context, event, title % (stages[-1] if stages else "last"), message, button)

    def execute(self, context):
        stages = undo_watch.undoable_stages(fresh=True)
        if not stages:
            chat_run.STATE.changed = []
            main_thread.tag_redraw()
            self.report({"ERROR"}, "The newest undo step is not the chat's. Use Edit > Undo History instead.")
            return {"CANCELLED"}
        stage = stages[-1]  # the active undo step
        chat_run._undo["own"] = True
        try:
            bpy.ops.ed.undo()
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            chat_run._undo["own"] = False
            undo_watch._settle()
        chat_run.STATE.changed.remove(stage)
        stage_log.undone(chat_run.log_folder(), chat_run.STATE.prompt, stage)
        chat_run.STATE.stages[stage] = "todo"
        chat_run.STATE.failed_stage = stage
        main_thread.tag_redraw()
        return {"FINISHED"}



class EACHLABS_OT_chat_new_scene(bpy.types.Operator):
    bl_idname = "eachlabs.chat_new_scene"
    bl_label = "New scene"
    bl_description = tooltips.TEXTS["new"]
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return not chat_run.STATE.running

    def invoke(self, context, event):
        return confirm.ask(self, context, event, *tokens.CONFIRM_NEW_SCENE)

    def execute(self, context):
        chat_run.new_scene(context)
        return {"FINISHED"}



class EACHLABS_OT_chat_frame_result(bpy.types.Operator):
    bl_idname = "eachlabs.chat_frame_result"
    bl_label = "Frame result"
    bl_description = tooltips.TEXTS["frame"]

    @classmethod
    def poll(cls, context):
        return chat_run._build is not None and viewport._view3d(context) is not None

    def execute(self, context):
        try:
            chat_run._build.scene
            found = [chat_run._build.scene.objects.get(n) for n in chat_run.STATE.found] if chat_run.STATE.status == "found" else []
            found = [o for o in found if o is not None]
            framed = viewport.frame_objects(found, viewport._view3d(context)) if found else viewport.frame_build(chat_run._build, viewport._view3d(context))
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not framed:
            self.report({"ERROR"}, "Nothing the chat built is in this view.")
            return {"CANCELLED"}
        return {"FINISHED"}



class EACHLABS_OT_chat_show_code(bpy.types.Operator):
    bl_idname = "eachlabs.chat_show_code"
    bl_label = "Show code"
    bl_description = tooltips.TEXTS["code"]

    @classmethod
    def poll(cls, context):
        return bool(chat_run.STATE.code_steps)

    def execute(self, context):
        try:
            _text, message = show_code.show_code(context)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if message:
            self.report({"INFO"}, message)
        return {"FINISHED"}



class EACHLABS_OT_chat_plan(bpy.types.Operator):
    bl_idname = "eachlabs.chat_plan"
    bl_label = "Build"
    bl_description = tooltips.TEXTS["plan_build"]

    answer: StringProperty(default="build", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        return tooltips.text("plan_" + properties.answer) or tooltips.TEXTS["plan_build"]

    @classmethod
    def poll(cls, context):
        return chat_run.STATE.plan_waiting

    def execute(self, context):
        return {"FINISHED"} if plan_flow.plan_answer("cancel" if self.answer == "cancel" else "build") else {"CANCELLED"}



class EACHLABS_OT_chat_plan_toggle(bpy.types.Operator):
    bl_idname = "eachlabs.chat_plan_toggle"
    bl_label = "Move between 3D and code"
    bl_description = tooltips.PLAN_ITEM

    index: IntProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return chat_run.STATE.plan_waiting

    def execute(self, context):
        return {"FINISHED"} if plan_flow.plan_toggle(self.index) else {"CANCELLED"}



class EACHLABS_OT_chat_play(bpy.types.Operator):
    bl_idname = "eachlabs.chat_play"
    bl_label = "Play"
    bl_description = tooltips.TEXTS["play"]

    camera: StringProperty(name="Camera name", description="The camera to look through; empty: the chosen one",
                           options={"SKIP_SAVE"})

    def execute(self, context):
        try:
            if playback.is_playing(context):
                playback.pause(context)
            else:
                playback.play(context, self.camera or playback.chosen(context.scene))
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}



_camera_items = []  # kept alive while Blender shows the enum's items


def _cameras(_self, context):
    _camera_items[:] = [(name, name, hint) for name, hint, _chosen in playback.menu(context.scene)]
    return _camera_items



class EACHLABS_OT_chat_play_camera(bpy.types.Operator):
    bl_idname = "eachlabs.chat_play_camera"
    bl_label = "Play through"
    bl_description = tooltips.TEXTS["play_menu"]
    bl_property = "camera"

    camera: EnumProperty(name="Play through", items=_cameras)

    def execute(self, context):
        if self.camera:
            chat_run.STATE.play_camera = self.camera
            main_thread.tag_redraw()
        return {"FINISHED"}



from . import final_render, make_video  # noqa: E402

CLASSES = (
    EACHLABS_OT_chat_send,
    EACHLABS_OT_chat_cancel,
    EACHLABS_OT_chat_retry_stage,
    EACHLABS_OT_chat_undo_stage,
    EACHLABS_OT_chat_new_scene,
    EACHLABS_OT_chat_frame_result,
    EACHLABS_OT_chat_play,
    EACHLABS_OT_chat_play_camera,
    EACHLABS_OT_chat_show_code,
    EACHLABS_OT_chat_plan,
    EACHLABS_OT_chat_plan_toggle,
) + final_render.CLASSES + make_video.CLASSES
