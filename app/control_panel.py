#!/usr/bin/env python3

import sys
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSlider, QFrame, QFileDialog,
    QGraphicsDropShadowEffect, QScrollArea, QSizePolicy,
    QSystemTrayIcon, QMenu
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QIcon, QPixmap, QPainter, QAction

CMD_PIPE = "/tmp/videofx/videofx_cmd"
CONFIG_DIR = Path("/root/.config/videofx")
CONFIG_FILE = CONFIG_DIR / "settings.json"

EFFECT_MODES = [
    "Show Mask Only",
    "Light Overlay",
    "Green Screen",
    "White Background",
    "Original (No Effect)",
    "Custom Background",
    "Blur Background",
    "Denoise",
]

STYLESHEET = """
QMainWindow {
    background-color: #1a1a2e;
}
QWidget {
    color: #eaeaea;
    font-family: 'Segoe UI', 'SF Pro Display', 'Helvetica Neue', sans-serif;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QLabel {
    color: #eaeaea;
}
QComboBox {
    background-color: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 14px;
    min-height: 20px;
}
QComboBox:hover {
    border-color: #4a4a8a;
}
QComboBox:focus {
    border-color: #6366f1;
}
QComboBox::drop-down {
    border: none;
    width: 30px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #888888;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    background-color: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    selection-background-color: #4a4a8a;
    padding: 4px;
}
QPushButton {
    background-color: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    padding: 12px 24px;
    font-size: 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #1f2b4a;
    border-color: #4a4a8a;
}
QPushButton:pressed {
    background-color: #0f1629;
}
QSlider::groove:horizontal {
    background-color: #2a2a4a;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background-color: #6366f1;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    background-color: #818cf8;
}
QSlider::sub-page:horizontal {
    background-color: #6366f1;
    border-radius: 3px;
}
"""


class Settings:
    DEFAULT = {
        "effect_mode": 5,
        "background_image": "",
        "blur_strength": 50,
        "output_fps": 30,
        "vcam_enabled": True,
        "preview_enabled": False,
        "overlay_enabled": False,
        "resolution": "1280x720",
        "fps": 30,
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


def send_command(cmd):
    try:
        with open(CMD_PIPE, 'w') as f:
            f.write(cmd + '\n')
        return True
    except OSError:
        return False


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setStyleSheet("QFrame[class='card'] { background-color: #16213e; border-radius: 12px; }")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)


class ToggleButton(QPushButton):
    def __init__(self, text_on, text_off, parent=None):
        super().__init__(parent)
        self.text_on = text_on
        self.text_off = text_off
        self.setCheckable(True)
        self.setProperty("class", "toggle")
        self.toggled.connect(self._update_text)
        self._update_text(self.isChecked())

    def _update_text(self, checked):
        self.setText(self.text_on if checked else self.text_off)


class ControlPanel(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.setWindowTitle("VideoFX Studio")
        self.setMinimumSize(400, 600)
        self.resize(420, 650)
        self._build_ui()
        self._setup_tray()
        self._apply_settings()

    def _create_tray_icon(self):
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(0, 168, 107))
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
        self.tray_icon.setToolTip("VideoFX Studio")
        tray_menu = QMenu()
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self._show_window)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        vcam_action = QAction("Toggle Virtual Camera", self)
        vcam_action.triggered.connect(lambda: self.vcam_toggle.toggle())
        tray_menu.addAction(vcam_action)
        tray_menu.addSeparator()
        quit_action = QAction("Quit VideoFX", self)
        quit_action.triggered.connect(self._on_quit)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_window()

    def closeEvent(self, event):
        if hasattr(self, 'tray_available') and self.tray_available and self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            self._on_quit()
            event.accept()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)
        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("VideoFX Studio")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        header.addWidget(title)
        subtitle = QLabel("AI-powered video effects • Virtual camera ready")
        subtitle.setStyleSheet("color: #22c55e; font-size: 13px;")
        header.addWidget(subtitle)
        layout.addLayout(header)
        layout.addSpacing(8)

        layout.addWidget(self._section_label("BACKGROUND EFFECT"))
        effect_card = Card()
        effect_layout = QVBoxLayout(effect_card)
        effect_layout.setContentsMargins(16, 16, 16, 16)
        effect_layout.setSpacing(12)
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(EFFECT_MODES)
        self.effect_combo.currentIndexChanged.connect(self._on_effect_changed)
        effect_layout.addWidget(self.effect_combo)
        bg_row = QHBoxLayout()
        self.bg_label = QLabel("No image selected")
        self.bg_label.setStyleSheet("color: #888888; font-size: 13px;")
        self.bg_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bg_row.addWidget(self.bg_label)
        self.bg_button = QPushButton("Browse...")
        self.bg_button.clicked.connect(self._on_select_background)
        bg_row.addWidget(self.bg_button)
        effect_layout.addLayout(bg_row)
        layout.addWidget(effect_card)

        layout.addWidget(self._section_label("BLUR STRENGTH"))
        blur_card = Card()
        blur_layout = QVBoxLayout(blur_card)
        blur_layout.setContentsMargins(16, 16, 16, 16)
        blur_layout.setSpacing(8)
        blur_row = QHBoxLayout()
        self.blur_slider = QSlider(Qt.Horizontal)
        self.blur_slider.setRange(0, 100)
        self.blur_slider.valueChanged.connect(self._on_blur_changed)
        blur_row.addWidget(self.blur_slider)
        self.blur_label = QLabel("50%")
        self.blur_label.setMinimumWidth(45)
        self.blur_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        blur_row.addWidget(self.blur_label)
        blur_layout.addLayout(blur_row)
        layout.addWidget(blur_card)

        layout.addWidget(self._section_label("OUTPUT"))
        output_card = Card()
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(16, 16, 16, 16)
        output_layout.setSpacing(12)
        output_fps_row = QHBoxLayout()
        output_fps_label = QLabel("Output FPS:")
        output_fps_label.setMinimumWidth(100)
        output_fps_row.addWidget(output_fps_label)
        self.output_fps_combo = QComboBox()
        self.output_fps_combo.addItems(["15 fps", "24 fps", "30 fps", "60 fps"])
        self.output_fps_combo.setCurrentIndex(2)
        self.output_fps_combo.currentIndexChanged.connect(self._on_output_fps_changed)
        output_fps_row.addWidget(self.output_fps_combo, 1)
        output_layout.addLayout(output_fps_row)
        self.vcam_toggle = ToggleButton("Virtual Camera: ON", "Virtual Camera: OFF")
        self.vcam_toggle.toggled.connect(self._on_vcam_toggled)
        output_layout.addWidget(self.vcam_toggle)
        vcam_info = QLabel("/dev/video10 • Use in Zoom, Meet, OBS")
        vcam_info.setStyleSheet("color: #666666; font-size: 12px;")
        output_layout.addWidget(vcam_info)
        layout.addWidget(output_card)

        layout.addWidget(self._section_label("CAMERA"))
        camera_card = Card()
        camera_layout = QVBoxLayout(camera_card)
        camera_layout.setContentsMargins(16, 16, 16, 16)
        camera_layout.setSpacing(12)
        res_row = QHBoxLayout()
        res_label = QLabel("Resolution:")
        res_label.setMinimumWidth(80)
        res_row.addWidget(res_label)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems([
            "640x480 (VGA)",
            "1280x720 (HD)",
            "1920x1080 (FHD)",
            "2560x1440 (QHD)",
            "3840x2160 (4K)"
        ])
        self.resolution_combo.currentIndexChanged.connect(self._on_resolution_changed)
        res_row.addWidget(self.resolution_combo, 1)
        camera_layout.addLayout(res_row)
        fps_row = QHBoxLayout()
        fps_label = QLabel("Frame Rate:")
        fps_label.setMinimumWidth(80)
        fps_row.addWidget(fps_label)
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["15 fps", "24 fps", "30 fps", "60 fps"])
        self.fps_combo.currentIndexChanged.connect(self._on_fps_changed)
        fps_row.addWidget(self.fps_combo, 1)
        camera_layout.addLayout(fps_row)
        camera_info = QLabel("Camera will restart when changed")
        camera_info.setStyleSheet("color: #666666; font-size: 11px;")
        camera_layout.addWidget(camera_info)
        layout.addWidget(camera_card)

        layout.addWidget(self._section_label("DISPLAY"))
        display_card = Card()
        display_layout = QVBoxLayout(display_card)
        display_layout.setContentsMargins(16, 16, 16, 16)
        display_layout.setSpacing(12)
        self.preview_toggle = ToggleButton("Preview Window: ON", "Preview Window: OFF")
        self.preview_toggle.toggled.connect(self._on_preview_toggled)
        display_layout.addWidget(self.preview_toggle)
        self.overlay_toggle = ToggleButton("Overlay Text: ON", "Overlay Text: OFF")
        self.overlay_toggle.toggled.connect(self._on_overlay_toggled)
        display_layout.addWidget(self.overlay_toggle)
        layout.addWidget(display_card)

        layout.addStretch()

        self.quit_button = QPushButton("Quit VideoFX")
        self.quit_button.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                border: none;
                color: white;
                border-radius: 8px;
                padding: 14px;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
        """)
        self.quit_button.clicked.connect(self._on_quit)
        layout.addWidget(self.quit_button)

        footer = QLabel("Press Q or ESC in preview window to quit")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color: #555555; font-size: 11px; margin-top: 8px;")
        layout.addWidget(footer)

    def _section_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-size: 11px; font-weight: bold; color: #888888; letter-spacing: 1px;")
        return label

    def _apply_settings(self):
        self.effect_combo.setCurrentIndex(self.settings.get("effect_mode"))
        self.blur_slider.setValue(self.settings.get("blur_strength"))
        self.vcam_toggle.setChecked(self.settings.get("vcam_enabled"))
        self.preview_toggle.setChecked(self.settings.get("preview_enabled"))
        self.overlay_toggle.setChecked(self.settings.get("overlay_enabled"))
        output_fps = self.settings.get("output_fps")
        fps_map = {15: 0, 24: 1, 30: 2, 60: 3}
        self.output_fps_combo.setCurrentIndex(fps_map.get(output_fps, 2))
        bg_path = self.settings.get("background_image")
        if bg_path and Path(bg_path).exists():
            self.bg_label.setText(Path(bg_path).name)
            self.bg_label.setStyleSheet("color: #eaeaea; font-size: 13px;")
        self._send_all_settings()
        saved_res = self.settings.get("resolution")
        res_map = {"640x480": 0, "1280x720": 1, "1920x1080": 2, "2560x1440": 3, "3840x2160": 4}
        self.resolution_combo.setCurrentIndex(res_map.get(saved_res, 1))
        saved_fps = self.settings.get("fps")
        self.fps_combo.setCurrentIndex(fps_map.get(saved_fps, 2))

    def _send_all_settings(self):
        send_command(f"MODE:{self.settings.get('effect_mode')}")
        bg_path = self.settings.get("background_image")
        if bg_path and Path(bg_path).exists():
            send_command(f"BG:{bg_path}")
        send_command(f"BLUR:{self.settings.get('blur_strength') / 100.0}")
        send_command(f"OUTPUT_FPS:{self.settings.get('output_fps')}")
        send_command("VCAM:on" if self.settings.get("vcam_enabled") else "VCAM:off")
        send_command("PREVIEW:on" if self.settings.get("preview_enabled") else "PREVIEW:off")
        send_command("OVERLAY:on" if self.settings.get("overlay_enabled") else "OVERLAY:off")

    def _on_effect_changed(self, index):
        send_command(f"MODE:{index}")
        self.settings.set("effect_mode", index)

    def _on_select_background(self):
        start_dir = "/host_home" if Path("/host_home").exists() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Background Image", start_dir,
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.bg_label.setText(Path(path).name)
            self.bg_label.setStyleSheet("color: #eaeaea; font-size: 13px;")
            send_command(f"BG:{path}")
            self.settings.set("background_image", path)
            self.effect_combo.setCurrentIndex(5)

    def _on_blur_changed(self, value):
        self.blur_label.setText(f"{value}%")
        send_command(f"BLUR:{value / 100.0}")
        self.settings.set("blur_strength", value)

    def _on_output_fps_changed(self, index):
        fps_values = [15, 24, 30, 60]
        if 0 <= index < len(fps_values):
            fps = fps_values[index]
            send_command(f"OUTPUT_FPS:{fps}")
            self.settings.set("output_fps", fps)

    def _on_vcam_toggled(self, checked):
        send_command("VCAM:on" if checked else "VCAM:off")
        self.settings.set("vcam_enabled", checked)

    def _on_preview_toggled(self, checked):
        send_command("PREVIEW:on" if checked else "PREVIEW:off")
        self.settings.set("preview_enabled", checked)

    def _on_overlay_toggled(self, checked):
        send_command("OVERLAY:on" if checked else "OVERLAY:off")
        self.settings.set("overlay_enabled", checked)

    def _on_resolution_changed(self, index):
        resolutions = ["640x480", "1280x720", "1920x1080", "2560x1440", "3840x2160"]
        if 0 <= index < len(resolutions):
            res = resolutions[index]
            send_command(f"RESOLUTION:{res}")
            self.settings.set("resolution", res)

    def _on_fps_changed(self, index):
        fps_values = [15, 24, 30, 60]
        if 0 <= index < len(fps_values):
            fps = fps_values[index]
            send_command(f"FPS:{fps}")
            self.settings.set("fps", fps)

    def _on_quit(self):
        send_command("QUIT")
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#1a1a2e"))
    palette.setColor(QPalette.WindowText, QColor("#eaeaea"))
    palette.setColor(QPalette.Base, QColor("#16213e"))
    palette.setColor(QPalette.AlternateBase, QColor("#1a1a2e"))
    palette.setColor(QPalette.Text, QColor("#eaeaea"))
    palette.setColor(QPalette.Button, QColor("#16213e"))
    palette.setColor(QPalette.ButtonText, QColor("#eaeaea"))
    palette.setColor(QPalette.Highlight, QColor("#6366f1"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    window = ControlPanel()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
