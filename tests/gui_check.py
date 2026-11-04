"""Interactive check in a real Blender window, with no network. Opens Blender, runs, quits.

Run through scripts/gui-check.sh, which first builds the scene file in background mode:

    blender --background --factory-startup --python tests/gui_check.py -- <dir>
    blender --factory-startup --online-mode <dir>/gui_check.blend --python tests/gui_check.py -- <dir>
    blender --factory-startup --offline-mode <dir>/gui_check.blend --python tests/gui_check.py -- <dir>

Covers what background mode cannot: panels drawing in both editors, the asynchronous render job
and its handlers, the Image Editor, the sequencer, cancellation while the UI keeps ticking, and the
offline message. Results print as PASS/FAIL lines; screenshots go to the given folder.

The scenarios live in tests/gui_check/; this file picks one and runs it. A flow module of the bar
scenario that is not in this checkout is skipped and named at the end.
"""

import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.gui_check.args import BAR  # noqa: E402  (makes Skia importable first in the bar scenario)

import eachlabs  # noqa: E402
from tests.gui_check.common import (RESULTS, SKIPPED, build_scene, check, install_parking,  # noqa: E402
                                    panels_in_active_tabs, parked, setup, watch_ticks, window)


def run():
    install_parking()
    if BAR:
        from tests.gui_check.bar import scenario_bar

        steps = scenario_bar()
    else:
        from tests.gui_check.online import scenario_offline, scenario_online

        steps = scenario_online() if bpy.app.online_access else scenario_offline()

    def step():
        try:
            return next(steps)
        except StopIteration:
            finish()
        except Exception:
            traceback.print_exc()
            check("scenario ran to completion", False)
            finish()
        return None

    bpy.app.timers.register(step, first_interval=1.0)


def finish():
    failed = [name for name, ok in RESULTS if not ok]
    if SKIPPED:
        print("GUI skipped, not in this checkout: %s" % ", ".join(SKIPPED), flush=True)
    print("GUI %s: %d checks, %d failed%s" % (bpy.app.version_string, len(RESULTS), len(failed),
                                             (": " + ", ".join(failed)) if failed else ""), flush=True)
    eachlabs.unregister()

    def quit_blender():
        try:
            with parked(), bpy.context.temp_override(window=window()):
                bpy.ops.wm.quit_blender()
        finally:
            os._exit(1 if failed else 0)

    bpy.app.timers.register(quit_blender, first_interval=0.5)


if bpy.app.background:
    build_scene()
elif BAR:
    import addon_utils

    addon_utils.enable("eachlabs", default_set=True)  # enabled, so its preferences (the consent) exist
    bpy.app.timers.register(watch_ticks, persistent=True)
    run()
else:
    eachlabs.register()
    panels_in_active_tabs()
    setup()
    bpy.app.timers.register(watch_ticks, persistent=True)
    run()
