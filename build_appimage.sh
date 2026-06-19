#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"
TOOLS_DIR="$ROOT_DIR/tools"
APPDIR="$BUILD_DIR/AppDir"
PYTHON_DIR="$APPDIR/usr/python"
APPIMAGE_TOOL="$TOOLS_DIR/appimagetool-x86_64.AppImage"
APPSTREAM_FILE="$ROOT_DIR/io.github.eisen.DumbRecorder.metainfo.xml"

# Portable CPython (python-build-standalone) gives the AppImage its own
# self-contained interpreter + site-packages, so it never depends on the host
# Python version. A venv that symlinks the system interpreter is NOT portable
# across Python versions and breaks in clean environments (e.g. AppImageHub CI).
PYTHON_BUILD_STANDALONE_REPO="astral-sh/python-build-standalone"
PYTHON_VERSION="3.12"

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

ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  PY_ARCH="x86_64-unknown-linux-gnu" ;;
  aarch64) PY_ARCH="aarch64-unknown-linux-gnu" ;;
  *) echo "ERROR: unsupported architecture $ARCH" >&2; exit 1 ;;
esac

echo "Fetching latest python-build-standalone release (Python ${PYTHON_VERSION}, ${PY_ARCH})..."
# python-build-standalone is pre-release-only, so /releases/latest is empty;
# use the releases list and pick the newest tag. -L follows the repo redirect.
PBS_TAG=$(curl -sL "https://api.github.com/repos/${PYTHON_BUILD_STANDALONE_REPO}/releases?per_page=1" \
  | grep '"tag_name"' | head -1 | cut -d'"' -f4 || true)

if [ -z "$PBS_TAG" ]; then
  echo "ERROR: could not determine latest python-build-standalone release." >&2
  exit 1
fi
echo "Latest release tag: ${PBS_TAG}"

# Find the install_only asset matching our Python version and arch.
PBS_ASSET=$(curl -sL "https://api.github.com/repos/${PYTHON_BUILD_STANDALONE_REPO}/releases/tags/${PBS_TAG}" \
  | grep '"browser_download_url"' \
  | grep -o "https://[^\"]*cpython-${PYTHON_VERSION}\.[^\"]*${PY_ARCH}-install_only\.tar\.gz" \
  | sort -V | tail -1 || true)

if [ -z "$PBS_ASSET" ]; then
  echo "ERROR: no python-build-standalone install_only asset found for Python ${PYTHON_VERSION} ${PY_ARCH} in tag ${PBS_TAG}." >&2
  exit 1
fi

echo "Downloading: $PBS_ASSET"
PBS_TARBALL="$BUILD_DIR/cpython-install_only.tar.gz"
curl -Lf "$PBS_ASSET" -o "$PBS_TARBALL"

echo "Extracting portable CPython into AppDir..."
rm -rf "$PYTHON_DIR"
mkdir -p "$PYTHON_DIR"
tar -xzf "$PBS_TARBALL" -C "$PYTHON_DIR" --strip-components=1
rm -f "$PBS_TARBALL"

PY_BIN="$PYTHON_DIR/bin/python3"
if [ ! -x "$PY_BIN" ]; then
  echo "ERROR: portable python not found at $PY_BIN after extraction." >&2
  exit 1
fi

echo "Portable Python: $("$PY_BIN" --version)"

# Bootstrap pip inside the portable interpreter, then install requirements.
"$PY_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$PY_BIN" -m pip install --upgrade pip
"$PY_BIN" -m pip install -r "$ROOT_DIR/requirements.txt"

# Sanity: PySide6 must actually be importable inside the bundled interpreter.
if ! "$PY_BIN" -c "import PySide6" >/dev/null 2>&1; then
  echo "ERROR: PySide6 is not importable in the bundled Python. Aborting." >&2
  exit 1
fi
echo "PySide6 OK in bundled Python."

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

# Bundle the Qt xcb platform plugin's runtime dependencies so the AppImage can
# initialize a GUI even on bare/minimal hosts (e.g. AppImageHub CI sandboxes)
# that lack libxkbcommon-x11 / libxcb-cursor. These are copied from the build
# environment (Docker image installs libxkbcommon-x11-0 and libxcb-cursor0).
mkdir -p "$APPDIR/usr/lib"
copy_lib() {
  local lib="$1"
  local found
  found="$(find /usr/lib -name "${lib}*" 2>/dev/null | head -1 || true)"
  if [ -n "$found" ]; then
    cp -L $found "$APPDIR/usr/lib/"
    echo "Bundled: $(basename "$found")"
  else
    echo "WARNING: ${lib} not found in build environment; not bundled." >&2
  fi
}
copy_lib "libxkbcommon-x11.so.0"
copy_lib "libxcb-cursor.so.0"
# libxkbcommon-x11 depends on libxkbcommon.so.0; bundle it too if present.
copy_lib "libxkbcommon.so.0"

cat > "$APPDIR/usr/bin/dumb-recorder" <<'APP_EOF'
#!/usr/bin/env bash
APPDIR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="$APPDIR_ROOT/usr/bin:$PATH"
export PYTHONNOUSERSITE=1
export PYTHONHOME="$APPDIR_ROOT/usr/python"
export PYTHONPATH="$APPDIR_ROOT/usr/bin"
# The portable CPython ships its own libpython and shared libs; make sure they
# resolve regardless of the host's library layout.
export LD_LIBRARY_PATH="$APPDIR_ROOT/usr/python/lib:$APPDIR_ROOT/usr/lib:${LD_LIBRARY_PATH:-}"

# On Wayland: use KMS/X11 mode only when gsr-kms-server is available in the system PATH
# (it needs cap_sys_admin set by the package manager and cannot be bundled in an AppImage).
# Without it, fall through to portal mode automatically.
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ] && [ -z "${QT_QPA_PLATFORM:-}" ]; then
  if command -v gsr-kms-server >/dev/null 2>&1; then
    export QT_QPA_PLATFORM=xcb
  fi
fi

cd "$APPDIR_ROOT/usr/bin"
exec "$APPDIR_ROOT/usr/python/bin/python3" -m dumb_recorder "$@"
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
    appimagetool "$APPDIR" "$DIST_DIR/DumbRecorder.AppImage"
    exit 0
  fi
  exit 1
fi

APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGE_TOOL" "$APPDIR" "$DIST_DIR/DumbRecorder.AppImage"
