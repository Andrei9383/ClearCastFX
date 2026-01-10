#!/usr/bin/env python3
"""
VideoFX Control Panel
A PyQt5 GUI that sends commands to the C++ VideoFX Server
With system tray support for minimized operation
"""

import sys
import os
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QGroupBox, QFileDialog, QSlider,
    QFrame, QSystemTrayIcon, QMenu, QAction, QStyle
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon, QPixmap, QPainter, QColor

# Command pipe path (same as C++ server)
CMD_PIPE = "/tmp/videofx_cmd"


def send_command(cmd):
    """Send a command to the VideoFX server via named pipe"""
    try:
        with open(CMD_PIPE, 'w') as f:
            f.write(cmd + '\n')
            f.flush()
        return True
    except Exception as e:
        print(f"Error sending command: {e}")
        return False


def create_tray_icon():
    """Create a simple colored icon for the system tray"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setBrush(QColor(0, 168, 107))  # Green color
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawEllipse(20, 20, 24, 24)
    painter.end()
    return QIcon(pixmap)


class ControlPanel(QMainWindow):
    """Control panel for VideoFX Server"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VideoFX Control Panel")
        self.setMinimumSize(380, 520)
        
        self.init_ui()
        self.init_tray()
    
    def init_tray(self):
        """Initialize system tray icon"""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_tray_icon())
        self.tray_icon.setToolTip("VideoFX Studio")
        
        # Create tray menu
        tray_menu = QMenu()
        
        show_action = QAction("Show Control Panel", self)
        show_action.triggered.connect(self.show_window)
        tray_menu.addAction(show_action)
        
        hide_action = QAction("Hide Control Panel", self)
        hide_action.triggered.connect(self.hide)
        tray_menu.addAction(hide_action)
        
        tray_menu.addSeparator()
        
        preview_action = QAction("Toggle Preview", self)
        preview_action.triggered.connect(self.toggle_preview)
        tray_menu.addAction(preview_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("Quit VideoFX", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()
    
    def tray_activated(self, reason):
        """Handle tray icon click"""
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_window()
    
    def show_window(self):
        """Show and activate the window"""
        self.show()
        self.activateWindow()
        self.raise_()
    
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Title
        title = QLabel("VideoFX Control Panel")
        title.setFont(QFont("Sans", 14, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Status
        status_label = QLabel("Server running - Video in separate window")
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setStyleSheet("color: green;")
        layout.addWidget(status_label)
        
        # Composition mode
        comp_group = QGroupBox("Background Mode")
        comp_layout = QVBoxLayout(comp_group)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Show Mask Only",
            "Light Overlay",
            "Green Screen",
            "White Background",
            "Original (No Effect)",
            "Custom Background Image",
            "Blur Background"
        ])
        self.mode_combo.setCurrentIndex(5)  # Default to custom background
        self.mode_combo.currentIndexChanged.connect(self.change_mode)
        comp_layout.addWidget(self.mode_combo)
        
        layout.addWidget(comp_group)
        
        # Background selection
        bg_group = QGroupBox("Background Image")
        bg_layout = QVBoxLayout(bg_group)
        
        self.bg_label = QLabel("No background selected")
        self.bg_label.setStyleSheet("color: gray;")
        bg_layout.addWidget(self.bg_label)
        
        self.btn_select_bg = QPushButton("Select Image...")
        self.btn_select_bg.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.btn_select_bg.clicked.connect(self.select_background)
        bg_layout.addWidget(self.btn_select_bg)
        
        layout.addWidget(bg_group)
        
        # Blur strength
        blur_group = QGroupBox("Blur Strength")
        blur_layout = QVBoxLayout(blur_group)
        
        blur_row = QHBoxLayout()
        self.blur_slider = QSlider(Qt.Horizontal)
        self.blur_slider.setRange(0, 100)
        self.blur_slider.setValue(50)
        self.blur_slider.valueChanged.connect(self.change_blur)
        blur_row.addWidget(self.blur_slider)
        
        self.blur_label = QLabel("50%")
        self.blur_label.setMinimumWidth(40)
        blur_row.addWidget(self.blur_label)
        blur_layout.addLayout(blur_row)
        
        layout.addWidget(blur_group)
        
        # Virtual camera
        vcam_group = QGroupBox("Virtual Camera")
        vcam_layout = QVBoxLayout(vcam_group)
        
        self.btn_vcam = QPushButton("Enable Virtual Camera")
        self.btn_vcam.setCheckable(True)
        self.btn_vcam.clicked.connect(self.toggle_vcam)
        vcam_layout.addWidget(self.btn_vcam)
        
        vcam_info = QLabel("Output to /dev/video10 for OBS, Zoom, etc.")
        vcam_info.setStyleSheet("color: gray; font-size: 10px;")
        vcam_layout.addWidget(vcam_info)
        
        layout.addWidget(vcam_group)
        
        # Display options
        display_group = QGroupBox("Display Options")
        display_layout = QVBoxLayout(display_group)
        
        self.btn_preview = QPushButton("Hide Preview Window")
        self.btn_preview.setCheckable(True)
        self.btn_preview.clicked.connect(self.toggle_preview)
        display_layout.addWidget(self.btn_preview)
        
        self.btn_overlay = QPushButton("Hide Overlay Text")
        self.btn_overlay.setCheckable(True)
        self.btn_overlay.clicked.connect(self.toggle_overlay)
        display_layout.addWidget(self.btn_overlay)
        
        self.btn_minimize = QPushButton("Minimize to Tray")
        self.btn_minimize.setIcon(self.style().standardIcon(QStyle.SP_TitleBarMinButton))
        self.btn_minimize.clicked.connect(self.hide)
        display_layout.addWidget(self.btn_minimize)
        
        layout.addWidget(display_group)
        
        layout.addStretch()
        
        # Quit button
        self.btn_quit = QPushButton("Quit VideoFX")
        self.btn_quit.setIcon(self.style().standardIcon(QStyle.SP_DialogCloseButton))
        self.btn_quit.clicked.connect(self.quit_app)
        layout.addWidget(self.btn_quit)
        
        # Info
        info_label = QLabel("Press Q or ESC in video window to quit")
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(info_label)
        
        # Send initial mode
        self.change_mode(5)
    
    def change_mode(self, index):
        send_command(f"MODE:{index}")
    
    def select_background(self):
        # Start in /host_home where host's home directory is mounted
        start_dir = "/host_home"
        if not os.path.exists(start_dir):
            start_dir = ""
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Image",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            self.bg_label.setText(Path(file_path).name)
            self.bg_label.setStyleSheet("")
            send_command(f"BG:{file_path}")
            # Auto-switch to custom background mode
            self.mode_combo.setCurrentIndex(5)
    
    def change_blur(self, value):
        self.blur_label.setText(f"{value}%")
        send_command(f"BLUR:{value / 100.0}")
    
    def toggle_vcam(self):
        if self.btn_vcam.isChecked():
            send_command("VCAM:on")
            self.btn_vcam.setText("Virtual Camera: ON")
        else:
            send_command("VCAM:off")
            self.btn_vcam.setText("Enable Virtual Camera")
    
    def toggle_preview(self):
        if self.btn_preview.isChecked():
            send_command("PREVIEW:off")
            self.btn_preview.setText("Show Preview Window")
        else:
            send_command("PREVIEW:on")
            self.btn_preview.setText("Hide Preview Window")
    
    def toggle_overlay(self):
        if self.btn_overlay.isChecked():
            send_command("OVERLAY:off")
            self.btn_overlay.setText("Show Overlay Text")
        else:
            send_command("OVERLAY:on")
            self.btn_overlay.setText("Hide Overlay Text")
    
    def quit_app(self):
        send_command("QUIT")
        self.tray_icon.hide()
        self.close()
        QApplication.quit()
    
    def closeEvent(self, event):
        # Minimize to tray instead of closing
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "VideoFX Studio",
            "Running in background. Click tray icon to restore.",
            QSystemTrayIcon.Information,
            2000
        )


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Don't quit when window is hidden
    
    # Use Fusion style (modern, consistent look)
    app.setStyle('Fusion')
    
    window = ControlPanel()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
