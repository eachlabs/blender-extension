"""The GUI check's command line (the output folder and the scenario), and Skia for the bar scenario."""

import os
import sys

from tests import blender_fakes

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGS[0] if ARGS else os.path.join(ROOT, ".gui-check")
BAR = ARGS[1:2] == ["bar"]  # the prompt bar scenario; Blender runs with --enable-event-simulate

SKIA_ERROR = blender_fakes.ensure_skia() if BAR else None

os.makedirs(OUT, exist_ok=True)
