#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is missing. Please install python3." >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"

export PYTHONUNBUFFERED=1

# Prefer vendor binary for source runs without a system-wide installation
if [ -f "$ROOT_DIR/vendor/gpu-screen-recorder" ]; then
  export PATH="$ROOT_DIR/vendor:$PATH"
elif ! command -v gpu-screen-recorder >/dev/null 2>&1; then
  echo "WARNING: gpu-screen-recorder not found." >&2
  echo "For source runs: place the binary at ./vendor/gpu-screen-recorder or install it system-wide." >&2
fi

# Force X11 mode on Wayland so the window position can be tracked for pixel-accurate capture
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ] && [ -z "${QT_QPA_PLATFORM:-}" ]; then
  export QT_QPA_PLATFORM=xcb
fi

exec "$VENV_DIR/bin/python" -m dumb_recorder "$@"
