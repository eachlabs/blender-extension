"""Blender smoke test: export, import, the full job pipeline and the scene chat, with no network.

    blender --background --factory-startup --python-exit-code 1 --python tests/smoke.py

The add-on is registered from this checkout. Network calls go to a fake client that serves local
files, so this exercises rendering, MP4 packaging, the worker thread, the main-thread dispatcher,
cancellation, re-run and sequencer timing without an API key.

The checks live in tests/smoke/, one module per domain; this file runs them in a fixed order. A module
that is not in this checkout is skipped and named at the end.
"""

import importlib
import os
import shutil
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.smoke.common import RESULTS, WORK, check  # noqa: E402  (makes Skia importable first)

import eachlabs  # noqa: E402

SKIPPED = []


def run(module, test, *args):
    """Run ``tests.smoke.<module>.<test>``; None when the module is not in this checkout."""
    name = "tests.smoke." + module
    try:
        found = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        if module not in SKIPPED:
            SKIPPED.append(module)
        return None
    return getattr(found, test)(*args)


def main():
    eachlabs.register()
    try:
        run("bar", "test_overlay")
        run("chat_run", "test_startup_cube")
        run("steps", "test_scene_tools")
        run("scene_report", "test_read_scene_groups")
        run("version_notes", "test_version_notes")
        run("scene_report", "test_camera_view_room")
        run("chat_run", "test_chat_run")
        run("chat_run", "test_chat_follow_up")
        run("objects_3d", "test_generated_objects")
        run("chat_run", "test_partly_done_stage")
        run("selection", "test_find_and_selection")
        run("chat_run", "test_earlier_work")
        run("selection", "test_tab_change")
        run("objects_3d", "test_placeholder_parts")
        run("selection", "test_targeted_edit")
        run("detail", "test_detail_stage")
        run("settings", "test_confirmations")
        run("pictures", "test_generated_textures")
        run("pictures", "test_concept_picture")
        run("pictures", "test_looks_need_build")
        run("objects_3d", "test_failed_note_paths")
        run("objects_3d", "test_generated_files")
        run("review", "test_visual_check")
        run("review", "test_scene_review")
        run("scene_report", "test_free_space")
        run("placement", "test_fix_round")
        run("placement", "test_resting_and_mesh_health")
        run("placement", "test_settle")
        run("report_checks", "test_correct_room")
        run("review", "test_candidates")
        run("report_checks", "test_emission")
        run("report_checks", "test_through_glass")
        run("steps", "test_helper_library")
        run("steps", "test_broken_mesh_steps")
        run("steps", "test_attach_parenting")
        run("scene_report", "test_solids")
        run("placement", "test_zones")
        run("placement", "test_placement")
        run("report_checks", "test_pierces")
        run("report_checks", "test_floats")
        run("report_checks", "test_texture_scale")
        run("report_checks", "test_look_checks")
        run("scene_report", "test_forest_copies")
        run("scene_report", "test_blend")
        run("things", "test_empty_group_edit")
        run("things", "test_resting_on_removed")
        run("bar", "test_marks_lifecycle")
        run("steps", "test_code_runner")
        run("steps", "test_world_kept")
        run("steps", "test_error_hints")
        run("things", "test_contents_on_holder")
        run("things", "test_replaced_parts")
        run("things", "test_things")
        run("settings", "test_hidden_settings")
        scene = run("export", "orbit_scene")
        still, frames, outputs = run("export", "test_export", scene)
        run("export", "test_import", scene, still, frames)
        run("thread_guard", "test_thread_guard", scene)
        run("export", "test_timing_content")
        run("shims", "test_scene_shims")
        run("settings", "test_chat_settings")
        run("settings", "test_code_check")
        run("next_steps", "test_next_steps")
        run("export", "test_offline")
        run("export", "test_pipeline", scene, still, run("export", "out_clip", frames))
        run("export", "test_audio")
        run("export", "test_reference_flow", scene)
        run("steps", "test_asked_colour")
        run("play", "test_final_render")
        run("play", "test_play_through_camera")
        # Last: the step's own mode change is an undo step later undos would reach.
        run("steps", "test_step_left_in_edit_mode")
    except Exception:
        traceback.print_exc()
        check("smoke test ran to completion", False)
    finally:
        eachlabs.unregister()
    failed = [name for name, ok, _ in RESULTS if not ok]
    if SKIPPED:
        print("\nskipped, not in this checkout: %s" % ", ".join(SKIPPED))
    print("\n%d checks, %d failed%s" % (len(RESULTS), len(failed), (": " + ", ".join(failed)) if failed else ""))
    print("Blender %s, work dir %s" % (bpy.app.version_string, WORK))
    if failed:
        sys.exit(1)
    shutil.rmtree(WORK, ignore_errors=True)


main()
