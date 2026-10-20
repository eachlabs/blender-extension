#!/usr/bin/env bash
# Screenshots for the public tutorial: the built zip, served from a local static repository, in a
# throwaway profile and a real Blender window. With EACHLABS_KEY_FILE (a chmod 600 file holding a key)
# the panels show a configured state; the key stays inside Blender. No predictions are made unless
# EACHLABS_TUTORIAL_PAID is set (PAID: one image and one video, about $0.86, receipt in the output
# folder); EACHLABS_TUTORIAL_REHEARSE runs the same steps with local answers, at no cost.
# Usage: BLENDER=/path/to/blender [EACHLABS_KEY_FILE=path] scripts/tutorial-shots.sh [output dir]
set -euo pipefail

BLENDER="${BLENDER:-blender}"
cd "$(dirname "$0")/.."
out="${1:-$(mktemp -d "${TMPDIR:-/tmp}/eachlabs-tutorial.XXXXXX")}"
zip=$(ls -t dist/eachlabs-*.zip | head -1)
mkdir -p "$out/repo"
cp "$zip" "$out/repo/"

profile=$(mktemp -d "${TMPDIR:-/tmp}/eachlabs-tutorial-profile.XXXXXX")
trap 'rm -rf "$profile"' EXIT
export BLENDER_USER_RESOURCES="$profile"

# perl's alarm stands in for coreutils timeout, which macOS lacks.
run() { perl -e 'alarm shift; exec @ARGV' "${TIMEOUT:-300}" "$BLENDER" "$@"; }
gui() { run --enable-event-simulate --online-mode --window-geometry 0 0 1600 1100 "$out/tutorial.blend" \
    --python scripts/tutorial_shots.py -- "$out" "$1" >"$out/$1.log" 2>&1; }

run --command extension server-generate --repo-dir="$out/repo" >"$out/setup.log" 2>&1
run --background --python-expr "import bpy; bpy.context.preferences.view.show_splash = False; bpy.ops.wm.save_userpref()" \
    >>"$out/setup.log" 2>&1
run --command extension repo-add --name Eachlabs --url "file://$out/repo/index.json" eachlabs >>"$out/setup.log" 2>&1
run --online-mode --command extension sync >>"$out/setup.log" 2>&1
run --background --factory-startup --python scripts/tutorial_shots.py -- "$out" scene >"$out/scene.log" 2>&1
gui listing
run --online-mode --command extension install eachlabs --enable >>"$out/setup.log" 2>&1
gui panels
if [ -n "${EACHLABS_TUTORIAL_PAID:-}${EACHLABS_TUTORIAL_REHEARSE:-}" ]; then TIMEOUT=2700 gui results; fi
run --background --factory-startup --python scripts/tutorial_shots.py -- "$out" crop >"$out/crop.log" 2>&1

status=0
grep -h -E "^(SHOT|TAB|SIDEBAR|CATALOG|IMAGE|VIDEO|JOB|BUDGET)" "$out"/listing.log "$out"/panels.log "$out"/results.log "$out"/crop.log 2>/dev/null || true
if grep -l "Traceback" "$out"/*.log; then
    grep -h -B2 -A12 "Traceback" "$out"/*.log
    status=1
fi
echo "images: $out"
exit $status
