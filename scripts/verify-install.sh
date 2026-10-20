#!/usr/bin/env bash
# Install the built zip into a fresh, throwaway Blender profile and check that it enables, registers
# its UI and reloads cleanly, with no Python errors on the console.
# Usage: BLENDER=/path/to/blender scripts/verify-install.sh [dist/eachlabs-<version>.zip]
set -euo pipefail

BLENDER="${BLENDER:-blender}"
cd "$(dirname "$0")/.."
zip="${1:-$(ls -t dist/eachlabs-*.zip | head -1)}"

profile=$(mktemp -d "${TMPDIR:-/tmp}/eachlabs-profile.XXXXXX")
log="$profile/console.log"
trap 'rm -rf "$profile"' EXIT
export BLENDER_USER_RESOURCES="$profile"

"$BLENDER" --command extension install-file --repo user_default --enable "$zip" >"$log" 2>&1

"$BLENDER" --background --python-exit-code 1 --python-expr '
import addon_utils, bpy, sys
module = "bl_ext.user_default.eachlabs"
enabled = module in bpy.context.preferences.addons
panels = [name for name in dir(bpy.types) if name.startswith("EACHLABS_PT_")]
operators = [op for op in dir(bpy.ops.eachlabs)]
prefs = bpy.context.preferences.addons[module].preferences if enabled else None
print("enabled", enabled, "panels", len(panels), "operators", len(operators), "prefs", type(prefs).__name__)
addon_utils.disable(module)
addon_utils.enable(module, default_set=True)
ok = enabled and len(panels) == 8 and {"generate_image", "generate_video", "rerun", "cancel_job"} <= set(operators)
sys.exit(0 if ok else 1)
' >>"$log" 2>&1 || { cat "$log"; echo "FAIL: add-on did not install and register cleanly"; exit 1; }

if grep -E "Traceback|Error|Exception" "$log" | grep -v "^enabled"; then
    cat "$log"
    echo "FAIL: console errors during install or registration"
    exit 1
fi
grep "^enabled" "$log"
echo "OK: $zip installs and registers cleanly in a fresh profile ($("$BLENDER" --version | head -1))"
