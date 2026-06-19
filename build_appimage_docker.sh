#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="dumb-recorder-appimage-builder"
USER_ID="$(id -u)"
GROUP_ID="$(id -g)"

docker build -f "$ROOT_DIR/Dockerfile.appimage" -t "$IMAGE_NAME" "$ROOT_DIR"

# Clean possible rootless-Docker/nobody-owned leftovers from older builds from inside the container namespace.
if [ -d "$ROOT_DIR/build/AppDir" ]; then
  docker run --rm \
    -v "$ROOT_DIR:/src" \
    -w /src \
    "$IMAGE_NAME" \
    sh -c 'rm -rf build/AppDir'
fi

docker run --rm \
  -e APPIMAGE_EXTRACT_AND_RUN=1 \
  -e HOME=/tmp \
  --user "$USER_ID:$GROUP_ID" \
  -v "$ROOT_DIR:/src" \
  -w /src \
  "$IMAGE_NAME"
