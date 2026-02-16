#!/usr/bin/env python3
"""
BluCast Control Panel
A modern, dark themed interface for AI-powered video effects.
"""

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
    QSystemTrayIcon, QMenu, QButtonGroup, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, QTimer, Signal, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, QAbstractAnimation
from PySide6.QtGui import QColor, QPalette, QIcon, QPixmap, QPainter, QAction, QImage, QFont, QFontDatabase
from PySide6.QtSvg import QSvgRenderer

CMD_PIPE = "/tmp/blucast/blucast_cmd"
CONFIG_DIR = Path("/root/.config/blucast")
CONFIG_FILE = CONFIG_DIR / "settings.json"
PREVIEW_FRAME = "/tmp/blucast/preview_frame.raw"
LOGO_PATH = "/app/assets/logo.svg"

# TODO: Add denoise filter (from superres)
# Map effect buttons to internal mode indices
EFFECT_MAP = {
    "blur": 6,      # Blur Background
    "replace": 5,   # Custom Background
    "remove": 3,    # White Background (or could be green screen)
    "none": 4,      # Original
}

DEFAULT_SUPPORTED_FORMATS = {
    "640x480": [15, 24, 30, 60],
    "1280x720": [15, 24, 30, 60],
    "1920x1080": [15, 24, 30, 60],
}

STANDARD_RESOLUTIONS = [
    (320, 240),
    (640, 480),
    (800, 600),
    (960, 540),
    (1024, 576),
    (1280, 720),
    (1600, 900),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
]

STYLESHEET = """
QMainWindow {
    background-color: #0a0f0a;
}
QWidget {
    color: #e2e8f0;
    font-family: 'Ubuntu', 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollArea > QWidget > QWidget {
    background-color: transparent;
}
QLabel {
    color: #94a3b8;
    border: 0px solid #0a0f0a;
}
QComboBox {
    background-color: #1a1f1a;
    border: 1px solid #2d3d2d;
    border-radius: 10px;
    padding: 12px 16px;
    padding-right: 40px;
    font-size: 14px;
    min-height: 22px;
    color: #e2e8f0;
    selection-background-color: transparent;
}
QComboBox:hover {
    border-color: #3b82f6;
    background-color: #1f2a1f;
}
QComboBox:focus {
    border-color: #3b82f6;
}
QComboBox:on {
    border-color: #3b82f6;
}
QComboBox::drop-down {
    border: none;
    background: transparent;
    width: 40px;
    subcontrol-origin: padding;
    subcontrol-position: right center;
}
QComboBox::down-arrow {
    image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiM2NDc0OGIiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJNNiA5bDYgNiA2LTYiLz48L3N2Zz4=");
    width: 14px;
    height: 14px;
}
QComboBox QAbstractItemView {
    background-color: #1a1f1a;
    border: 1px solid #2d3d2d;
    border-radius: 8px;
    selection-background-color: #3b82f6;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    padding: 8px 12px;
    border-radius: 6px;
    min-height: 24px;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #3b82f6;
}
QPushButton {
    background-color: #1a1f1a;
    border: 1px solid #2d3d2d;
    border-radius: 10px;
    padding: 12px 20px;
    font-size: 14px;
    font-weight: 500;
    color: #94a3b8;
}
QPushButton:hover {
    background-color: #1f2a1f;
    border-color: #3d4d3d;
}
QPushButton:pressed {
    background-color: #2d3d2d;
}
QSlider::groove:horizontal {
    background-color: #2d3d2d;
    height: 8px;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background-color: #3b82f6;
    width: 20px;
    height: 20px;
    margin: -6px 0;
    border-radius: 10px;
    border: 3px solid #0a0f0a;
}
QSlider::handle:horizontal:hover {
    background-color: #2563eb;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa);
    border-radius: 4px;
}
"""


class Settings:
    """Persistent settings storage with sensible defaults."""
    
    DEFAULT = {
        "effect_mode": "blur",
        "background_image": "",
        "blur_strength": 50,
        "vcam_enabled": False,
        "preview_enabled": True,
        "overlay_enabled": False,
        "resolution": "1280x720",
        "fps": 30,
        "input_device": "",
    }

    def __init__(self):
        self._data = self.DEFAULT.copy()
        self._load()

    def _load(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE) as f:
                    self._data.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self._data, f, indent=2)
        except OSError:
            pass

    def get(self, key):
        return self._data.get(key, self.DEFAULT.get(key))

    def set(self, key, value):
        self._data[key] = value
        self.save()


def send_command(cmd: str) -> bool:
    """Send a command to the video processing server via named pipe."""
    try:
        with open(CMD_PIPE, 'w') as f:
            f.write(cmd + '\n')
        return True
    except OSError:
        return False


VCAM_DEVICE = "/dev/video10"


def get_video_devices():
    """Get list of available video devices."""
    devices = []
    try:
        result = subprocess.run(['ls', '/dev'], capture_output=True, text=True)
        for line in result.stdout.split():
            if line.startswith('video'):
                dev_path = f"/dev/{line}"
                if dev_path == VCAM_DEVICE:
                    continue
                try:
                    name_result = subprocess.run(
                        ['v4l2-ctl', '-d', dev_path, '--info'],
                        capture_output=True, text=True, timeout=1
                    )
                    name = "Unknown Camera"
                    for info_line in name_result.stdout.split('\n'):
                        if 'Card type' in info_line:
                            name = info_line.split(':')[1].strip()
                            break
                    devices.append((dev_path, name))
                except:
                    devices.append((dev_path, f"Camera {line}"))
    except:
        devices = [("/dev/video0", "Default Camera")]
    
    if not devices:
        devices = [("/dev/video0", "Integrated Webcam")]
    return devices


def _normalize_fps(value: float) -> Optional[int]:
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return None
    fps_int = int(round(fps))
    if fps_int <= 0 or fps_int > 240:
        return None
    return fps_int


def get_supported_formats(device_path: str) -> Dict[str, List[int]]:
    """Get supported resolutions and frame rates for a device using v4l2-ctl."""
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", device_path, "--list-formats-ext"],
            capture_output=True,
            text=True,
            timeout=2
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    output = result.stdout or ""
    if not output:
        return {}

    size_discrete_re = re.compile(r"Size:\s+Discrete\s+(\d+)x(\d+)")
    size_step_re = re.compile(r"Size:\s+Stepwise\s+(\d+)x(\d+)\s*-\s*(\d+)x(\d+)")
    interval_fps_re = re.compile(r"\(([-\d\.]+)\s*fps\)")
    interval_frac_re = re.compile(r"Interval:\s+Discrete\s+(\d+)\s*/\s*(\d+)")
    interval_step_re = re.compile(r"Interval:\s+Stepwise\s+([\d\.]+)s\s*-\s*([\d\.]+)s")

    formats: Dict[str, Set[int]] = {}
    current_res: Optional[str] = None
    stepwise_range: Optional[Tuple[int, int, int, int]] = None
    stepwise_fps: Set[int] = set()
    stepwise_fps_range: Optional[Tuple[int, int]] = None

    for line in output.splitlines():
        size_match = size_discrete_re.search(line)
        if size_match:
            width, height = size_match.groups()
            current_res = f"{width}x{height}"
            formats.setdefault(current_res, set())
            continue

        step_match = size_step_re.search(line)
        if step_match:
            min_w, min_h, max_w, max_h = map(int, step_match.groups())
            stepwise_range = (min_w, min_h, max_w, max_h)
            current_res = None
            continue

        fps_match = interval_fps_re.search(line)
        if fps_match:
            fps_value = _normalize_fps(fps_match.group(1))
            if fps_value is None:
                continue
            if current_res:
                formats.setdefault(current_res, set()).add(fps_value)
            else:
                stepwise_fps.add(fps_value)
            continue

        frac_match = interval_frac_re.search(line)
        if frac_match:
            numerator = float(frac_match.group(1))
            denominator = float(frac_match.group(2))
            if numerator > 0:
                fps_value = _normalize_fps(denominator / numerator)
                if fps_value is None:
                    continue
                if current_res:
                    formats.setdefault(current_res, set()).add(fps_value)
                else:
                    stepwise_fps.add(fps_value)
            continue

        step_fps_match = interval_step_re.search(line)
        if step_fps_match:
            min_s = float(step_fps_match.group(1))
            max_s = float(step_fps_match.group(2))
            if min_s > 0 and max_s > 0:
                min_fps = _normalize_fps(1.0 / max_s)
                max_fps = _normalize_fps(1.0 / min_s)
                if min_fps and max_fps:
                    stepwise_fps_range = (min_fps, max_fps)

    if formats:
        return {res: sorted(fps_set) for res, fps_set in formats.items() if fps_set}

    if stepwise_range:
        min_w, min_h, max_w, max_h = stepwise_range
        resolutions = []
        for width, height in STANDARD_RESOLUTIONS:
            if min_w <= width <= max_w and min_h <= height <= max_h:
                resolutions.append(f"{width}x{height}")

        if stepwise_fps_range:
            min_fps, max_fps = stepwise_fps_range
            candidates = [15, 24, 30, 60, 120]
            fps_values = [fps for fps in candidates if min_fps <= fps <= max_fps]
        else:
            fps_values = sorted(stepwise_fps) if stepwise_fps else [30]

        return {res: fps_values for res in resolutions} if resolutions else {}

    return {}


class Card(QFrame):
    """A styled card component with dark theme."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card_frame") 
        self.setStyleSheet("""
            #card_frame {
                background-color: #111611;
                border: 1px solid #1f2a1f;
                border-radius: 16px;
            }
        """)

class EffectButton(QPushButton):
    """A button for effect selectDion with icon-like appearance."""
    
    def __init__(self, text: str, icon_text: str = "", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.icon_text = icon_text
        self.setCheckable(True)
        self.setMinimumHeight(70)
        self.setMinimumWidth(75)
        self._update_style(False)
        self.toggled.connect(self._update_style)

    def _update_style(self, checked: bool):
        if checked:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    border: 2px solid #3b82f6;
                    color: white;
                    border-radius: 12px;
                    padding: 8px;
                    font-weight: 600;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                    border-color: #2563eb;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #1a1f1a;
                    border: 1px solid #2d3d2d;
                    color: #64748b;
                    border-radius: 12px;
                    padding: 8px;
                    font-weight: 500;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #1f2a1f;
                    border-color: #3d4d3d;
                }
            """)


class ToggleButton(QPushButton):
    """A toggle button with on/off states and visual feedback."""
    
    def __init__(self, text_on: str, text_off: str, parent=None):
        super().__init__(parent)
        self.text_on = text_on
        self.text_off = text_off
        self.setCheckable(True)
        self.toggled.connect(self._update_style)
        self._update_style(self.isChecked())

    def _update_style(self, checked: bool):
        self.setText(self.text_on if checked else self.text_off)
        if checked:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    border: none;
                    color: white;
                    border-radius: 10px;
                    padding: 12px 20px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #1a1f1a;
                    border: 1px solid #2d3d2d;
                    color: #64748b;
                    border-radius: 10px;
                    padding: 12px 20px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #1f2a1f;
                }
            """)


class ControlPanel(QMainWindow):
    """Main application window for BluCast."""
    
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.setWindowTitle("BluCast")
        self.setMinimumSize(480, 800)
        self.resize(500, 900)
        self.preview_width = 0
        self.preview_height = 0
        self.supported_formats = {}
        self._build_ui()
        self._setup_tray()
        self._apply_settings()
        self._setup_preview_timer()

    def _setup_preview_timer(self):
        """Setup timer for updating preview frame."""
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._update_preview)
        self.preview_timer.start(33)  # ~30fps
    
    def _update_preview(self):
        """Update the preview frame from shared memory/file."""
        try:
            # Read resolution from settings
            res = self.settings.get("resolution")
            width, height = map(int, res.split('x'))
            
            frame_path = Path(PREVIEW_FRAME)
            if frame_path.exists():
                with open(frame_path, 'rb') as f:
                    data = f.read()
                if len(data) == width * height * 3:
                    image = QImage(data, width, height, width * 3, QImage.Format_RGB888)
                    pixmap = QPixmap.fromImage(image)
                    scaled = pixmap.scaled(
                        self.preview_label.width() - 4,
                        self.preview_label.height() - 4,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    self.preview_label.setPixmap(scaled)
                    self.preview_placeholder.hide()
                    self.preview_label.show()
                    return
        except:
            pass
        
        # Show placeholder if no frame
        self.preview_label.clear()
        self.preview_placeholder.show()

    def _create_tray_icon(self) -> QIcon:
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        if Path(LOGO_PATH).exists():
            renderer = QSvgRenderer(LOGO_PATH)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
        else:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(59, 130, 246))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(4, 4, 56, 56)
            painter.setBrush(QColor(255, 255, 255))
            painter.drawEllipse(20, 20, 24, 24)
            painter.end()
        return QIcon(pixmap)

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_available = False
            return
        self.tray_available = True
        self.tray_icon.setIcon(self._create_tray_icon())
        self.tray_icon.setToolTip("BluCast")
        
        tray_menu = QMenu()
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self._show_window)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        vcam_action = QAction("Toggle Virtual Camera", self)
        vcam_action.triggered.connect(lambda: self.vcam_button.click())
        tray_menu.addAction(vcam_action)
        tray_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._on_quit)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()
        send_command("EMBEDDED:on")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
                send_command("EMBEDDED:off")
            else:
                self._show_window()

    def closeEvent(self, event):
        if hasattr(self, 'tray_available') and self.tray_available and self.tray_icon.isVisible():
            self.hide()
            send_command("EMBEDDED:off")
            event.ignore()
        else:
            self._on_quit()
            event.accept()

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

        # Preview Card
        preview_card = Card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        
        self.preview_container = QWidget()
        self.preview_container.setMinimumHeight(200)
        self.preview_container.setStyleSheet("""
            QWidget {
                background-color: #0d120d;
                border-radius: 12px;
            }
        """)
        preview_inner = QVBoxLayout(self.preview_container)
        preview_inner.setContentsMargins(0, 0, 0, 0)
        
        # Placeholder for when preview is disabled
        self.preview_placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.preview_placeholder)
        placeholder_layout.setAlignment(Qt.AlignCenter)
        
        camera_off_text = QLabel("Camera preview disabled")
        camera_off_text.setStyleSheet("color: #64748b; font-size: 13px; background: transparent;")
        camera_off_text.setAlignment(Qt.AlignCenter)
        placeholder_layout.addWidget(camera_off_text)
        
        preview_inner.addWidget(self.preview_placeholder)
        
        # Actual preview label
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(180)
        self.preview_label.hide()
        preview_inner.addWidget(self.preview_label)
        
        preview_layout.addWidget(self.preview_container)
        
        # Resolution/FPS indicator
        self.preview_info = QLabel("1280x720 @ 30fps")
        self.preview_info.setStyleSheet("color: #64748b; font-size: 11px; background: transparent; padding: 4px;")
        self.preview_info.setAlignment(Qt.AlignRight)
        preview_layout.addWidget(self.preview_info)
        
        layout.addWidget(preview_card)

        # Virtual Camera Card
        vcam_card = Card()
        vcam_layout = QHBoxLayout(vcam_card)
        vcam_layout.setContentsMargins(16, 16, 16, 16)
        
        vcam_info_layout = QVBoxLayout()
        vcam_info_layout.setSpacing(2)
        vcam_title = QLabel("Virtual Camera")
        vcam_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff; background: transparent;")
        vcam_info_layout.addWidget(vcam_title)
        
        self.vcam_device_label = QLabel("/dev/video10")
        self.vcam_device_label.setStyleSheet("font-size: 12px; color: #64748b; background: transparent;")
        vcam_info_layout.addWidget(self.vcam_device_label)
        
        vcam_layout.addLayout(vcam_info_layout)
        vcam_layout.addStretch()
        
        self.vcam_button = QPushButton("Start")
        self.vcam_button.setFixedWidth(80)
        self.vcam_glow = QGraphicsDropShadowEffect(self.vcam_button)
        self.vcam_glow.setBlurRadius(0)
        self.vcam_glow.setColor(QColor(59, 130, 246, 180))
        self.vcam_glow.setOffset(0, 0)
        self.vcam_button.setGraphicsEffect(self.vcam_glow)
        self.vcam_button.setStyleSheet("""
            QPushButton {
                background-color: #1f2a1f;
                border: 1px solid #2d3d2d;
                border-radius: 8px;
                padding: 10px 16px;
                color: #e2e8f0;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #2d3d2d;
            }
        """)
        self.vcam_button.clicked.connect(self._on_vcam_clicked)
        vcam_layout.addWidget(self.vcam_button)
        
        layout.addWidget(vcam_card)

        # Background Effects Card
        effects_card = Card()
        effects_layout = QVBoxLayout(effects_card)
        effects_layout.setContentsMargins(16, 16, 16, 16)
        effects_layout.setSpacing(16)
        
        effects_title = QLabel("Background Effects")
        effects_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff; background: transparent;")
        effects_layout.addWidget(effects_title)
        
        # Effect buttons row
        effects_row = QHBoxLayout()
        effects_row.setSpacing(8)
        
        self.effect_buttons = {}
        self.effect_group = QButtonGroup(self)
        self.effect_group.setExclusive(True)
        
        for key, label in [("blur", "BLUR"), ("replace", "REPLACE"), ("remove", "REMOVE"), ("none", "NONE")]:
            btn = EffectButton(label)
            self.effect_buttons[key] = btn
            self.effect_group.addButton(btn)
            effects_row.addWidget(btn)
            btn.toggled.connect(lambda checked, k=key: self._on_effect_selected(k, checked))
        
        effects_layout.addLayout(effects_row)
        
        # Blur strength controls (visible only when blur selected)
        self.blur_controls = QWidget()
        blur_controls_layout = QVBoxLayout(self.blur_controls)
        blur_controls_layout.setContentsMargins(0, 8, 0, 0)
        blur_controls_layout.setSpacing(8)
        
        blur_header = QHBoxLayout()
        blur_label = QLabel("Blur Strength")
        blur_label.setStyleSheet("color: #94a3b8; font-size: 13px; background: transparent;")
        blur_header.addWidget(blur_label)
        self.blur_value_label = QLabel("50%")
        self.blur_value_label.setStyleSheet("color: #3b82f6; font-size: 13px; font-weight: 600; background: transparent;")
        blur_header.addWidget(self.blur_value_label)
        blur_controls_layout.addLayout(blur_header)
        
        self.blur_slider = QSlider(Qt.Horizontal)
        self.blur_slider.setRange(0, 100)
        self.blur_slider.setValue(50)
        self.blur_slider.valueChanged.connect(self._on_blur_changed)
        blur_controls_layout.addWidget(self.blur_slider)
        
        effects_layout.addWidget(self.blur_controls)
        self.blur_controls.hide()
        
        # Background image selector (visible only when replace selected)
        self.bg_controls = QWidget()
        bg_controls_layout = QVBoxLayout(self.bg_controls)
        bg_controls_layout.setContentsMargins(0, 8, 0, 0)
        bg_controls_layout.setSpacing(8)
        
        bg_header = QLabel("Background Image")
        bg_header.setStyleSheet("color: #94a3b8; font-size: 13px; background: transparent;")
        bg_controls_layout.addWidget(bg_header)
        
        bg_row = QHBoxLayout()
        self.bg_label = QLabel("No image selected")
        self.bg_label.setStyleSheet("color: #64748b; font-size: 12px; background: transparent;")
        bg_row.addWidget(self.bg_label, 1)
        
        self.bg_button = QPushButton("Browse")
        self.bg_button.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                border: none;
                color: white;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.bg_button.clicked.connect(self._on_select_background)
        bg_row.addWidget(self.bg_button)
        bg_controls_layout.addLayout(bg_row)
        
        effects_layout.addWidget(self.bg_controls)
        self.bg_controls.hide()
        
        layout.addWidget(effects_card)

        # Camera Settings Card
        camera_card = Card()
        camera_layout = QVBoxLayout(camera_card)
        camera_layout.setContentsMargins(16, 16, 16, 16)
        camera_layout.setSpacing(14)
        
        camera_title = QLabel("Camera Settings")
        camera_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff; background: transparent;")
        camera_layout.addWidget(camera_title)
        
        # Input Device
        input_text = QLabel("Input Device")
        input_text.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent;")
        camera_layout.addWidget(input_text)
        
        device_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._populate_devices()
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        device_row.addWidget(self.device_combo)
        
        self.refresh_devices_button = QPushButton("⟳")
        self.refresh_devices_button.setToolTip("Refresh device list")
        self.refresh_devices_button.setFixedSize(46, 46)
        self.refresh_devices_button.setStyleSheet("""
            QPushButton {
                background-color: #1a1f1a;
                border: 1px solid #2d3d2d;
                border-radius: 10px;
                font-size: 18px;
                color: #94a3b8;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #1f2a1f;
                border-color: #3b82f6;
                color: #3b82f6;
            }
        """)
        self.refresh_devices_button.clicked.connect(self._refresh_devices)
        device_row.addWidget(self.refresh_devices_button)
        
        camera_layout.addLayout(device_row)
        
        # Resolution
        res_text = QLabel("Resolution")
        res_text.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent;")
        camera_layout.addWidget(res_text)
        
        self.resolution_combo = QComboBox()
        self.resolution_combo.currentIndexChanged.connect(self._on_resolution_changed)
        camera_layout.addWidget(self.resolution_combo)
        
        # Frame Rate
        fps_text = QLabel("Frame Rate")
        fps_text.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent;")
        camera_layout.addWidget(fps_text)
        
        self.fps_combo = QComboBox()
        self.fps_combo.currentIndexChanged.connect(self._on_fps_changed)
        camera_layout.addWidget(self.fps_combo)
        
        layout.addWidget(camera_card)

        layout.addStretch()

        # Quit Button
        self.quit_button = QPushButton("Quit")
        self.quit_button.setStyleSheet("""
            QPushButton {
                background-color: #1a1515;
                border: 1px solid #3d2d2d;
                color: #ef4444;
                border-radius: 10px;
                padding: 14px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2d1f1f;
                border-color: #4d3d3d;
            }
        """)
        self.quit_button.clicked.connect(self._on_quit)
        layout.addWidget(self.quit_button)

    def _populate_devices(self):
        """Populate the device combo box."""
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        devices = get_video_devices()
        for path, name in devices:
            self.device_combo.addItem(f"{name}  ({path})", path)
        self.device_combo.blockSignals(False)

    def _refresh_devices(self):
        """Refresh the list of video devices."""
        current = self.device_combo.currentData()
        self._populate_devices()
        # Try to restore selection
        for i in range(self.device_combo.count()):
            if self.device_combo.itemData(i) == current:
                self.device_combo.setCurrentIndex(i)
                break

    def _resolution_sort_key(self, res: str) -> Tuple[int, int]:
        try:
            width, height = map(int, res.split("x"))
            return width, height
        except (ValueError, AttributeError):
            return (0, 0)

    def _set_combo_by_data(self, combo: QComboBox, data) -> bool:
        combo.blockSignals(True)
        index = combo.findData(data)
        if index >= 0:
            combo.setCurrentIndex(index)
            combo.blockSignals(False)
            return True
        combo.blockSignals(False)
        return False

    def _refresh_supported_formats(self):
        device = self.settings.get("input_device")
        if not device or not Path(device).exists():
            devices = get_video_devices()
            if devices:
                device = devices[0][0]
                self.settings.set("input_device", device)
            else:
                device = "/dev/video0"

        formats = get_supported_formats(device)
        self.supported_formats = formats if formats else DEFAULT_SUPPORTED_FORMATS.copy()

    def _populate_resolution_combo(self, preferred_res: Optional[str] = None) -> Optional[str]:
        if not self.supported_formats:
            return None

        resolutions = sorted(self.supported_formats.keys(), key=self._resolution_sort_key)
        self.resolution_combo.blockSignals(True)
        self.resolution_combo.clear()
        for res in resolutions:
            self.resolution_combo.addItem(res, res)
        self.resolution_combo.blockSignals(False)

        target_res = preferred_res if preferred_res in self.supported_formats else resolutions[0]
        self._set_combo_by_data(self.resolution_combo, target_res)
        return target_res

    def _populate_fps_combo(self, res: str, preferred_fps: Optional[int] = None) -> Optional[int]:
        fps_values = self.supported_formats.get(res, [])
        if not fps_values:
            self.fps_combo.blockSignals(True)
            self.fps_combo.clear()
            self.fps_combo.blockSignals(False)
            return None

        self.fps_combo.blockSignals(True)
        self.fps_combo.clear()
        for fps in fps_values:
            self.fps_combo.addItem(f"{fps} fps", fps)
        self.fps_combo.blockSignals(False)

        target_fps = preferred_fps if preferred_fps in fps_values else fps_values[0]
        self._set_combo_by_data(self.fps_combo, target_fps)
        return target_fps

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("""
            font-size: 11px;
            font-weight: 700;
            color: #64748b;
            letter-spacing: 1.5px;
            background: transparent;
            border: none;
        """)
        return label

    def _apply_settings(self):
        # Apply effect mode
        effect_mode = self.settings.get("effect_mode")
        if effect_mode in self.effect_buttons:
            self.effect_buttons[effect_mode].setChecked(True)
        else:
            self.effect_buttons["blur"].setChecked(True)
        
        # Apply blur strength
        self.blur_slider.setValue(self.settings.get("blur_strength"))
        
        # Apply vcam state
        self.vcam_running = self.settings.get("vcam_enabled")
        self._update_vcam_button()
        
        # Apply background image
        bg_path = self.settings.get("background_image")
        if bg_path and Path(bg_path).exists():
            self.bg_label.setText(Path(bg_path).name)
            self.bg_label.setStyleSheet("color: #e2e8f0; font-size: 12px; background: transparent;")
        
        # Apply input device
        saved_device = self.settings.get("input_device")
        if saved_device:
            self._set_combo_by_data(self.device_combo, saved_device)
        
        # Apply resolution
        self._refresh_supported_formats()
        saved_res = self.settings.get("resolution")
        selected_res = self._populate_resolution_combo(saved_res)
        saved_fps = self.settings.get("fps")
        selected_fps = None
        if selected_res:
            selected_fps = self._populate_fps_combo(selected_res, saved_fps)
            self.settings.set("resolution", selected_res)
        if selected_fps is not None:
            self.settings.set("fps", selected_fps)
        
        # Update preview info
        self._update_preview_info()
        
        self._send_all_settings()

    def _update_preview_info(self):
        """Update the resolution/fps info label."""
        res = self.settings.get("resolution")
        fps = self.settings.get("fps")
        self.preview_info.setText(f"{res} @ {fps}fps")

    def _update_vcam_button(self):
        """Update vcam button appearance based on state."""
        if self.vcam_running:
            self.vcam_button.setText("Stop")
            self.vcam_glow.setBlurRadius(20)
            self.vcam_button.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 16px;
                    color: white;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                }
            """)
        else:
            self.vcam_button.setText("Start")
            self.vcam_glow.setBlurRadius(0)
            self.vcam_button.setStyleSheet("""
                QPushButton {
                    background-color: #1f2a1f;
                    border: 1px solid #2d3d2d;
                    border-radius: 8px;
                    padding: 10px 16px;
                    color: #e2e8f0;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #2d3d2d;
                }
            """)

    def _send_all_settings(self):
        effect_mode = self.settings.get("effect_mode")
        mode_index = EFFECT_MAP.get(effect_mode, 6)
        send_command(f"MODE:{mode_index}")
        
        # Send input device
        device = self.settings.get("input_device")
        if device:
            send_command(f"DEVICE:{device}")
        
        bg_path = self.settings.get("background_image")
        if bg_path and Path(bg_path).exists():
            send_command(f"BG:{bg_path}")
        send_command(f"BLUR:{self.settings.get('blur_strength') / 100.0}")
        send_command("VCAM:on" if self.settings.get("vcam_enabled") else "VCAM:off")
        # Enable embedded preview for Qt UI
        send_command("EMBEDDED:on")

    def _on_effect_selected(self, effect_key: str, checked: bool):
        if not checked:
            return
        
        # Animate the effect change on preview
        self._animate_effect_change()
        
        # Update visibility of conditional controls with animation
        self._animate_control_visibility(self.blur_controls, effect_key == "blur")
        self._animate_control_visibility(self.bg_controls, effect_key == "replace")
        
        # Send command and save
        mode_index = EFFECT_MAP.get(effect_key, 6)
        send_command(f"MODE:{mode_index}")
        self.settings.set("effect_mode", effect_key)

    def _animate_effect_change(self):
        """Animate the preview when changing effects."""
        if hasattr(self, "_fade_anim") and self._fade_anim.state() == QAbstractAnimation.Running:
            self._fade_anim.stop()

        opacity_effect = QGraphicsOpacityEffect(self.preview_container)
        self.preview_container.setGraphicsEffect(opacity_effect)

        # Fade out and back in
        self._fade_anim = QPropertyAnimation(opacity_effect, b"opacity")
        self._fade_anim.setDuration(300)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setKeyValueAt(0.5, 0.6)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade_anim.finished.connect(lambda: self.preview_container.setGraphicsEffect(None))
        self._fade_anim.start()

    def _animate_control_visibility(self, widget, show: bool):
        """Animate showing/hiding of control widgets."""
        if hasattr(widget, "_show_anim") and widget._show_anim.state() == QAbstractAnimation.Running:
            widget._show_anim.stop()

        if show:
            widget.setVisible(True)
            opacity_effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(opacity_effect)
            opacity_effect.setOpacity(0.0)

            anim = QPropertyAnimation(opacity_effect, b"opacity")
            anim.setDuration(200)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutQuad)
            widget._show_anim = anim  # Keep reference
            anim.finished.connect(lambda: widget.setGraphicsEffect(None))
            anim.start()
        else:
            widget.setGraphicsEffect(None)
            widget.setVisible(False)

    def _on_select_background(self):
        start_dir = "/host_home" if Path("/host_home").exists() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Background Image", start_dir,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self.bg_label.setText(Path(path).name)
            self.bg_label.setStyleSheet("color: #e2e8f0; font-size: 12px; background: transparent;")
            send_command(f"BG:{path}")
            self.settings.set("background_image", path)

    def _on_blur_changed(self, value):
        self.blur_value_label.setText(f"{value}%")
        send_command(f"BLUR:{value / 100.0}")
        self.settings.set("blur_strength", value)

    def _on_vcam_clicked(self):
        self.vcam_running = not self.vcam_running
        send_command("VCAM:on" if self.vcam_running else "VCAM:off")
        self.settings.set("vcam_enabled", self.vcam_running)
        self._update_vcam_button()

    def _on_device_changed(self, index):
        if index >= 0:
            device = self.device_combo.itemData(index)
            send_command(f"DEVICE:{device}")
            self.settings.set("input_device", device)
            self._refresh_supported_formats()
            selected_res = self._populate_resolution_combo(self.settings.get("resolution"))
            selected_fps = None
            if selected_res:
                selected_fps = self._populate_fps_combo(selected_res, self.settings.get("fps"))
                self.settings.set("resolution", selected_res)
                send_command(f"RESOLUTION:{selected_res}")
            if selected_fps is not None:
                self.settings.set("fps", selected_fps)
                send_command(f"FPS:{selected_fps}")
            self._update_preview_info()

    def _on_resolution_changed(self, index):
        res = self.resolution_combo.itemData(index)
        if not res:
            return
        previous_fps = self.settings.get("fps")
        self.settings.set("resolution", res)
        selected_fps = self._populate_fps_combo(res, previous_fps)
        send_command(f"RESOLUTION:{res}")
        if selected_fps is not None and selected_fps != previous_fps:
            self.settings.set("fps", selected_fps)
            send_command(f"FPS:{selected_fps}")
        self._update_preview_info()

    def _on_fps_changed(self, index):
        fps = self.fps_combo.itemData(index)
        if fps is None:
            return
        send_command(f"FPS:{fps}")
        self.settings.set("fps", fps)
        self._update_preview_info()

    def _on_quit(self):
        send_command("QUIT")
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    
    # Dark theme palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#0a0f0a"))
    palette.setColor(QPalette.WindowText, QColor("#e2e8f0"))
    palette.setColor(QPalette.Base, QColor("#111611"))
    palette.setColor(QPalette.AlternateBase, QColor("#1a1f1a"))
    palette.setColor(QPalette.Text, QColor("#e2e8f0"))
    palette.setColor(QPalette.Button, QColor("#1a1f1a"))
    palette.setColor(QPalette.ButtonText, QColor("#94a3b8"))
    palette.setColor(QPalette.Highlight, QColor("#3b82f6"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    
    # Set application icon
    if Path(LOGO_PATH).exists():
        app.setWindowIcon(QIcon(LOGO_PATH))
    
    window = ControlPanel()
    window.setWindowIcon(QIcon(LOGO_PATH) if Path(LOGO_PATH).exists() else QIcon())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
