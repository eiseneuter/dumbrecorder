#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"
TOOLS_DIR="$ROOT_DIR/tools"
APPDIR="$BUILD_DIR/AppDir"
VENV_DIR="$APPDIR/usr/venv"
APPIMAGE_TOOL="$TOOLS_DIR/appimagetool-x86_64.AppImage"
APPSTREAM_FILE="$ROOT_DIR/io.github.eisen.DumbRecorder.metainfo.xml"

if [ -d "$APPDIR" ] && ! rm -rf "$APPDIR"; then
  echo "ERROR: Could not remove existing AppDir." >&2
  echo "It may have been created by Docker with a different owner." >&2
  echo "Fix it with: sudo chown -R \"$USER:$USER\" \"$APPDIR\" && rm -rf \"$APPDIR\"" >&2
  exit 1
fi
mkdir -p "$BUILD_DIR" "$DIST_DIR" "$TOOLS_DIR"
mkdir -p \
  "$APPDIR/usr/bin" \
  "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
  "$APPDIR/usr/share/metainfo"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"

cp -r "$ROOT_DIR/dumb_recorder" "$APPDIR/usr/bin/dumb_recorder"
cp "$ROOT_DIR/dumbrecordericon.png" "$APPDIR/usr/bin/dumbrecordericon.png"
cp "$ROOT_DIR/dumbrecordericon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/dumbrecordericon.png"
cp "$ROOT_DIR/dumb-recorder.desktop" "$APPDIR/dumb-recorder.desktop"
cp "$ROOT_DIR/dumb-recorder.desktop" "$APPDIR/usr/share/applications/dumb-recorder.desktop"
if [ -f "$APPSTREAM_FILE" ]; then
  cp "$APPSTREAM_FILE" "$APPDIR/usr/share/metainfo/io.github.eisen.DumbRecorder.metainfo.xml"
  # Older appimagetool builds look for metadata matching the desktop-file basename.
  cp "$APPSTREAM_FILE" "$APPDIR/usr/share/metainfo/dumb-recorder.appdata.xml"
fi

GSR_BIN="$APPDIR/usr/bin/gpu-screen-recorder"
ARCH=$(uname -m)
echo "Fetching gpu-screen-recorder from GitHub Releases..."
GSR_VERSION=$(curl -sf "https://api.github.com/repos/dec05eba/gpu-screen-recorder/releases/latest" \
  | grep '"tag_name"' | cut -d'"' -f4 || true)

if [ -n "$GSR_VERSION" ]; then
  curl -Lf "https://github.com/dec05eba/gpu-screen-recorder/releases/download/${GSR_VERSION}/gpu-screen-recorder-${ARCH}" \
    -o "$GSR_BIN" \
    && chmod +x "$GSR_BIN" \
    && echo "Downloaded: gpu-screen-recorder ${GSR_VERSION}" \
    || { echo "Download failed, trying fallback..."; rm -f "$GSR_BIN"; }
fi

if [ ! -x "$GSR_BIN" ]; then
  if command -v gpu-screen-recorder >/dev/null 2>&1; then
    echo "Fallback: copying system installation from $(command -v gpu-screen-recorder)"
    cp "$(command -v gpu-screen-recorder)" "$GSR_BIN"
  else
    echo "WARNING: gpu-screen-recorder was not bundled." >&2
    echo "The AppImage will use gpu-screen-recorder from the host PATH at runtime." >&2
  fi
fi

if command -v ffmpeg >/dev/null 2>&1; then
  cp "$(command -v ffmpeg)" "$APPDIR/usr/bin/ffmpeg"
fi

cat > "$APPDIR/usr/bin/dumb-recorder" <<'APP_EOF'
#!/usr/bin/env bash
APPDIR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="$APPDIR_ROOT/usr/bin:$PATH"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$APPDIR_ROOT/usr/bin"

# On Wayland: use KMS/X11 mode only when gsr-kms-server is available in the system PATH
# (it needs cap_sys_admin set by the package manager and cannot be bundled in an AppImage).
# Without it, fall through to portal mode automatically.
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ] && [ -z "${QT_QPA_PLATFORM:-}" ]; then
  if command -v gsr-kms-server >/dev/null 2>&1; then
    export QT_QPA_PLATFORM=xcb
  fi
fi

cd "$APPDIR_ROOT/usr/bin"
exec "$APPDIR_ROOT/usr/venv/bin/python" -m dumb_recorder "$@"
APP_EOF
chmod +x "$APPDIR/usr/bin/dumb-recorder"

cat > "$APPDIR/AppRun" <<'APPRUN_EOF'
#!/usr/bin/env bash
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/usr/bin/dumb-recorder" "$@"
APPRUN_EOF
chmod +x "$APPDIR/AppRun"

ln -s usr/share/icons/hicolor/256x256/apps/dumbrecordericon.png "$APPDIR/dumbrecordericon.png"

if [ ! -x "$APPIMAGE_TOOL" ]; then
  echo "appimagetool-x86_64.AppImage not found in project directory. Trying to download it..."
  curl -Lf "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
    -o "$APPIMAGE_TOOL" \
    && chmod +x "$APPIMAGE_TOOL" \
    || true
fi

if [ ! -x "$APPIMAGE_TOOL" ]; then
  echo "Could not download appimagetool-x86_64.AppImage." >&2
  echo "Download it from https://github.com/AppImage/AppImageKit/releases and place it here, or install appimagetool system-wide." >&2
  if command -v appimagetool >/dev/null 2>&1; then
    appimagetool "$APPDIR" "$DIST_DIR/Dumb_Recorder-x86_64.AppImage"
    exit 0
  fi
  exit 1
fi

APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGE_TOOL" "$APPDIR" "$DIST_DIR/Dumb_Recorder-x86_64.AppImage"
