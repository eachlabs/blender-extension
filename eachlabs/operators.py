"""Thin operators: check context, call ``pipeline`` or ``catalog``, report the outcome."""

import os
import threading

import bpy
from bpy.props import EnumProperty, StringProperty

from . import api_client, capabilities as caps, catalog, compat, main_thread, naming, pipeline, preferences


class EACHLABS_OT_refresh_catalog(bpy.types.Operator):
    bl_idname = "eachlabs.refresh_catalog"
    bl_label = "Refresh models"
    bl_description = "Load Eachlabs models and your workflows"

    def execute(self, context):
        problem = compat.online_problem()
        if problem:
            self.report({"ERROR"}, problem)
            return {"CANCELLED"}
        try:
            catalog.refresh(context)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class EACHLABS_OT_test_connection(bpy.types.Operator):
    bl_idname = "eachlabs.test_connection"
    bl_label = "Test connection"
    bl_description = "Check the API key by reading your Eachlabs balance"

    def execute(self, context):
        status = preferences.connection_status
        problem = compat.online_problem()
        if problem:
            status.update(text=problem, ok=False)
            self.report({"ERROR"}, problem)
            return {"CANCELLED"}
        try:
            client = preferences.client(context)
        except ValueError as exc:
            status.update(text=str(exc), ok=False)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not client.api_key:
            status.update(text="Enter an API key first.", ok=False)
            return {"CANCELLED"}
        status.update(text="Checking…", ok=None)

        def work():
            try:
                balance = client.get_balance().get("balance_usd")
                text = "Connected. Balance $%.2f" % balance if isinstance(balance, (int, float)) else "Connected."
                result = (text, True)
            except api_client.ApiError as exc:
                result = (exc.message, False)
            main_thread.call_soon(lambda: status.update(text=result[0], ok=result[1]))

        threading.Thread(target=work, name="eachlabs-test", daemon=True).start()
        main_thread.start()
        return {"FINISHED"}


class _Generate:
    def _finish(self, error, started):
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        self.report({"INFO"}, started)
        return {"FINISHED"}


class EACHLABS_OT_generate_image(_Generate, bpy.types.Operator):
    bl_idname = "eachlabs.generate_image"
    bl_label = "Generate Image"
    bl_description = "Render the current frame (or snapshot the viewport) and send it to the selected target"

    def execute(self, context):
        return self._finish(pipeline.start_image(context), "Eachlabs: rendering the frame")


class EACHLABS_OT_generate_video(_Generate, bpy.types.Operator):
    bl_idname = "eachlabs.generate_video"
    bl_label = "Generate Video"
    bl_description = "Render the frame range and send the clip or its first and last frames to the selected target"

    def execute(self, context):
        return self._finish(pipeline.start_video(context), "Eachlabs: rendering the frame range")


class EACHLABS_OT_rerun(_Generate, bpy.types.Operator):
    bl_idname = "eachlabs.rerun"
    bl_label = "Re-run"
    bl_description = "Send the last rendered inputs again with the current target, prompt, seed and parameters"

    action: EnumProperty(items=[(caps.IMAGE, "Image", ""), (caps.VIDEO, "Video", "")])

    def execute(self, context):
        return self._finish(pipeline.rerun(context, self.action), "Eachlabs: re-running without rendering")


class EACHLABS_OT_use_default_video(bpy.types.Operator):
    bl_idname = "eachlabs.use_default_video"
    bl_label = "Use default video model"
    bl_description = "Select the default video model with its inputs and parameters (set in the add-on preferences)"

    def execute(self, context):
        message = pipeline.apply_default_video(context, force=True)
        if message:
            self.report({"WARNING"}, message)
        return {"FINISHED"}


class EACHLABS_OT_export_movie(_Generate, bpy.types.Operator):
    bl_idname = "eachlabs.export_movie"
    bl_label = "Export movie"
    bl_description = "Render the sequencer, with sound, to one MP4 next to the .blend file"

    def execute(self, context):
        return self._finish(pipeline.export_movie(context), "Eachlabs: exporting the sequencer")


class EACHLABS_OT_open_file(bpy.types.Operator):
    bl_idname = "eachlabs.open_file"
    bl_label = "Open"
    bl_description = "Open this file in the system's default app"

    filepath: StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        if not os.path.isfile(self.filepath):
            self.report({"ERROR"}, "File not found: %s" % self.filepath)
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=self.filepath)
        return {"FINISHED"}


class EACHLABS_OT_cancel_job(bpy.types.Operator):
    bl_idname = "eachlabs.cancel_job"
    bl_label = "Cancel"
    bl_description = "Stop this job"

    job_id: StringProperty()

    def execute(self, context):
        pipeline.cancel(self.job_id)
        main_thread.tag_redraw()
        return {"FINISHED"}


class EACHLABS_OT_clear_jobs(bpy.types.Operator):
    bl_idname = "eachlabs.clear_jobs"
    bl_label = "Clear finished"
    bl_description = "Remove finished jobs from the list"

    def execute(self, context):
        pipeline.REGISTRY.clear_finished()
        return {"FINISHED"}


class EACHLABS_OT_open_folder(bpy.types.Operator):
    bl_idname = "eachlabs.open_folder"
    bl_label = "Open folder"
    bl_description = "Open the folder holding renders and results for this file"

    def execute(self, context):
        folder = naming.output_dir(bpy.data.filepath)
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {"FINISHED"}


class EACHLABS_OT_open_preferences(bpy.types.Operator):
    bl_idname = "eachlabs.open_preferences"
    bl_label = "Open preferences"
    bl_description = "Show the Eachlabs add-on preferences"

    section: StringProperty(default="ADDON")

    def execute(self, context):
        if self.section == "SYSTEM":
            bpy.ops.screen.userpref_show(section="SYSTEM")
        else:
            bpy.ops.preferences.addon_show(module=__package__)
        return {"FINISHED"}


CLASSES = (
    EACHLABS_OT_refresh_catalog,
    EACHLABS_OT_test_connection,
    EACHLABS_OT_generate_image,
    EACHLABS_OT_generate_video,
    EACHLABS_OT_rerun,
    EACHLABS_OT_use_default_video,
    EACHLABS_OT_export_movie,
    EACHLABS_OT_open_file,
    EACHLABS_OT_cancel_job,
    EACHLABS_OT_clear_jobs,
    EACHLABS_OT_open_folder,
    EACHLABS_OT_open_preferences,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
