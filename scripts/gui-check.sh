#!/usr/bin/env bash
# Run tests/gui_check.py in a real Blender window, online and offline. Opens and closes Blender
# three times (online, offline, prompt bar); no network calls are made. Screenshots and logs go to the output folder.
# Usage: BLENDER=/path/to/blender [GUI_MODES="bar"] scripts/gui-check.sh [output dir]
set -euo pipefail

BLENDER="${BLENDER:-blender}"
cd "$(dirname "$0")/.."
out="${1:-$(mktemp -d "${TMPDIR:-/tmp}/eachlabs-gui.XXXXXX")}"
mkdir -p "$out"

# A throwaway profile keeps the user's Blender preferences untouched; saved preferences with the
# splash off keep first-run screens out of the screenshots.
profile=$(mktemp -d "${TMPDIR:-/tmp}/eachlabs-gui-profile.XXXXXX")
trap 'rm -rf "$profile"' EXIT
export BLENDER_USER_RESOURCES="$profile"

# perl's alarm stands in for coreutils timeout, which macOS lacks.
run() { perl -e 'alarm shift; exec @ARGV' 300 "$BLENDER" "$@"; }

run --background --python-expr "import bpy; bpy.context.preferences.view.show_splash = False; bpy.ops.wm.save_userpref()" \
    >"$out/profile.log" 2>&1
run --background --factory-startup --python tests/gui_check.py -- "$out" >"$out/build.log" 2>&1
status=0
# "bar" drives the prompt bar with simulated clicks and keys; real input is ignored meanwhile.
for mode in ${GUI_MODES:-online offline bar}; do
    mkdir -p "$out/$mode"
    cp "$out/gui_check.blend" "$out/$mode/gui_check.blend"
    case $mode in
        bar) flags=(--online-mode --enable-event-simulate) ;;
        *) flags=("--$mode-mode") ;;
    esac
    run "${flags[@]}" "$out/$mode/gui_check.blend" --python tests/gui_check.py -- "$out/$mode" "$mode" \
        >"$out/$mode/console.log" 2>&1 || status=1
    grep -E "^(PASS|FAIL|GUI)" "$out/$mode/console.log" || status=1
    # The bar scenario's forced draw error prints EACHLABS-FORCED-DRAW-FAILURE, never a traceback,
    # so any traceback fails the check.
    if grep -q "Traceback" "$out/$mode/console.log"; then
        grep -B2 -A12 "Traceback" "$out/$mode/console.log"
        status=1
    fi
done
echo "screenshots: $out/online $out/offline $out/bar"
exit $status
