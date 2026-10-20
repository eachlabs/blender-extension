#!/usr/bin/env bash
# Add the built zip to a static extensions repository and regenerate its listing (index.json and
# index.html). <site> is the folder GitHub Pages serves; older zips in it stay listed.
# Usage: BLENDER=/path/to/blender scripts/build-listing.sh <site>
set -euo pipefail

BLENDER="${BLENDER:-blender}"
cd "$(dirname "$0")/.."
site=${1:?usage: scripts/build-listing.sh <site>}
zip=$(ls -t dist/eachlabs-*.zip | head -1)
mkdir -p "$site"
cp "$zip" "$site/"
"$BLENDER" --command extension server-generate --repo-dir="$site" --html
echo "listed $(basename "$zip") in $site/index.json"
