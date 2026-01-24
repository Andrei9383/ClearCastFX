#!/usr/bin/env python3
"""
VideoFX Control Panel
A modern PySide6 GUI for the VideoFX Server
"""

import sys
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSlider, QFrame, QFileDialog,
    QGraphicsDropShadowEffect, QScrollArea, QSizePolicy,
    QSystemTrayIcon, QMenu
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QPixmap, QPainter, QAction

# Configuration
CMD_PIPE = "/tmp/videofx/videofx_cmd"
CONFIG_DIR = Path("/root/.config/videofx")
CONFIG_FILE = CONFIG_DIR / "settings.json"

# Effect modes
EFFECT_MODES = [
    "Show Mask Only",
    "Light Overlay",
    "Green Screen",
    "White Background",
    "Original (No Effect)",
    "Custom Background",
    "Blur Background",
]

# Modern dark theme stylesheet
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

QLabel[class="title"] {
    font-size: 24px;
    font-weight: bold;
    color: #ffffff;
}

QLabel[class="subtitle"] {
    font-size: 13px;
    color: #888888;
}

QLabel[class="section"] {
    font-size: 11px;
    font-weight: bold;
    color: #888888;
    text-transform: uppercase;
    letter-spacing: 1px;
}

QFrame[class="card"] {
    background-color: #16213e;
    border-radius: 12px;
    padding: 16px;
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

QPushButton[class="primary"] {
    background-color: #6366f1;
    border: none;
    color: white;
}

QPushButton[class="primary"]:hover {
    background-color: #5558e3;
}

QPushButton[class="danger"] {
    background-color: #dc2626;
    border: none;
    color: white;
}

QPushButton[class="danger"]:hover {
    background-color: #b91c1c;
}

QPushButton[class="toggle"] {
    background-color: #2a2a4a;
}

QPushButton[class="toggle"]:checked {
    background-color: #6366f1;
    border-color: #6366f1;
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
    """Handles loading and saving application settings."""
    
    DEFAULT = {
        "effect_mode": 5,
        "background_image": "",
        "blur_strength": 50,
        "vcam_enabled": True,
        "preview_enabled": False,
        "overlay_enabled": False,
    }
    
    def __init__(self):
        self._data = self.DEFAULT.copy()
        self._load()
    
    def _load(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE) as f:
                    saved = json.load(f)
                    self._data.update(saved)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Could not load settings: {e}")
    
    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            print(f"Warning: Could not save settings: {e}")
    
    def get(self, key):
        return self._data.get(key, self.DEFAULT.get(key))
    
    def set(self, key, value):
        self._data[key] = value
        self.save()


def send_command(cmd):
    """Send a command to the VideoFX server via named pipe."""
    try:
        with open(CMD_PIPE, 'w') as f:
            f.write(cmd + '\n')
        return True
    except OSError as e:
        print(f"Error sending command: {e}")
        return False


class Card(QFrame):
    """A styled card container."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setStyleSheet("QFrame[class='card'] { background-color: #16213e; border-radius: 12px; }")
        
        # Add subtle shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)


class ToggleButton(QPushButton):
    """A modern toggle button."""
    
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
    """Main control panel window."""
    
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.setWindowTitle("VideoFX Studio")
        self.setMinimumSize(400, 650)
        self.resize(420, 700)
        
        self._build_ui()
        self._setup_tray()
        self._apply_settings()
    
    def _create_tray_icon(self):
        """Create a simple tray icon programmatically."""
        # Create a 64x64 icon - green circle with white center (like the old version)
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw outer circle (green)
        painter.setBrush(QColor(0, 168, 107))  # Green color
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, 4, 56, 56)
        
        # Draw white inner circle
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(20, 20, 24, 24)
        
        painter.end()
        return QIcon(pixmap)
    
    def _setup_tray(self):
        """Setup the system tray icon and menu."""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_notified = False  # Only show notification once
        
        # Check if system tray is available
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("Warning: System tray not available on this desktop")
            self.tray_available = False
            return
        
        self.tray_available = True
        self.tray_icon.setIcon(self._create_tray_icon())
        self.tray_icon.setToolTip("VideoFX Studio")
        
        # Create tray menu
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
        print("System tray icon enabled")
    
    def _show_window(self):
        """Show and raise the main window."""
        self.show()
        self.raise_()
        self.activateWindow()
    
    def _on_tray_activated(self, reason):
        """Handle tray icon activation (click)."""
        if reason == QSystemTrayIcon.Trigger:  # Single click
            if self.isVisible():
                self.hide()
            else:
                self._show_window()
    
    def closeEvent(self, event):
        """Override close event to minimize to tray instead of quitting."""
        if hasattr(self, 'tray_available') and self.tray_available and self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            # No tray available, quit properly
            self._on_quit()
            event.accept()
    
    def _build_ui(self):
        # Central widget with scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)
        
        container = QWidget()
        scroll.setWidget(container)
        
        layout = QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        header = QVBoxLayout()
        header.setSpacing(4)
        
        title = QLabel("VideoFX Studio")
        title.setProperty("class", "title")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        header.addWidget(title)
        
        subtitle = QLabel("AI-powered video effects • Virtual camera ready")
        subtitle.setProperty("class", "subtitle")
        subtitle.setStyleSheet("color: #22c55e; font-size: 13px;")
        header.addWidget(subtitle)
        
        layout.addLayout(header)
        layout.addSpacing(8)
        
        # Effect mode section
        layout.addWidget(self._section_label("BACKGROUND EFFECT"))
        
        effect_card = Card()
        effect_layout = QVBoxLayout(effect_card)
        effect_layout.setContentsMargins(16, 16, 16, 16)
        effect_layout.setSpacing(12)
        
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(EFFECT_MODES)
        self.effect_combo.currentIndexChanged.connect(self._on_effect_changed)
        effect_layout.addWidget(self.effect_combo)
        
        # Background image row
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
        
        # Blur section
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
        
        # Output section
        layout.addWidget(self._section_label("OUTPUT"))
        
        output_card = Card()
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(16, 16, 16, 16)
        output_layout.setSpacing(12)
        
        self.vcam_toggle = ToggleButton("Virtual Camera: ON", "Virtual Camera: OFF")
        self.vcam_toggle.toggled.connect(self._on_vcam_toggled)
        output_layout.addWidget(self.vcam_toggle)
        
        vcam_info = QLabel("/dev/video10 • Use in Zoom, Meet, OBS")
        vcam_info.setStyleSheet("color: #666666; font-size: 12px;")
        output_layout.addWidget(vcam_info)
        
        layout.addWidget(output_card)
        
        # Display section
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
        
        # Quit button
        self.quit_button = QPushButton("Quit VideoFX")
        self.quit_button.setProperty("class", "danger")
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
        
        # Footer
        footer = QLabel("Press Q or ESC in preview window to quit")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color: #555555; font-size: 11px; margin-top: 8px;")
        layout.addWidget(footer)
    
    def _section_label(self, text):
        label = QLabel(text)
        label.setProperty("class", "section")
        label.setStyleSheet("font-size: 11px; font-weight: bold; color: #888888; letter-spacing: 1px;")
        return label
    
    def _apply_settings(self):
        """Apply saved settings to UI and server."""
        self.effect_combo.setCurrentIndex(self.settings.get("effect_mode"))
        self.blur_slider.setValue(self.settings.get("blur_strength"))
        self.vcam_toggle.setChecked(self.settings.get("vcam_enabled"))
        self.preview_toggle.setChecked(self.settings.get("preview_enabled"))
        self.overlay_toggle.setChecked(self.settings.get("overlay_enabled"))
        
        bg_path = self.settings.get("background_image")
        if bg_path and Path(bg_path).exists():
            self.bg_label.setText(Path(bg_path).name)
            self.bg_label.setStyleSheet("color: #eaeaea; font-size: 13px;")
        
        # Send all settings to server
        self._send_all_settings()
    
    def _send_all_settings(self):
        send_command(f"MODE:{self.settings.get('effect_mode')}")
        
        bg_path = self.settings.get("background_image")
        if bg_path and Path(bg_path).exists():
            send_command(f"BG:{bg_path}")
        
        send_command(f"BLUR:{self.settings.get('blur_strength') / 100.0}")
        send_command("VCAM:on" if self.settings.get("vcam_enabled") else "VCAM:off")
        send_command("PREVIEW:on" if self.settings.get("preview_enabled") else "PREVIEW:off")
        send_command("OVERLAY:on" if self.settings.get("overlay_enabled") else "OVERLAY:off")
    
    def _on_effect_changed(self, index):
        send_command(f"MODE:{index}")
        self.settings.set("effect_mode", index)
    
    def _on_select_background(self):
        start_dir = "/host_home"
        if not Path(start_dir).exists():
            start_dir = ""
        
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Image",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        
        if path:
            self.bg_label.setText(Path(path).name)
            self.bg_label.setStyleSheet("color: #eaeaea; font-size: 13px;")
            send_command(f"BG:{path}")
            self.settings.set("background_image", path)
            self.effect_combo.setCurrentIndex(5)  # Switch to custom background
    
    def _on_blur_changed(self, value):
        self.blur_label.setText(f"{value}%")
        send_command(f"BLUR:{value / 100.0}")
        self.settings.set("blur_strength", value)
    
    def _on_vcam_toggled(self, checked):
        send_command("VCAM:on" if checked else "VCAM:off")
        self.settings.set("vcam_enabled", checked)
    
    def _on_preview_toggled(self, checked):
        send_command("PREVIEW:on" if checked else "PREVIEW:off")
        self.settings.set("preview_enabled", checked)
    
    def _on_overlay_toggled(self, checked):
        send_command("OVERLAY:on" if checked else "OVERLAY:off")
        self.settings.set("overlay_enabled", checked)
    
    def _on_quit(self):
        send_command("QUIT")
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running when window is hidden
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    
    # Set dark palette
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
