#!/usr/bin/env bash
# Download the Skia wheels, validate the manifest, build one zip per platform into dist/ and
# validate each zip. Usage: BLENDER=/path/to/blender scripts/build.sh
set -euo pipefail

BLENDER="${BLENDER:-blender}"
PYTHON="${PYTHON:-python3}"
SKIA_VERSION="144.1"
cd "$(dirname "$0")/.."

version=$(sed -n 's/^version = "\(.*\)"/\1/p' eachlabs/blender_manifest.toml)

# Wheels are not in git; fetch exactly the files the manifest lists (Blender 4.2: 3.11, 5.2: 3.13).
mkdir -p eachlabs/wheels
for platform in macosx_11_0_arm64 macosx_11_0_x86_64 win_amd64 manylinux_2_28_x86_64; do
    for py in 3.11 3.13; do
        tag="cp${py/./}"
        [ -f "eachlabs/wheels/skia_python-${SKIA_VERSION}-${tag}-${tag}-${platform}.whl" ] && continue
        "$PYTHON" -m pip download "skia-python==${SKIA_VERSION}" --no-deps --only-binary=:all: \
            --python-version "$py" --platform "$platform" -d eachlabs/wheels --quiet --disable-pip-version-check
    done
done

# Keep only the pinned files, then check each against its pinned sha256.
for path in eachlabs/wheels/*; do
    grep -q "  $(basename "$path")\$" scripts/skia-wheels.sha256 || rm -f "$path"
done
if command -v shasum >/dev/null; then sha=(shasum -a 256); else sha=(sha256sum); fi
(cd eachlabs/wheels && "${sha[@]}" -c --quiet ../../scripts/skia-wheels.sha256) || {
    echo "Skia wheel hash mismatch; delete eachlabs/wheels and build again" >&2
    exit 1
}

find eachlabs -name __pycache__ -prune -exec rm -rf {} +
"$BLENDER" --factory-startup --command extension validate eachlabs
mkdir -p dist
rm -f dist/eachlabs-"${version}"*.zip
"$BLENDER" --factory-startup --command extension build --source-dir eachlabs --output-dir dist --split-platforms
for zip in dist/eachlabs-"${version}"-*.zip; do
    "$BLENDER" --factory-startup --command extension validate "$zip"
    echo "$zip"
done
