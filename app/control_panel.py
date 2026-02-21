#!/usr/bin/env python3

import sys
import json
import subprocess
import re
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSlider, QFrame, QFileDialog,
    QGraphicsDropShadowEffect, QScrollArea, QSizePolicy,
    QSystemTrayIcon, QMenu, QButtonGroup,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QPalette, QIcon, QPixmap, QPainter, QAction, QImage, QFont,
)
from PySide6.QtSvg import QSvgRenderer

# ── Paths ────────────────────────────────────────────────────────────────
CMD_PIPE       = "/tmp/blucast/cmd.pipe"
PREVIEW_FILE   = "/tmp/blucast/preview.jpg"
CONFIG_DIR     = Path("/root/.config/blucast")
CONFIG_FILE    = CONFIG_DIR / "settings.json"
LOGO_PATH      = "/app/assets/logo.svg"
VCAM_DEVICE    = "/dev/video10"

# ── Effect mapping ───────────────────────────────────────────────────────
EFFECT_MAP = {
    "blur":    6,
    "replace": 5,
    "remove":  3,
    "none":    4,
}

DEFAULT_FORMATS = {
    "640x480":   [15, 24, 30, 60],
    "1280x720":  [15, 24, 30, 60],
    "1920x1080": [15, 24, 30, 60],
}

STANDARD_RESOLUTIONS = [
    (320, 240), (640, 480), (800, 600), (960, 540), (1024, 576),
    (1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160),
]

# ── Stylesheet ───────────────────────────────────────────────────────────
STYLESHEET = """
QMainWindow { background-color: #0a0f0a; }
QWidget { color: #e2e8f0; font-family: 'Ubuntu', 'Inter', sans-serif; font-size: 13px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QLabel { color: #94a3b8; border: 0; }
QComboBox {
    background: #1a1f1a; border: 1px solid #2d3d2d; border-radius: 10px;
    padding: 12px 16px; padding-right: 40px; font-size: 14px; min-height: 22px; color: #e2e8f0;
}
QComboBox:hover { border-color: #3b82f6; background: #1f2a1f; }
QComboBox::drop-down { border: none; width: 40px; }
QComboBox QAbstractItemView {
    background: #1a1f1a; border: 1px solid #2d3d2d; border-radius: 8px;
    selection-background-color: #3b82f6; padding: 4px; outline: none;
}
QComboBox QAbstractItemView::item { padding: 8px 12px; border-radius: 6px; min-height: 24px; }
QPushButton {
    background: #1a1f1a; border: 1px solid #2d3d2d; border-radius: 10px;
    padding: 12px 20px; font-size: 14px; font-weight: 500; color: #94a3b8;
}
QPushButton:hover { background: #1f2a1f; border-color: #3d4d3d; }
QPushButton:pressed { background: #2d3d2d; }
QSlider::groove:horizontal { background: #2d3d2d; height: 8px; border-radius: 4px; }
QSlider::handle:horizontal {
    background: #3b82f6; width: 20px; height: 20px; margin: -6px 0;
    border-radius: 10px; border: 3px solid #0a0f0a;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa);
    border-radius: 4px;
}
"""


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════

def send_command(cmd: str) -> bool:
    """Send a command to the server via named pipe."""
    try:
        with open(CMD_PIPE, 'w') as f:
            f.write(cmd + '\n')
        return True
    except OSError:
        return False


def get_video_devices() -> List[Tuple[str, str]]:
    """Return list of (path, name) for real camera devices (excluding our vcam)."""
    devices = []
    try:
        for entry in sorted(Path("/dev").iterdir()):
            if not entry.name.startswith("video"):
                continue
            path = str(entry)
            if path == VCAM_DEVICE:
                continue
            try:
                res = subprocess.run(
                    ["v4l2-ctl", "-d", path, "--info"],
                    capture_output=True, text=True, timeout=1,
                )
                name = "Unknown Camera"
                for line in res.stdout.splitlines():
                    if "Card type" in line:
                        name = line.split(":", 1)[1].strip()
                        break
                devices.append((path, name))
            except Exception:
                devices.append((path, f"Camera ({entry.name})"))
    except Exception:
        pass
    return devices or [("/dev/video0", "Default Camera")]


def get_supported_formats(device: str) -> Dict[str, List[int]]:
    """Query device for supported resolutions and frame rates."""
    try:
        res = subprocess.run(
            ["v4l2-ctl", "-d", device, "--list-formats-ext"],
            capture_output=True, text=True, timeout=2,
        )
    except Exception:
        return {}

    output = res.stdout or ""
    if not output:
        return {}

    size_re = re.compile(r"Size:\s+Discrete\s+(\d+)x(\d+)")
    step_re = re.compile(r"Size:\s+Stepwise\s+(\d+)x(\d+)\s*-\s*(\d+)x(\d+)")
    fps_re  = re.compile(r"\(([\d.]+)\s*fps\)")
    frac_re = re.compile(r"Interval:\s+Discrete\s+(\d+)\s*/\s*(\d+)")
    step_fps_re = re.compile(r"Interval:\s+Stepwise\s+([\d.]+)s\s*-\s*([\d.]+)s")

    formats: Dict[str, Set[int]] = {}
    current_res = None
    stepwise_range = None
    stepwise_fps: Set[int] = set()
    stepwise_fps_range = None

    for line in output.splitlines():
        m = size_re.search(line)
        if m:
            current_res = f"{m.group(1)}x{m.group(2)}"
            formats.setdefault(current_res, set())
            continue

        m = step_re.search(line)
        if m:
            stepwise_range = tuple(map(int, m.groups()))
            current_res = None
            continue

        m = fps_re.search(line)
        if m:
            fps = int(round(float(m.group(1))))
            if 0 < fps <= 240:
                if current_res:
                    formats.setdefault(current_res, set()).add(fps)
                else:
                    stepwise_fps.add(fps)
            continue

        m = frac_re.search(line)
        if m:
            n, d = float(m.group(1)), float(m.group(2))
            if n > 0:
                fps = int(round(d / n))
                if 0 < fps <= 240:
                    if current_res:
                        formats.setdefault(current_res, set()).add(fps)
                    else:
                        stepwise_fps.add(fps)
            continue

        m = step_fps_re.search(line)
        if m:
            min_s, max_s = float(m.group(1)), float(m.group(2))
            if min_s > 0 and max_s > 0:
                stepwise_fps_range = (int(round(1 / max_s)), int(round(1 / min_s)))

    if formats:
        return {r: sorted(f) for r, f in formats.items() if f}

    if stepwise_range:
        min_w, min_h, max_w, max_h = stepwise_range
        resolutions = [f"{w}x{h}" for w, h in STANDARD_RESOLUTIONS
                       if min_w <= w <= max_w and min_h <= h <= max_h]
        if stepwise_fps_range:
            lo, hi = stepwise_fps_range
            fps_list = [f for f in [15, 24, 30, 60, 120] if lo <= f <= hi]
        else:
            fps_list = sorted(stepwise_fps) or [30]
        return {r: fps_list for r in resolutions} if resolutions else {}

    return {}


# ═════════════════════════════════════════════════════════════════════════
# Settings
# ═════════════════════════════════════════════════════════════════════════

class Settings:
    DEFAULTS = {
        "effect_mode": "blur",
        "background_image": "",
        "blur_strength": 50,
        "resolution": "1280x720",
        "fps": 30,
        "input_device": "",
    }

    def __init__(self):
        self._data = self.DEFAULTS.copy()
        try:
            if CONFIG_FILE.exists():
                self._data.update(json.loads(CONFIG_FILE.read_text()))
        except Exception:
            pass

    def get(self, key):
        return self._data.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self._data[key] = value
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self._data, indent=2))
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════════
# Reusable widgets
# ═════════════════════════════════════════════════════════════════════════

class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet("""
            #card {
                background: #111611;
                border: 1px solid #1f2a1f;
                border-radius: 16px;
            }
        """)


class EffectButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setMinimumHeight(70)
        self.setMinimumWidth(75)
        self._apply(False)
        self.toggled.connect(self._apply)

    def _apply(self, checked):
        if checked:
            self.setStyleSheet("""
                QPushButton {
                    background: #3b82f6; border: 2px solid #3b82f6; color: white;
                    border-radius: 12px; padding: 8px; font-weight: 600; font-size: 11px;
                }
                QPushButton:hover { background: #2563eb; }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background: #1a1f1a; border: 1px solid #2d3d2d; color: #64748b;
                    border-radius: 12px; padding: 8px; font-weight: 500; font-size: 11px;
                }
                QPushButton:hover { background: #1f2a1f; border-color: #3d4d3d; }
            """)


# ═════════════════════════════════════════════════════════════════════════
# Main Window
# ═════════════════════════════════════════════════════════════════════════

class ControlPanel(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.setWindowTitle("BluCast")
        self.setMinimumSize(480, 780)
        self.resize(500, 880)
        self.supported_formats: Dict[str, List[int]] = {}

        self._build_ui()
        self._setup_tray()
        self._apply_saved_settings()
        self._start_preview_timer()

    # ── Preview timer ────────────────────────────────────────────────────
    def _start_preview_timer(self):
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._update_preview)
        self.preview_timer.start(33)  # ~30 fps

    def _update_preview(self):
        """Read JPEG preview written by the server."""
        path = Path(PREVIEW_FILE)
        if not path.exists():
            if self.preview_label.pixmap() and not self.preview_label.pixmap().isNull():
                pass  # Keep last good frame
            else:
                self.preview_placeholder.show()
                self.preview_label.hide()
            return

        try:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                return
            scaled = pixmap.scaled(
                self.preview_label.width() - 4,
                self.preview_label.height() - 4,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)
            self.preview_placeholder.hide()
            self.preview_label.show()
        except Exception:
            pass

    # ── System tray ──────────────────────────────────────────────────────
    def _make_tray_icon(self) -> QIcon:
        px = QPixmap(64, 64)
        px.fill(Qt.transparent)
        if Path(LOGO_PATH).exists():
            renderer = QSvgRenderer(LOGO_PATH)
            painter = QPainter(px)
            renderer.render(painter)
            painter.end()
        else:
            painter = QPainter(px)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(59, 130, 246))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(4, 4, 56, 56)
            painter.setBrush(QColor(255, 255, 255))
            painter.drawEllipse(20, 20, 24, 24)
            painter.end()
        return QIcon(px)

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if not self.tray_available:
            return

        self.tray_icon.setIcon(self._make_tray_icon())
        self.tray_icon.setToolTip("BluCast")

        menu = QMenu()
        show_act = QAction("Show Window", self)
        show_act.triggered.connect(self._show_window)
        menu.addAction(show_act)
        menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self._quit)
        menu.addAction(quit_act)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_click)
        self.tray_icon.show()

    def _show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()
        send_command("WINDOW:visible")

    def _on_tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
                send_command("WINDOW:hidden")
            else:
                self._show_window()

    def closeEvent(self, event):
        if self.tray_available and self.tray_icon.isVisible():
            self.hide()
            send_command("WINDOW:hidden")
            event.ignore()
        else:
            self._quit()
            event.accept()

    # ── UI construction ──────────────────────────────────────────────────
    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # ── Preview ──
        preview_card = Card()
        pv_layout = QVBoxLayout(preview_card)
        pv_layout.setContentsMargins(4, 4, 4, 4)

        self.preview_container = QWidget()
        self.preview_container.setMinimumHeight(200)
        self.preview_container.setStyleSheet("background: #0d120d; border-radius: 12px;")
        inner = QVBoxLayout(self.preview_container)
        inner.setContentsMargins(0, 0, 0, 0)

        self.preview_placeholder = QWidget()
        ph_layout = QVBoxLayout(self.preview_placeholder)
        ph_layout.setAlignment(Qt.AlignCenter)
        ph_label = QLabel("Camera preview")
        ph_label.setStyleSheet("color: #64748b; font-size: 13px; background: transparent;")
        ph_label.setAlignment(Qt.AlignCenter)
        ph_layout.addWidget(ph_label)
        inner.addWidget(self.preview_placeholder)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(180)
        self.preview_label.hide()
        inner.addWidget(self.preview_label)

        pv_layout.addWidget(self.preview_container)

        self.preview_info = QLabel("1280x720 @ 30fps")
        self.preview_info.setStyleSheet("color: #64748b; font-size: 11px; background: transparent; padding: 4px;")
        self.preview_info.setAlignment(Qt.AlignRight)
        pv_layout.addWidget(self.preview_info)
        layout.addWidget(preview_card)

        # ── Status indicator ──
        status_card = Card()
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(16, 12, 16, 12)

        status_info = QVBoxLayout()
        status_info.setSpacing(2)
        status_title = QLabel("Virtual Camera")
        status_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #fff; background: transparent;")
        status_info.addWidget(status_title)
        self.status_label = QLabel(VCAM_DEVICE)
        self.status_label.setStyleSheet("font-size: 12px; color: #64748b; background: transparent;")
        status_info.addWidget(self.status_label)
        status_layout.addLayout(status_info)
        status_layout.addStretch()

        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #22c55e; font-size: 22px; background: transparent;")
        status_layout.addWidget(self.status_dot)
        layout.addWidget(status_card)

        # ── Effects ──
        effects_card = Card()
        fx_layout = QVBoxLayout(effects_card)
        fx_layout.setContentsMargins(16, 16, 16, 16)
        fx_layout.setSpacing(16)

        fx_title = QLabel("Background Effects")
        fx_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #fff; background: transparent;")
        fx_layout.addWidget(fx_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.effect_buttons: Dict[str, EffectButton] = {}
        self.effect_group = QButtonGroup(self)
        self.effect_group.setExclusive(True)

        for key, label in [("blur", "BLUR"), ("replace", "REPLACE"),
                           ("remove", "REMOVE"), ("none", "NONE")]:
            btn = EffectButton(label)
            self.effect_buttons[key] = btn
            self.effect_group.addButton(btn)
            btn_row.addWidget(btn)
            btn.toggled.connect(lambda checked, k=key: self._on_effect(k, checked))
        fx_layout.addLayout(btn_row)

        # Blur controls
        self.blur_controls = QWidget()
        bl_layout = QVBoxLayout(self.blur_controls)
        bl_layout.setContentsMargins(0, 8, 0, 0)
        bl_layout.setSpacing(8)

        bh = QHBoxLayout()
        bh.addWidget(self._styled_label("Blur Strength"))
        self.blur_value_label = QLabel("50%")
        self.blur_value_label.setStyleSheet("color: #3b82f6; font-size: 13px; font-weight: 600; background: transparent;")
        bh.addWidget(self.blur_value_label)
        bl_layout.addLayout(bh)

        self.blur_slider = QSlider(Qt.Horizontal)
        self.blur_slider.setRange(0, 100)
        self.blur_slider.setValue(50)
        self.blur_slider.valueChanged.connect(self._on_blur)
        bl_layout.addWidget(self.blur_slider)
        fx_layout.addWidget(self.blur_controls)
        self.blur_controls.hide()

        # Background image controls
        self.bg_controls = QWidget()
        bg_layout = QVBoxLayout(self.bg_controls)
        bg_layout.setContentsMargins(0, 8, 0, 0)
        bg_layout.setSpacing(8)
        bg_layout.addWidget(self._styled_label("Background Image"))

        bg_row = QHBoxLayout()
        self.bg_path_label = QLabel("No image selected")
        self.bg_path_label.setStyleSheet("color: #64748b; font-size: 12px; background: transparent;")
        bg_row.addWidget(self.bg_path_label, 1)
        self.bg_button = QPushButton("Browse")
        self.bg_button.setStyleSheet("""
            QPushButton { background: #3b82f6; border: none; color: white;
                          border-radius: 8px; padding: 8px 16px; font-weight: 500; }
            QPushButton:hover { background: #2563eb; }
        """)
        self.bg_button.clicked.connect(self._on_browse_bg)
        bg_row.addWidget(self.bg_button)
        bg_layout.addLayout(bg_row)
        fx_layout.addWidget(self.bg_controls)
        self.bg_controls.hide()

        layout.addWidget(effects_card)

        # ── Camera settings ──
        cam_card = Card()
        cam_layout = QVBoxLayout(cam_card)
        cam_layout.setContentsMargins(16, 16, 16, 16)
        cam_layout.setSpacing(14)

        cam_title = QLabel("Camera Settings")
        cam_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #fff; background: transparent;")
        cam_layout.addWidget(cam_title)

        cam_layout.addWidget(self._styled_label("Input Device"))
        dev_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._populate_devices()
        self.device_combo.currentIndexChanged.connect(self._on_device)
        dev_row.addWidget(self.device_combo)

        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedSize(46, 46)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: #1a1f1a; border: 1px solid #2d3d2d; border-radius: 10px;
                font-size: 18px; color: #94a3b8; padding: 8px;
            }
            QPushButton:hover { background: #1f2a1f; border-color: #3b82f6; color: #3b82f6; }
        """)
        refresh_btn.clicked.connect(self._refresh_devices)
        dev_row.addWidget(refresh_btn)
        cam_layout.addLayout(dev_row)

        cam_layout.addWidget(self._styled_label("Resolution"))
        self.res_combo = QComboBox()
        self.res_combo.currentIndexChanged.connect(self._on_resolution)
        cam_layout.addWidget(self.res_combo)

        cam_layout.addWidget(self._styled_label("Frame Rate"))
        self.fps_combo = QComboBox()
        self.fps_combo.currentIndexChanged.connect(self._on_fps)
        cam_layout.addWidget(self.fps_combo)

        layout.addWidget(cam_card)
        layout.addStretch()

        # ── Quit ──
        quit_btn = QPushButton("Quit")
        quit_btn.setStyleSheet("""
            QPushButton {
                background: #1a1515; border: 1px solid #3d2d2d; color: #ef4444;
                border-radius: 10px; padding: 14px; font-size: 14px; font-weight: 600;
            }
            QPushButton:hover { background: #2d1f1f; border-color: #4d3d3d; }
        """)
        quit_btn.clicked.connect(self._quit)
        layout.addWidget(quit_btn)

    # ── Helpers ──────────────────────────────────────────────────────────
    def _styled_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent;")
        return lbl

    def _populate_devices(self):
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for path, name in get_video_devices():
            self.device_combo.addItem(f"{name}  ({path})", path)
        self.device_combo.blockSignals(False)

    def _refresh_devices(self):
        cur = self.device_combo.currentData()
        self._populate_devices()
        for i in range(self.device_combo.count()):
            if self.device_combo.itemData(i) == cur:
                self.device_combo.setCurrentIndex(i)
                break

    def _refresh_formats(self):
        device = self.settings.get("input_device")
        if not device or not Path(device).exists():
            devs = get_video_devices()
            device = devs[0][0] if devs else "/dev/video0"
            self.settings.set("input_device", device)
        fmts = get_supported_formats(device)
        self.supported_formats = fmts if fmts else DEFAULT_FORMATS.copy()

    def _populate_res_combo(self, preferred: Optional[str] = None) -> Optional[str]:
        if not self.supported_formats:
            return None
        resolutions = sorted(self.supported_formats.keys(),
                             key=lambda r: tuple(map(int, r.split("x"))))
        self.res_combo.blockSignals(True)
        self.res_combo.clear()
        for r in resolutions:
            self.res_combo.addItem(r, r)
        self.res_combo.blockSignals(False)
        target = preferred if preferred in self.supported_formats else resolutions[0]
        idx = self.res_combo.findData(target)
        if idx >= 0:
            self.res_combo.setCurrentIndex(idx)
        return target

    def _populate_fps_combo(self, res: str, preferred: Optional[int] = None) -> Optional[int]:
        fps_list = self.supported_formats.get(res, [])
        if not fps_list:
            self.fps_combo.blockSignals(True)
            self.fps_combo.clear()
            self.fps_combo.blockSignals(False)
            return None
        self.fps_combo.blockSignals(True)
        self.fps_combo.clear()
        for f in fps_list:
            self.fps_combo.addItem(f"{f} fps", f)
        self.fps_combo.blockSignals(False)
        target = preferred if preferred in fps_list else fps_list[0]
        idx = self.fps_combo.findData(target)
        if idx >= 0:
            self.fps_combo.setCurrentIndex(idx)
        return target

    def _update_info_label(self):
        res = self.settings.get("resolution")
        fps = self.settings.get("fps")
        self.preview_info.setText(f"{res} @ {fps}fps")

    # ── Apply saved settings ─────────────────────────────────────────────
    def _apply_saved_settings(self):
        # Effect
        eff = self.settings.get("effect_mode")
        btn = self.effect_buttons.get(eff, self.effect_buttons["blur"])
        btn.setChecked(True)

        # Blur
        self.blur_slider.setValue(self.settings.get("blur_strength"))

        # Background
        bg = self.settings.get("background_image")
        if bg and Path(bg).exists():
            self.bg_path_label.setText(Path(bg).name)
            self.bg_path_label.setStyleSheet("color: #e2e8f0; font-size: 12px; background: transparent;")

        # Device
        saved_dev = self.settings.get("input_device")
        if saved_dev:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == saved_dev:
                    self.device_combo.setCurrentIndex(i)
                    break

        # Resolution / FPS
        self._refresh_formats()
        sel_res = self._populate_res_combo(self.settings.get("resolution"))
        sel_fps = None
        if sel_res:
            sel_fps = self._populate_fps_combo(sel_res, self.settings.get("fps"))
            self.settings.set("resolution", sel_res)
        if sel_fps is not None:
            self.settings.set("fps", sel_fps)
        self._update_info_label()

        # Send everything to server
        self._send_all()

    def _send_all(self):
        eff = self.settings.get("effect_mode")
        send_command(f"MODE:{EFFECT_MAP.get(eff, 6)}")

        dev = self.settings.get("input_device")
        if dev:
            send_command(f"DEVICE:{dev}")

        bg = self.settings.get("background_image")
        if bg and Path(bg).exists():
            send_command(f"BG:{bg}")

        send_command(f"BLUR:{self.settings.get('blur_strength') / 100.0}")
        send_command(f"RESOLUTION:{self.settings.get('resolution')}")
        send_command(f"FPS:{self.settings.get('fps')}")
        send_command("WINDOW:visible")

    # ── Callbacks ────────────────────────────────────────────────────────
    def _on_effect(self, key: str, checked: bool):
        if not checked:
            return
        self.blur_controls.setVisible(key == "blur")
        self.bg_controls.setVisible(key == "replace")
        send_command(f"MODE:{EFFECT_MAP.get(key, 6)}")
        self.settings.set("effect_mode", key)

    def _on_blur(self, value: int):
        self.blur_value_label.setText(f"{value}%")
        send_command(f"BLUR:{value / 100.0}")
        self.settings.set("blur_strength", value)

    def _on_browse_bg(self):
        start = "/host_home" if Path("/host_home").exists() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Background Image", start,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if path:
            self.bg_path_label.setText(Path(path).name)
            self.bg_path_label.setStyleSheet("color: #e2e8f0; font-size: 12px; background: transparent;")
            send_command(f"BG:{path}")
            self.settings.set("background_image", path)

    def _on_device(self, index: int):
        if index < 0:
            return
        device = self.device_combo.itemData(index)
        send_command(f"DEVICE:{device}")
        self.settings.set("input_device", device)
        self._refresh_formats()
        sel_res = self._populate_res_combo(self.settings.get("resolution"))
        if sel_res:
            sel_fps = self._populate_fps_combo(sel_res, self.settings.get("fps"))
            self.settings.set("resolution", sel_res)
            send_command(f"RESOLUTION:{sel_res}")
            if sel_fps is not None:
                self.settings.set("fps", sel_fps)
                send_command(f"FPS:{sel_fps}")
        self._update_info_label()

    def _on_resolution(self, index: int):
        res = self.res_combo.itemData(index)
        if not res:
            return
        prev_fps = self.settings.get("fps")
        self.settings.set("resolution", res)
        sel_fps = self._populate_fps_combo(res, prev_fps)
        send_command(f"RESOLUTION:{res}")
        if sel_fps is not None and sel_fps != prev_fps:
            self.settings.set("fps", sel_fps)
            send_command(f"FPS:{sel_fps}")
        self._update_info_label()

    def _on_fps(self, index: int):
        fps = self.fps_combo.itemData(index)
        if fps is None:
            return
        send_command(f"FPS:{fps}")
        self.settings.set("fps", fps)
        self._update_info_label()

    def _quit(self):
        send_command("QUIT")
        QApplication.quit()


# ═════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor("#0a0f0a"))
    palette.setColor(QPalette.WindowText,      QColor("#e2e8f0"))
    palette.setColor(QPalette.Base,            QColor("#111611"))
    palette.setColor(QPalette.AlternateBase,   QColor("#1a1f1a"))
    palette.setColor(QPalette.Text,            QColor("#e2e8f0"))
    palette.setColor(QPalette.Button,          QColor("#1a1f1a"))
    palette.setColor(QPalette.ButtonText,      QColor("#94a3b8"))
    palette.setColor(QPalette.Highlight,       QColor("#3b82f6"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    if Path(LOGO_PATH).exists():
        app.setWindowIcon(QIcon(LOGO_PATH))

    window = ControlPanel()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
