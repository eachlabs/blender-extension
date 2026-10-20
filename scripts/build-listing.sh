#!/usr/bin/env bash
# Write the extensions repository listing for the built zip: <dir>/index.json, index.html and the zip.
# Upload the zip and index.json to the GitHub release; Blender reads releases/latest/download/index.json,
# and its relative archive URL points at the same release's zip, so <dir> holds this version only.
# Usage: BLENDER=/path/to/blender scripts/build-listing.sh <dir>
set -euo pipefail

BLENDER="${BLENDER:-blender}"
cd "$(dirname "$0")/.."
dir=${1:?usage: scripts/build-listing.sh <dir>}
zip=$(ls -t dist/eachlabs-*.zip | head -1)
if [ -e "$dir" ] && [ -n "$(ls -A "$dir")" ]; then
    echo "$dir is not empty; the listing must hold only $(basename "$zip")"
    exit 1
fi
mkdir -p "$dir"
cp "$zip" "$dir/"
"$BLENDER" --command extension server-generate --repo-dir="$dir" --html
echo "listed $(basename "$zip") in $dir/index.json"
