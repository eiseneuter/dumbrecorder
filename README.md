# Dumb Recorder

Dumb Recorder is a small Linux screen recorder for KDE Wayland sessions. It gives you a draggable capture frame + toolbar, MP4 recording, low-quality GIF export, mouse cursor toggling, output-monitor audio capture, frame-rate selection, tray control, and persistent geometry/settings.

The recording backend is `gpu-screen-recorder`. Dumb Recorder provides the region UI and passes the exact capture rectangle, format, cursor, FPS, and audio options to the backend. Audio devices are discovered through the PulseAudio-compatible `pactl` interface, so the intended setup is PipeWire with `pipewire-pulse`/WirePlumber. Classic PulseAudio may work for audio enumeration, but the app is developed and tested for Wayland + PipeWire.

Dumb Recorder is intentionally focused: choose an area, record it, stop, and save the result. It is not a streaming suite or video editor. Its main job is to make region recording on a modern Wayland/PipeWire desktop feel direct and predictable.

Made with OpenAI Codex.

## Platform

- Linux only
- Developed for CachyOS/KDE Plasma on Wayland
- PipeWire session recommended
- MP4 output uses H.264 through `gpu-screen-recorder`
- GIF export uses `ffmpeg` after recording

## Runtime Dependencies

For running from source:

- `python3`
- `python3-venv`
- `gpu-screen-recorder`
- `ffmpeg` for GIF export
- `pactl` from PipeWire Pulse or PulseAudio for audio monitor discovery
- working GPU/OpenGL drivers for `gpu-screen-recorder`
- KDE/xdg desktop portals for Wayland capture where needed

Python dependencies are listed in `requirements.txt`:

- `PySide6`

Optional Python dependency:

- `pynput` enables the global hotkey listener. It is not installed by default because its `evdev` dependency may require kernel headers on some distributions.

## Run From Source

```bash
./run.sh
```

`run.sh` creates/updates a local `.venv`, installs the Python dependencies, prefers `./vendor/gpu-screen-recorder` if present, and then starts the app.

Only errors and crashes are written to the terminal.

Settings are stored in:

```text
~/.config/dumb-recorder/settings.json
```

## Build AppImage Locally

```bash
./build_appimage.sh
```

The build script creates `build/AppDir`, installs the Python dependencies into `build/AppDir/usr/venv`, copies the app, icon, `.desktop` file, AppStream metadata, and bundles `gpu-screen-recorder` plus `ffmpeg` when available. If `gpu-screen-recorder` cannot be bundled, the AppImage uses the host installation from `PATH` at runtime.

Output:

```text
dist/Dumb_Recorder-x86_64.AppImage
```

Important host dependencies still remain host dependencies: GPU drivers, PipeWire, portals, and any privileged `gpu-screen-recorder` helper such as `gsr-kms-server` must match the running system and cannot be reliably bundled into an AppImage.

## Build AppImage With Docker

```bash
./build_appimage_docker.sh
```

This builds a local Docker image from `Dockerfile.appimage`, mounts the project into the container, and runs `./build_appimage.sh` there. The resulting AppImage is written to `dist/`.

## Repository Contents

- `dumb_recorder/` - Python/PySide6 application
- `run.sh` - source runner
- `build_appimage.sh` - native AppImage build
- `build_appimage_docker.sh` - containerized AppImage build
- `Dockerfile.appimage` - Docker image for AppImage builds
- `dumb-recorder.desktop` - desktop launcher
- `io.github.eisen.DumbRecorder.metainfo.xml` - AppStream metadata
- `dumbrecordericon.png` - application icon
- `requirements.txt` - Python dependencies
- `.gitignore` / `.dockerignore` - keep build artifacts out of the repo and Docker build context

## Ignored / Local-Only Paths

These are intentionally not part of the repository:

- `.venv/` - local source-run virtualenv created by `run.sh`
- `build/` - AppDir staging tree produced by `build_appimage.sh`
- `dist/` - finished AppImages
- `tools/appimagetool-x86_64.AppImage` - downloaded build tool
- `local/` - scratch/test scripts (e.g. `resize_test.py`)
- `vendor/` - optional local `gpu-screen-recorder` binary for source runs
- `*.AppImage` - any AppImage anywhere in the tree
