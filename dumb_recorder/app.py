from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from pynput import keyboard
except ImportError:
    keyboard = None

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRect, QRectF, QSize, Qt, QEvent, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QGuiApplication, QIcon, QPainter, QPixmap, QPen, QBrush, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Dumb Recorder"
GREEN = "#39ff14"
RED = "#ff1111"
MIN_SIZE = QSize(100, 100)
HANDLE = 10
CORNER_GRIP = 18
TOOLBAR_W = 520
TOOLBAR_H = 86
TOOLBAR_GAP = 10
FRAME_TOP = TOOLBAR_H + TOOLBAR_GAP
CONFIG_DIR = Path.home() / ".config" / "dumb-recorder"
CONFIG_FILE = CONFIG_DIR / "settings.json"
def setup_logging() -> logging.Logger:
    logger = logging.getLogger("dumb-recorder")
    logger.setLevel(logging.ERROR)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)7s %(message)s", "%H:%M:%S")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.ERROR)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger


LOG = setup_logging()


class CircleToolButton(QToolButton):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setFixedSize(30, 30)
        self.setMouseTracking(True)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            if self.underMouse():
                bg_color = QColor(255, 255, 255, 45)
            else:
                bg_color = QColor(0, 0, 0, 100)
            painter.setBrush(bg_color)
            painter.setPen(QPen(QColor(RED), 2))
            painter.drawEllipse(self.rect().adjusted(2, 2, -2, -2))
            pen = QPen(QColor(RED), 2)
            pen.setCapStyle(Qt.SquareCap)
            painter.setPen(pen)
            rect = self.rect()
            cx = rect.width() / 2.0
            cy = rect.height() / 2.0
            if self.text() == "×":
                size = 4.5
                painter.drawLine(QPointF(cx - size, cy - size), QPointF(cx + size, cy + size))
                painter.drawLine(QPointF(cx + size, cy - size), QPointF(cx - size, cy + size))
            elif self.text() == "📁":
                painter.setPen(QPen(QColor(RED), 1.5))
                painter.setBrush(Qt.NoBrush)
                fw, fh = 14.0, 11.0
                fx, fy = cx - fw/2.0, cy - fh/2.0 + 1.0
                painter.drawRect(QRectF(fx, fy, fw, fh))
                painter.drawPolyline([QPointF(fx, fy), QPointF(fx, fy-2.0), QPointF(fx+5.0, fy-2.0), QPointF(fx+7.0, fy)])
            else:
                painter.drawText(self.rect(), Qt.AlignCenter, self.text())


class RecordButton(QPushButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(64, 64)

    def paintEvent(self, event) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            recording = self.property("recording")
            painter.setBrush(QColor(0, 0, 0, 160))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(self.rect().adjusted(4, 4, -4, -4))
            cx, cy = self.width() / 2.0, self.height() / 2.0
            painter.setBrush(QColor(RED))
            painter.setPen(QPen(Qt.white, 2))
            if recording:
                s = 22
                painter.drawRoundedRect(QRectF(cx - s/2, cy - s/2, s, s), 3, 3)
            else:
                r = 14
                painter.drawEllipse(QPointF(cx, cy), r, r)


class StyledCheckBox(QCheckBox):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(24)

    def sizeHint(self) -> QSize:
        # Calculate width: box (18) + gap (10) + text width + safety margin (5)
        tw = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(18 + 10 + tw + 5, 24)

    def paintEvent(self, event) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            size = 18
            rect = QRect(0, (self.height() - size) // 2, size, size)
            if self.isChecked():
                painter.setBrush(QColor(RED))
                painter.setPen(QPen(QColor(RED), 1))
            else:
                painter.setBrush(QColor(42, 42, 42))
                painter.setPen(QPen(QColor(61, 61, 61), 1))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(Qt.white)
            text_rect = self.rect().adjusted(size + 10, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())


class ToolbarFrame(QFrame):
    def paintEvent(self, event) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(0, 0, 0, 180))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)


@dataclass
class Settings:
    x: int | None = None
    y: int | None = None
    width: int = 500
    height: int = 500
    audio: bool = True
    cursor: bool = True
    fmt: str = "MP4"
    fps: str = "60 fps"
    audio_source: str = "default_output"

    @classmethod
    def load(cls) -> Settings:
        if not CONFIG_FILE.exists(): return cls()
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return cls(**data)
        except: return cls()

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.__dict__, f, indent=4)
        except: pass


class RecorderEngine:
    def __init__(self, parent: QWidget) -> None:
        self.parent = parent
        self.process = None
        self.temp_file = None
        self.final_format = "MP4"
        self.output_lines = []
        self.reader_threads = []
        self.crop_after_recording = False
        self.crop_region = QRect()
        self.capture_screen_rect = QRect()

    def list_audio_sources(self) -> list[tuple[str, str]]:
        sources = [("Monitor current output", "default_monitor")]
        if sys.platform != "linux": return sources
        try:
            out = subprocess.check_output(["pactl", "list", "sources"], text=True, stderr=subprocess.DEVNULL)
            current = {}
            for line in out.splitlines():
                l = line.strip()
                if l.startswith("Source #"):
                    if current.get("Name", "").endswith(".monitor"): sources.append(self._format_src(current))
                    current = {}
                elif l.startswith("Name: "): current["Name"] = l[6:]
                elif l.startswith("Description: "): current["Desc"] = l[13:].replace("Monitor of ", "")
                elif "device.bus =" in l: current["Bus"] = l.split("=")[1].strip().strip('"')
            if current.get("Name", "").endswith(".monitor"): sources.append(self._format_src(current))
        except: pass
        return sources

    def _format_src(self, s: dict) -> tuple[str, str]:
        name = s.get("Desc", s.get("Name", "Unknown")).replace(" Analoges Stereo", "").replace(" Analog Stereo", "").strip()
        bus = s.get("Bus", "bluez" if "bluez" in s.get("Name", "") else "pci" if "pci" in s.get("Name", "") else "usb" if "usb" in s.get("Name", "") else "")
        display = f"Monitor {name}"
        if bus: display += f" ({bus.title() if bus != 'bluez' else 'Bluez'})"
        return display, s["Name"]

    def _get_gsr_monitors(self) -> list[dict]:
        try:
            out = subprocess.check_output(["gpu-screen-recorder", "--list-monitors"], text=True, stderr=subprocess.DEVNULL)
            monitors = []
            for line in out.splitlines():
                m = re.search(r"Monitor:\s+(.*?)\s+\((\d+)x(\d+)\+(-?\d+)\+(-?\d+)\)", line.strip())
                if m:
                    monitors.append({"name": m.group(1), "x": int(m.group(4)), "y": int(m.group(5))})
                elif "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 2: monitors.append({"name": parts[0], "x": 0, "y": 0})
            return monitors
        except: return []

    def _get_env(self) -> dict:
        env = os.environ.copy()
        if "APPIMAGE" in env:
            # Aggressively clean up environment variables to avoid AppImage library conflicts
            # This ensures gpu-screen-recorder uses system OpenGL drivers
            for key in ["LD_LIBRARY_PATH", "LD_PRELOAD", "QT_PLUGIN_PATH", "PYTHONPATH"]:
                env.pop(key, None)
            # Force hardware acceleration if possible
            env["LIBGL_ALWAYS_SOFTWARE"] = "0"
        return env

    def start(self, capture: QRect, fmt: str, fps: int, cursor: bool, audio: bool, source: str, screen: QRect, screen_name: str, dpr: float) -> tuple[bool, str]:
        self.final_format = fmt; self.output_lines = []; self.reader_threads = []; self.crop_after_recording = False
        self.capture_screen_rect = QRect(screen); gsr_monitors = self._get_gsr_monitors()
        px, py = capture.x(), capture.y()
        target = next((m for m in gsr_monitors if m["name"] == screen_name), None)
        if not target and gsr_monitors: target = next((m for m in gsr_monitors if abs(m["x"] - screen.x()) < 100), None)
        if target:
            px = target["x"] + round((capture.x() - screen.x()) * dpr)
            py = target["y"] + round((capture.y() - screen.y()) * dpr)
        pw, ph = round(capture.width() * dpr), round(capture.height() * dpr)
        region = f"{pw}x{ph}+{px}+{py}"

        # If we are on Wayland AND not using the X11 trick (xcb), or gsr is missing, use portal
        is_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland"
        is_xcb = os.environ.get("QT_QPA_PLATFORM") == "xcb"

        if (is_wayland and not is_xcb) or not shutil.which("gpu-screen-recorder"):
            return self._start_portal_fallback(capture, fps, cursor, audio, source, screen, dpr)

        cmd = ["gpu-screen-recorder", "-w", region, "-f", str(fps), "-cursor", "yes" if cursor else "no", "-c", "mp4", "-k", "h264", "-ac", "aac", "-o", ""]
        if audio and source != "none":
            if source == "default_monitor":
                try:
                    ds = subprocess.check_output(["pactl", "get-default-sink"], text=True, stderr=subprocess.DEVNULL).strip()
                    source = f"{ds}.monitor"
                except:
                    LOG.error("Failed to get default sink via pactl")
                    source = "default_output"
            cmd[cmd.index("-c"):cmd.index("-c")] = ["-a", source]

        self.temp_file = Path(tempfile.gettempdir()) / f"dumb_recorder_{int(time.time())}.mp4"
        cmd[-1] = str(self.temp_file)
        try:
            self.process = subprocess.Popen(cmd, env=self._get_env(), preexec_fn=os.setsid, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self._start_reader(self.process.stdout); self._start_reader(self.process.stderr)
            time.sleep(0.5);
            if self.process.poll() is not None:
                err_msg = "\n".join(self.output_lines[-20:])
                LOG.error(f"Recorder failed immediately: {err_msg}")
                return False, err_msg
            return True, ""
        except Exception as exc:
            LOG.error(f"Start exception: {exc}")
            return False, str(exc)

    def _start_portal_fallback(self, capture: QRect, fps: int, cursor: bool, audio: bool, source: str, screen: QRect, dpr: float) -> tuple[bool, str]:
        self.crop_after_recording = True
        # Calculate crop region in physical pixels
        self.crop_region = QRect(
            round(max(0, capture.x() - screen.x()) * dpr),
            round(max(0, capture.y() - screen.y()) * dpr),
            round(capture.width() * dpr),
            round(capture.height() * dpr)
        )

        if source == "default_monitor":
            try:
                ds = subprocess.check_output(["pactl", "get-default-sink"], text=True, stderr=subprocess.DEVNULL).strip()
                source = f"{ds}.monitor"
            except: source = "default_output"

        cmd = ["gpu-screen-recorder", "-w", "portal", "-f", str(fps), "-cursor", "yes" if cursor else "no", "-c", "mp4", "-restore-portal-session", "yes", "-o", ""]
        if audio and source != "none": cmd[cmd.index("-c"):cmd.index("-c")] = ["-a", source]
        self.temp_file = Path(tempfile.gettempdir()) / f"dumb_portal_{int(time.time())}.mp4"
        cmd[-1] = str(self.temp_file)
        try:
            self.process = subprocess.Popen(cmd, env=self._get_env(), preexec_fn=os.setsid, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self._start_reader(self.process.stdout); self._start_reader(self.process.stderr)
            time.sleep(1.0)
            if self.process.poll() is not None:
                err_msg = "\n".join(self.output_lines[-20:])
                LOG.error(f"Portal recorder failed: {err_msg}")
                return False, err_msg
            return True, ""
        except Exception as exc:
            LOG.error(f"Portal start exception: {exc}")
            return False, str(exc)

    def _start_reader(self, pipe) -> None:
        def read():
            for line in pipe: self.output_lines.append(line.strip())
        t = threading.Thread(target=read, daemon=True); t.start(); self.reader_threads.append(t)

    def stop(self) -> tuple[Path | None, str]:
        if not self.process: return self.temp_file, "No active process"
        temp = self.temp_file
        try:
            pgid = os.getpgid(self.process.pid)
            os.killpg(pgid, signal.SIGINT)
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                self.process.wait()
        except ProcessLookupError:
            pass # Process already gone
        except Exception as e:
            LOG.error(f"Stop error: {e}")

        self.process = None
        # Wait for file
        for _ in range(15):
            if temp and temp.exists() and temp.stat().st_size > 0:
                return temp, ""
            time.sleep(0.1)
        return temp, "" if (temp and temp.exists()) else "File not created"

    def convert_or_move(self, source: Path, target: Path) -> tuple[bool, str]:
        try:
            if self.crop_after_recording:
                cropped = source.with_name(f"cropped_{source.name}")
                crop = f"crop={self.crop_region.width()}:{self.crop_region.height()}:{self.crop_region.x()}:{self.crop_region.y()}"
                res = subprocess.run(["ffmpeg", "-y", "-i", str(source), "-vf", crop, "-c:a", "copy", str(cropped)], capture_output=True, text=True)
                if res.returncode != 0: return False, res.stderr
                source = cropped
            if self.final_format == "GIF":
                # Strict 256 colors with optimized palette and dithering
                # palettegen=max_colors=256 ensures we don't exceed the limit
                # paletteuse=dither=sierra2_4a provides a clean look with better compression
                filt = "fps=15,scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse=dither=sierra2_4a"
                res = subprocess.run(["ffmpeg", "-y", "-i", str(source), "-vf", filt, str(target)], capture_output=True, text=True)
                if res.returncode != 0: return False, res.stderr
            else:
                shutil.move(str(source), str(target))
            return True, ""
        except Exception as exc: return False, str(exc)


class RecorderWindow(QWidget):
    hotkey_signal = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load(); self.engine = RecorderEngine(self); self.is_recording = False
        self._last_hotkey_time = 0
        # Capture dimensions (the green-bordered recording area, independent of window width)
        self._capture_w: int = max(MIN_SIZE.width(), self.settings.width)
        self._capture_h: int = max(MIN_SIZE.height(), self.settings.height)
        # Custom resize state (we don't use startSystemResize so we track it manually)
        self._resize_edges: set[str] = set()
        self._resize_origin: QPoint | None = None
        self._resize_start_capture: QRect | None = None
        self.hotkey_signal.connect(self._hotkey_triggered); self._setup_global_hotkey()
        self.setWindowTitle(APP_NAME); self.app_icon = QIcon(str(self.resource_path("dumbrecordericon.png")))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        # Window width is always >= TOOLBAR_W so the toolbar child widget is never clipped.
        # The capture frame (green border subrect) can be any width >= MIN_SIZE.width().
        self.setMouseTracking(True); self.setMinimumSize(QSize(TOOLBAR_W, MIN_SIZE.height()))
        self._build_ui(); self._build_tray(); self._place_initially(); self._load_audio_sources()

    def _setup_global_hotkey(self) -> None:
        if not keyboard: return
        self.pressed_keys = set()
        def on_press(key):
            try:
                k = key.char.lower() if hasattr(key, 'char') and key.char else str(key).replace("Key.", "").lower()
                self.pressed_keys.add(k)
                if all(x in self.pressed_keys for x in ('ctrl', 'shift', 'r')): self.hotkey_signal.emit()
            except: pass
        def on_release(key):
            try:
                k = key.char.lower() if hasattr(key, 'char') and key.char else str(key).replace("Key.", "").lower()
                self.pressed_keys.discard(k)
            except: pass
        self.hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release); self.hotkey_listener.start()

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.app_icon, self); menu = QMenu()
        self.tray_record_action = QAction("Record\tCtrl+Shift+R", self); self.tray_record_action.triggered.connect(self.toggle_recording)
        info_action = QAction("Info", self); info_action.triggered.connect(self.show_info)
        quit_action = QAction("Quit", self); quit_action.triggered.connect(QApplication.quit)
        menu.addAction(self.tray_record_action); menu.addSeparator(); menu.addAction(info_action); menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger: # Left click
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.showNormal()
                self.raise_()
                self.activateWindow()

    def show_info(self) -> None:
        text = "Vibe-coded by Eisen 2026\nhttps://eisenvibe.vercel.app\nrostrausch@gmail.com"
        msg = QMessageBox(self)
        msg.setWindowTitle("Info")
        msg.setText(text)
        # Center the text within the dialog
        msg.setStyleSheet("QLabel{ min-width: 250px; qproperty-alignment: 'AlignCenter'; }")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()

    def _hotkey_triggered(self) -> None:
        now = time.time()
        if now - self._last_hotkey_time < 1.0: return
        self._last_hotkey_time = now
        self.toggle_recording()

    def _update_tray_icon(self, recording: bool) -> None:
        self.tray_record_action.setText("Stop\tCtrl+Shift+R" if recording else "Record\tCtrl+Shift+R")
        if not recording: self.tray.setIcon(self.app_icon); return
        size = 64; pixmap = QPixmap(size, size); pixmap.fill(Qt.transparent)
        with QPainter(pixmap) as painter:
            painter.setRenderHint(QPainter.Antialiasing); painter.setBrush(QColor(RED)); painter.setPen(QPen(Qt.white, 2)); painter.drawEllipse(8, 8, 48, 48)
        self.tray.setIcon(QIcon(pixmap))

    def resource_path(self, name: str) -> Path:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])); return base / name

    def _build_ui(self) -> None:
        self.size_label = QLabel(self); self.size_label.setObjectName("sizeLabel")
        # Toolbar is a child widget — its position is compositor-independent (client-side layout).
        # The window is always >= TOOLBAR_W wide, so the child widget is never clipped.
        self.toolbar = ToolbarFrame(self)
        self.toolbar.setFixedSize(TOOLBAR_W, TOOLBAR_H)
        root = QVBoxLayout(self.toolbar); root.setContentsMargins(10, 8, 10, 10); root.setSpacing(7)
        top = QHBoxLayout(); top.setSpacing(15); self.close_btn = CircleToolButton("×"); self.close_btn.clicked.connect(self.quit_app)
        self.cursor_check = StyledCheckBox("Mouse"); self.cursor_check.setChecked(self.settings.cursor)
        self.cursor_check.toggled.connect(self._save_settings)
        self.audio_check = StyledCheckBox("Audio"); self.audio_check.setChecked(self.settings.audio)
        self.audio_check.toggled.connect(self._save_settings)
        self.folder_btn = CircleToolButton("📁"); self.folder_btn.clicked.connect(self._open_videos_folder)
        top.addWidget(self.close_btn); top.addStretch(1); top.addWidget(self.cursor_check); top.addWidget(self.audio_check); top.addStretch(1); top.addWidget(self.folder_btn); root.addLayout(top)
        row = QHBoxLayout(); self.format_combo = QComboBox(); self.format_combo.addItems(["MP4 (H.264)", "GIF (low quality)"])
        self.format_combo.setFixedWidth(135)
        self.format_combo.setCurrentIndex(0 if self.settings.fmt == "MP4" else 1)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        self.format_combo.currentIndexChanged.connect(self._save_settings)

        self.audio_combo = QComboBox()
        self.audio_combo.setFixedWidth(240)
        self.audio_combo.view().setTextElideMode(Qt.ElideRight)
        self.audio_combo.currentIndexChanged.connect(self._save_settings)

        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["15 fps", "20 fps", "30 fps", "60 fps"])
        self.fps_combo.setFixedWidth(80)
        self.fps_combo.setCurrentText(self.settings.fps)
        self.fps_combo.currentIndexChanged.connect(self._save_settings)

        row.addWidget(self.format_combo); row.addWidget(self.audio_combo); row.addWidget(self.fps_combo); root.addLayout(row)
        self.record_btn = RecordButton(self); self.record_btn.clicked.connect(self.toggle_recording)
        self.hotkey_label = QLabel("Ctrl + Shift + R", self); self.hotkey_label.setObjectName("hotkeyLabel")
        self.toolbar.installEventFilter(self)
        self._on_format_changed()
        self.setStyleSheet(f"""
            QWidget {{ color: white; font-family: sans-serif; font-size: 13px; }}
            QComboBox {{ background: #2a2a2a; border: 1px solid #3d3d3d; border-radius: 6px; padding: 4px; color: white; qproperty-elideMode: ElideRight; }}
            QComboBox::drop-down {{ border: 0px; width: 0px; }}
            QComboBox::down-arrow {{ image: none; }}
            QComboBox QAbstractItemView {{ background-color: #2a2a2a; selection-background-color: #444444; color: white; outline: none; border: 1px solid #3d3d3d; }}
            QComboBox QAbstractItemView::item {{ min-height: 28px; padding-left: 10px; }}
            #sizeLabel, #hotkeyLabel {{ background: rgba(0,0,0,160); color: {GREEN}; border-radius: 7px; padding: 4px 8px; }}
        """)

    def _capture_rect(self) -> QRect:
        """Subrect (local window coords) that is the actual capture/recording area."""
        x_off = (self.width() - self._capture_w) // 2
        return QRect(x_off, 0, self._capture_w, self.height())

    def _capture_global_rect(self) -> QRect:
        """Global screen coordinates of the capture area."""
        local = self._capture_rect()
        return QRect(self.x() + local.x(), self.y(), local.width(), local.height())

    def _place_initially(self) -> None:
        self._capture_w = max(MIN_SIZE.width(), self.settings.width)
        self._capture_h = max(MIN_SIZE.height(), self.settings.height)
        x, y = self.settings.x or 100, self.settings.y or 100
        win_w = max(TOOLBAR_W, self._capture_w)
        self.setGeometry(x, y, win_w, self._capture_h)
        self._layout_children()

    def _load_audio_sources(self) -> None:
        sources = self.engine.list_audio_sources()
        for label, val in sources:
            self.audio_combo.addItem(label, val)

        # Priority: 1. Saved setting, 2. Default output monitor if exists
        idx = self.audio_combo.findData(self.settings.audio_source)
        if idx < 0:
            idx = self.audio_combo.findData("default_output")

        if idx >= 0:
            self.audio_combo.setCurrentIndex(idx)
        elif self.audio_combo.count() > 0:
            self.audio_combo.setCurrentIndex(0)

    def _on_format_changed(self) -> None:
        is_gif = "GIF" in self.format_combo.currentText()
        if is_gif:
            self.audio_check.setChecked(False)
            self.audio_check.setEnabled(False)
            self.fps_combo.setCurrentText("15 fps")
            self.fps_combo.setEnabled(False)
        else:
            self.audio_check.setEnabled(True)
            self.fps_combo.setEnabled(True)

    def _layout_children(self) -> None:
        if self.is_recording or self.isMinimized() or not self.isVisible():
            self.toolbar.hide()
        else:
            # Toolbar is a child widget. Center it horizontally within the window.
            # Window is always >= TOOLBAR_W wide so no clipping occurs.
            self.toolbar.move((self.width() - TOOLBAR_W) // 2, 10)
            self.toolbar.show()
            self.toolbar.raise_()

        rc = self._capture_rect()
        cw, ch = rc.width(), rc.height()
        btn_w, btn_h = 64, 64
        btn_x = rc.left() + (cw - btn_w) // 2
        btn_y = rc.top() + (ch - btn_h) // 2
        self.record_btn.move(btn_x, btn_y)

        self.size_label.setText(f"{cw} x {ch}")
        self.size_label.adjustSize()
        self.size_label.move(rc.left() + (cw - self.size_label.width()) // 2, btn_y - self.size_label.height() - 8)

        self.hotkey_label.adjustSize()
        self.hotkey_label.move(rc.left() + (cw - self.hotkey_label.width()) // 2, btn_y + btn_h + 8)

    def _edges_at(self, pos: QPoint) -> set[str]:
        rc = self._capture_rect()
        edges = set()
        lx, rx = rc.left(), rc.right()
        ty, by = rc.top(), rc.bottom()
        if lx <= pos.x() <= lx + HANDLE: edges.add("left")
        elif rx - HANDLE <= pos.x() <= rx: edges.add("right")
        if ty <= pos.y() <= ty + HANDLE: edges.add("top")
        elif by - HANDLE <= pos.y() <= by: edges.add("bottom")
        return edges

    def _set_cursor(self, edges, target=None):
        t = target or self
        if not edges: t.setCursor(Qt.ArrowCursor)
        elif edges in ({"left"}, {"right"}): t.setCursor(Qt.SizeHorCursor)
        elif edges in ({"top"}, {"bottom"}): t.setCursor(Qt.SizeVerCursor)
        else: t.setCursor(Qt.SizeBDiagCursor)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton: return
        pos = event.position().toPoint()
        edges = self._edges_at(pos)
        if not edges:
            self.windowHandle().startSystemMove()
            self._resize_edges = set()
        else:
            # Custom resize: track capture rect geometry so we can resize it independently
            # from the window (which must stay >= TOOLBAR_W wide).
            self._resize_edges = edges
            self._resize_origin = event.globalPosition().toPoint()
            self._resize_start_capture = self._capture_global_rect()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if event.buttons() & Qt.LeftButton and self._resize_edges and self._resize_origin is not None:
            delta = event.globalPosition().toPoint() - self._resize_origin
            dx, dy = delta.x(), delta.y()
            rc = self._resize_start_capture  # global capture rect at drag start
            cx, cy = rc.x(), rc.y()
            cr, cb = rc.right(), rc.bottom()

            if "right" in self._resize_edges: cr = rc.right() + dx
            if "left" in self._resize_edges: cx = rc.x() + dx
            if "bottom" in self._resize_edges: cb = rc.bottom() + dy
            if "top" in self._resize_edges: cy = rc.y() + dy

            new_cw = max(MIN_SIZE.width(), cr - cx + 1)
            new_ch = max(MIN_SIZE.height(), cb - cy + 1)

            # Clamp: if minimum was hit, keep the fixed edge in place
            if "left" in self._resize_edges: cx = cr - new_cw + 1
            if "top" in self._resize_edges: cy = cb - new_ch + 1

            self._capture_w = new_cw
            self._capture_h = new_ch

            new_win_w = max(TOOLBAR_W, new_cw)
            # Center the capture rect horizontally within the window
            new_win_x = cx - (new_win_w - new_cw) // 2
            new_win_y = cy

            self.setGeometry(new_win_x, new_win_y, new_win_w, new_ch)
            self._layout_children()
            self.update()
        else:
            self._set_cursor(self._edges_at(pos))

    def mouseReleaseEvent(self, event):
        self._resize_edges = set()
        self._resize_origin = None
        self._resize_start_capture = None

    def resizeEvent(self, event):
        self._save_settings(); self._layout_children(); self.update()

    def moveEvent(self, event):
        self._save_settings(); self._layout_children(); self.update()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._layout_children()

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_children()

    def eventFilter(self, watched, event):
        if watched == self.toolbar and event.type() == QEvent.MouseButtonPress:
            if not self.toolbar.childAt(event.position().toPoint()):
                self.windowHandle().startSystemMove(); return True
        return False

    def paintEvent(self, event) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            frame = self._capture_rect()

            painter.setPen(QPen(QColor(GREEN), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(frame.adjusted(1, 1, -2, -2))

            # Corner accents
            painter.setPen(QPen(QColor(GREEN), 5))
            l, t, r, b = frame.left()+1, frame.top()+1, frame.right()-1, frame.bottom()-1
            for x in (l, r - CORNER_GRIP):
                painter.drawLine(x, t, x + CORNER_GRIP, t)
                painter.drawLine(x, b, x + CORNER_GRIP, b)
            for y in (t, b - CORNER_GRIP):
                painter.drawLine(l, y, l, y + CORNER_GRIP)
                painter.drawLine(r, y, r, y + CORNER_GRIP)

    def _open_videos_folder(self):
        p = Path.home() / "Videos"; p.mkdir(parents=True, exist_ok=True); subprocess.run(["xdg-open", str(p)])

    def toggle_recording(self):
        if self.is_recording: self.stop_recording()
        else: self.start_recording()

    def start_recording(self):
        self._save_settings(); self.is_recording = True; self.record_btn.setProperty("recording", True); self.record_btn.update()
        self._update_tray_icon(True); self.hide(); QTimer.singleShot(100, self._real_start)

    def _real_start(self):
        fps_text = self.fps_combo.currentText()
        fps = int(fps_text.split()[0])
        fmt = "GIF" if "GIF" in self.format_combo.currentText() else "MP4"
        capture = self._capture_global_rect()
        screen = QGuiApplication.screenAt(capture.center()) or QGuiApplication.primaryScreen()
        success, err = self.engine.start(capture, fmt, fps, self.cursor_check.isChecked(), self.audio_check.isChecked(), self.audio_combo.currentData(), screen.geometry(), screen.name(), screen.devicePixelRatio())
        if not success:
            self.is_recording = False
            self.record_btn.setProperty("recording", False)
            self.record_btn.update()
            self._update_tray_icon(False)
            self.show()
            QMessageBox.critical(self, "Recording Error", f"Failed to start recording:\n{err}")
            return

        if fmt == "GIF":
            # Auto-stop GIF after 60 seconds
            QTimer.singleShot(60000, self._auto_stop_gif)

    def _auto_stop_gif(self):
        if self.is_recording and "GIF" in self.format_combo.currentText():
            self.stop_recording()

    def stop_recording(self):
        self.is_recording = False; self.record_btn.setProperty("recording", False); self.record_btn.update()
        self._update_tray_icon(False); temp_path, err = self.engine.stop(); self.show(); self.raise_(); self.activateWindow()

        if not temp_path or not temp_path.exists():
            QMessageBox.critical(self, "Error", f"Recording file not found: {temp_path}\n{err}")
            return

        ext = "mp4" if "MP4" in self.format_combo.currentText() else "gif"
        stamp = datetime.now().strftime("%y.%m.%d_%H.%M.%S")
        target, _ = QFileDialog.getSaveFileName(self, "Save", str(Path.home()/"Videos"/f"rec_{stamp}.{ext}"))

        if target:
            success, msg = self.engine.convert_or_move(temp_path, Path(target))
            if not success:
                QMessageBox.critical(self, "FFmpeg Error", f"Failed to process video:\n{msg}")

    def _save_settings(self):
        g = self.geometry(); self.settings.x, self.settings.y = g.x(), g.y()
        # Save the capture dimensions, not the window dimensions
        self.settings.width = self._capture_w
        self.settings.height = self._capture_h
        self.settings.audio = self.audio_check.isChecked()
        self.settings.cursor = self.cursor_check.isChecked()
        self.settings.fmt = "GIF" if "GIF" in self.format_combo.currentText() else "MP4"
        self.settings.fps = self.fps_combo.currentText()
        self.settings.audio_source = self.audio_combo.currentData()
        self.settings.save()

    def quit_app(self):
        if self.is_recording: self.stop_recording()
        QApplication.quit()

def main():
    app = QApplication(sys.argv); win = RecorderWindow(); win.show(); return app.exec()

if __name__ == "__main__":
    sys.exit(main())
