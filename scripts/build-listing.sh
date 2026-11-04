#!/usr/bin/env bash
# Write the extensions repository listing for the built zips: <dir>/index.json, index.html and one zip
# per platform. Upload the zips and index.json to the GitHub release; Blender reads
# releases/latest/download/index.json, and its relative archive URLs point at the same release's zips,
# so <dir> holds this version only.
# Usage: BLENDER=/path/to/blender scripts/build-listing.sh <dir>
set -euo pipefail

BLENDER="${BLENDER:-blender}"
cd "$(dirname "$0")/.."
dir=${1:?usage: scripts/build-listing.sh <dir>}
version=$(sed -n 's/^version = "\(.*\)"/\1/p' eachlabs/blender_manifest.toml)
if [ -e "$dir" ] && [ -n "$(ls -A "$dir")" ]; then
    echo "$dir is not empty; the listing must hold only eachlabs-$version"
    exit 1
fi
mkdir -p "$dir"
cp dist/eachlabs-"$version"-*.zip "$dir/"
"$BLENDER" --command extension server-generate --repo-dir="$dir" --html
echo "listed $(cd "$dir" && ls eachlabs-*.zip | tr '\n' ' ')in $dir/index.json"
