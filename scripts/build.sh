#!/usr/bin/env bash
# Validate the manifest, build dist/eachlabs-<version>.zip and validate the zip.
# Usage: BLENDER=/path/to/blender scripts/build.sh
set -euo pipefail

BLENDER="${BLENDER:-blender}"
cd "$(dirname "$0")/.."

version=$(sed -n 's/^version = "\(.*\)"/\1/p' eachlabs/blender_manifest.toml)
zip="dist/eachlabs-${version}.zip"

find eachlabs -name __pycache__ -prune -exec rm -rf {} +
"$BLENDER" --factory-startup --command extension validate eachlabs
mkdir -p dist
rm -f "$zip"
"$BLENDER" --factory-startup --command extension build --source-dir eachlabs --output-dir dist
"$BLENDER" --factory-startup --command extension validate "$zip"
echo "$zip"
