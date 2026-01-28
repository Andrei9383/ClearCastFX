#!/usr/bin/env python3
"""
VideoFX UI - Webcam Effects Application
A PyQt5 GUI for NVIDIA VideoFX SDK with virtual camera output
"""

import sys
import subprocess
import threading
import queue
from pathlib import Path
import os

import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QGroupBox, QFileDialog, QSlider,
    QCheckBox, QStatusBar, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QImage, QPixmap, QFont

# VideoFX SDK paths
VFX_MODELS = "/usr/local/VideoFX/lib/models"
VFX_LIB = "/usr/local/VideoFX/lib"

# Effect executables (built from samples)
AIGS_APP = "/home/andrei/ubuntu-samples/AigsEffectApp/AigsEffectApp"
DENOISE_APP = "/home/andrei/ubuntu-samples/DenoiseEffectApp/DenoiseEffectApp"
VIDEO_EFFECTS_APP = "/home/andrei/ubuntu-samples/VideoEffectsApp/VideoEffectsApp"


class VideoThread(QThread):
    """Thread for capturing and processing video frames"""
    frame_ready = pyqtSignal(np.ndarray)
    error_signal = pyqtSignal(str)
    
    def __init__(self, camera_id=0):
        super().__init__()
        self.camera_id = camera_id
        self.running = False
        self.effect = None
        self.effect_mode = 0
        self.virtual_cam_enabled = False
        self.virtual_cam = None
        self.background_image = None
        self.background_path = None
        self.frame_skip = 10  # Process every Nth frame for performance (higher = faster but choppier effects)
        self.last_processed = None  # Cache last processed frame
        
    def run(self):
        self.running = True
        cap = cv2.VideoCapture(self.camera_id)
        
        if not cap.isOpened():
            self.error_signal.emit(f"Cannot open camera {self.camera_id}")
            return
        
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)
        
        frame_count = 0
        while self.running:
            ret, frame = cap.read()
            if ret:
                frame_count += 1
                
                # Apply effect with frame skipping for performance
                if self.effect is not None:
                    # Only process every Nth frame, use cached result otherwise
                    if frame_count % self.frame_skip == 0 or self.last_processed is None:
                        processed = self.apply_effect(frame)
                        self.last_processed = processed
                    else:
                        # Use cached result but show current frame if no cache
                        processed = self.last_processed if self.last_processed is not None else frame
                else:
                    processed = frame
                    self.last_processed = None
                
                # Send to virtual camera if enabled
                if self.virtual_cam_enabled and self.virtual_cam:
                    try:
                        self.virtual_cam.schedule_frame(
                            cv2.cvtColor(processed, cv2.COLOR_BGR2RGB)
                        )
                    except:
                        pass
                
                self.frame_ready.emit(processed)
            else:
                if frame_count == 0:
                    self.error_signal.emit("Camera not providing frames")
                    break
            
        cap.release()
    
    def apply_effect(self, frame):
        """Apply the selected effect to the frame using VideoFX SDK"""
        if self.effect is None:
            return frame
        
        try:
            # Save frame to temp file
            input_path = "/tmp/videofx_frames/input.png"
            output_path = "/tmp/videofx_frames/output.png"
            cv2.imwrite(input_path, frame)
            
            # Build command based on effect type
            cmd = None
            model_dir = "/usr/local/VideoFX/lib/models"
            
            if self.effect == "green_screen":
                # AI Green Screen (AIGS)
                aigs_app = "/build/samples/AigsEffectApp/AigsEffectApp"
                cmd = [aigs_app, 
                       f"--model_dir={model_dir}",
                       f"--in_file={input_path}",
                       f"--out_file={output_path}",
                       f"--mode={self.effect_mode}"]
                # Add background image if selected
                if self.background_path and os.path.exists(self.background_path):
                    cmd.append(f"--bg_file={self.background_path}")
                       
            elif self.effect == "denoise":
                # Video Denoise
                denoise_app = "/build/samples/DenoiseEffectApp/DenoiseEffectApp"
                cmd = [denoise_app,
                       f"--model_dir={model_dir}",
                       f"--in_file={input_path}",
                       f"--out_file={output_path}",
                       "--strength=1.0"]
                       
            elif self.effect == "superres":
                # Super Resolution
                effects_app = "/build/samples/VideoEffectsApp/VideoEffectsApp"
                cmd = [effects_app,
                       f"--model_dir={model_dir}",
                       f"--in_file={input_path}",
                       f"--out_file={output_path}",
                       "--effect=SuperRes",
                       "--resolution=1080",
                       f"--mode={self.effect_mode}"]
                       
            elif self.effect == "artifact":
                # Artifact Reduction
                effects_app = "/build/samples/VideoEffectsApp/VideoEffectsApp"
                cmd = [effects_app,
                       f"--model_dir={model_dir}",
                       f"--in_file={input_path}",
                       f"--out_file={output_path}",
                       "--effect=ArtifactReduction",
                       f"--mode={self.effect_mode}"]
            
            if cmd:
                # Run the effect
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                
                # Load processed result
                if os.path.exists(output_path):
                    processed = cv2.imread(output_path)
                    if processed is not None:
                        # Resize back to original size if needed
                        if processed.shape[:2] != frame.shape[:2]:
                            processed = cv2.resize(processed, (frame.shape[1], frame.shape[0]))
                        return processed
                        
        except subprocess.TimeoutExpired:
            pass  # Effect took too long, return original
        except Exception as e:
            pass  # Error processing, return original
            
        return frame
    
    def stop(self):
        self.running = False
        self.wait()
    
    def set_effect(self, effect, mode=0):
        self.effect = effect
        self.effect_mode = mode
    
    def set_background(self, image_path):
        if image_path and Path(image_path).exists():
            self.background_image = cv2.imread(image_path)
            self.background_path = image_path
            # Copy to container-accessible path if needed
            container_bg_path = "/tmp/videofx_frames/background.png"
            cv2.imwrite(container_bg_path, self.background_image)
            self.background_path = container_bg_path


class VideoFXApp(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VideoFX - NVIDIA AI Video Effects")
        self.setMinimumSize(1200, 800)
        self.setStyleSheet(self.get_stylesheet())
        
        # Video thread
        self.video_thread = None
        self.current_frame = None
        self.test_mode = False
        self.test_image_original = None
        
        # Virtual camera
        self.virtual_cam_device = "/dev/video10"
        
        self.init_ui()
        self.detect_gpu()
        self.start_camera()
    
    def get_stylesheet(self):
    return """
        QMainWindow {
            background-color: #f6f7fb;
        }

        QLabel {
            color: #1f2937;
            font-size: 14px;
        }

        QPushButton {
            background-color: #4f46e5; /* modern indigo */
            color: white;
            border: none;
            padding: 10px 22px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
        }

        QPushButton:hover {
            background-color: #4338ca;
        }

        QPushButton:pressed {
            background-color: #3730a3;
        }

        QPushButton:checked {
            background-color: #16a34a; /* soft green */
        }

        QGroupBox {
            background-color: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            margin-top: 14px;
            padding: 18px;
            font-weight: 600;
            color: #111827;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: #374151;
        }

        QComboBox {
            background-color: #ffffff;
            color: #111827;
            border: 1px solid #d1d5db;
            padding: 8px 14px;
            border-radius: 8px;
            min-width: 150px;
        }

        QComboBox:hover {
            border-color: #4f46e5;
        }

        QComboBox::drop-down {
            border: none;
        }

        QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #111827;
            selection-background-color: #e0e7ff;
            border: 1px solid #e5e7eb;
        }

        QCheckBox {
            color: #1f2937;
            font-size: 14px;
        }

        QCheckBox::indicator {
            width: 18px;
            height: 18px;
        }

        QSlider::groove:horizontal {
            background: #e5e7eb;
            height: 6px;
            border-radius: 3px;
        }

        QSlider::handle:horizontal {
            background: #4f46e5;
            width: 18px;
            margin: -6px 0;
            border-radius: 9px;
        }

        QStatusBar {
            background-color: #ffffff;
            color: #4b5563;
            border-top: 1px solid #e5e7eb;
        }
    """

    
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Left panel - Video preview
        preview_panel = QVBoxLayout()
        
        # Title
        title = QLabel("🎥 VideoFX Studio")
        title.setFont(QFont("Arial", 24, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #00a86b; margin-bottom: 10px;")
        preview_panel.addWidget(title)
        
        # Video display
        self.video_label = QLabel()
        self.video_label.setMinimumSize(800, 600)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("""
            background-color: #0a0a0a;
            border: 3px solid #0f3460;
            border-radius: 15px;
        """)
        self.video_label.setText("📹 Starting camera...")
        preview_panel.addWidget(self.video_label)
        
        # Camera controls
        cam_controls = QHBoxLayout()
        
        self.camera_combo = QComboBox()
        self.camera_combo.addItems(["Camera 0", "Camera 1", "Camera 2"])
        self.camera_combo.currentIndexChanged.connect(self.change_camera)
        cam_controls.addWidget(QLabel("Camera:"))
        cam_controls.addWidget(self.camera_combo)
        cam_controls.addStretch()
        
        preview_panel.addLayout(cam_controls)
        
        main_layout.addLayout(preview_panel, stretch=3)
        
        # Right panel - Effects controls
        controls_panel = QVBoxLayout()
        
        # Effects section
        effects_group = QGroupBox("🎨 AI Effects")
        effects_layout = QVBoxLayout(effects_group)
        
        # Green Screen
        self.btn_green_screen = QPushButton("🌿 AI Green Screen")
        self.btn_green_screen.setCheckable(True)
        self.btn_green_screen.clicked.connect(lambda: self.toggle_effect("green_screen"))
        effects_layout.addWidget(self.btn_green_screen)
        
        # Background selector
        bg_layout = QHBoxLayout()
        self.bg_label = QLabel("Background: None")
        self.bg_label.setStyleSheet("font-size: 12px; color: #888;")
        bg_layout.addWidget(self.bg_label)
        
        self.btn_select_bg = QPushButton("📁 Select")
        self.btn_select_bg.setStyleSheet("padding: 6px 12px; font-size: 12px;")
        self.btn_select_bg.clicked.connect(self.select_background)
        bg_layout.addWidget(self.btn_select_bg)
        effects_layout.addLayout(bg_layout)
        
        effects_layout.addWidget(self.create_separator())
        
        # Denoise
        self.btn_denoise = QPushButton("🔇 Video Denoise")
        self.btn_denoise.setCheckable(True)
        self.btn_denoise.clicked.connect(lambda: self.toggle_effect("denoise"))
        effects_layout.addWidget(self.btn_denoise)
        
        # Denoise strength
        denoise_strength = QHBoxLayout()
        denoise_strength.addWidget(QLabel("Strength:"))
        self.denoise_slider = QSlider(Qt.Horizontal)
        self.denoise_slider.setRange(0, 100)
        self.denoise_slider.setValue(50)
        denoise_strength.addWidget(self.denoise_slider)
        effects_layout.addLayout(denoise_strength)
        
        effects_layout.addWidget(self.create_separator())
        
        # Super Resolution
        self.btn_superres = QPushButton("🔍 Super Resolution")
        self.btn_superres.setCheckable(True)
        self.btn_superres.clicked.connect(lambda: self.toggle_effect("superres"))
        effects_layout.addWidget(self.btn_superres)
        
        # Resolution selector
        res_layout = QHBoxLayout()
        res_layout.addWidget(QLabel("Output:"))
        self.res_combo = QComboBox()
        self.res_combo.addItems(["1080p", "1440p", "4K"])
        res_layout.addWidget(self.res_combo)
        effects_layout.addLayout(res_layout)
        
        effects_layout.addWidget(self.create_separator())
        
        # Artifact Reduction
        self.btn_artifact = QPushButton("✨ Artifact Reduction")
        self.btn_artifact.setCheckable(True)
        self.btn_artifact.clicked.connect(lambda: self.toggle_effect("artifact"))
        effects_layout.addWidget(self.btn_artifact)
        
        controls_panel.addWidget(effects_group)
        
        # Virtual Camera section
        vcam_group = QGroupBox("📹 Virtual Camera")
        vcam_layout = QVBoxLayout(vcam_group)
        
        self.btn_virtual_cam = QPushButton("🎬 Enable Virtual Camera")
        self.btn_virtual_cam.setCheckable(True)
        self.btn_virtual_cam.setStyleSheet("""
            QPushButton {
                background-color: #4a0080;
                font-size: 16px;
            }
            QPushButton:checked {
                background-color: #00a86b;
            }
            QPushButton:hover {
                background-color: #6b00b3;
            }
        """)
        self.btn_virtual_cam.clicked.connect(self.toggle_virtual_camera)
        vcam_layout.addWidget(self.btn_virtual_cam)
        
        self.vcam_status = QLabel("Status: Disabled")
        self.vcam_status.setStyleSheet("color: #ff6b6b; font-size: 12px;")
        vcam_layout.addWidget(self.vcam_status)
        
        vcam_info = QLabel("Use 'VideoFX Camera' in OBS, Discord,\nGoogle Meet, Zoom, etc.")
        vcam_info.setStyleSheet("color: #888; font-size: 11px;")
        vcam_layout.addWidget(vcam_info)
        
        controls_panel.addWidget(vcam_group)
        
        # Test Mode section  
        test_group = QGroupBox("🧪 Test Mode")
        test_layout = QVBoxLayout(test_group)
        
        self.btn_test_mode = QPushButton("📷 Use Test Image")
        self.btn_test_mode.setCheckable(True)
        self.btn_test_mode.clicked.connect(self.toggle_test_mode)
        test_layout.addWidget(self.btn_test_mode)
        
        test_info = QLabel("Test effects without a camera")
        test_info.setStyleSheet("color: #888; font-size: 11px;")
        test_layout.addWidget(test_info)
        
        controls_panel.addWidget(test_group)
        
        controls_panel.addStretch()
        
        # Info section
        info_group = QGroupBox("ℹ️ System Info")
        info_layout = QVBoxLayout(info_group)
        info_layout.addWidget(QLabel("Powered by NVIDIA VideoFX SDK"))
        
        self.gpu_label = QLabel("GPU: Detecting...")
        info_layout.addWidget(self.gpu_label)
        
        self.btn_test_gpu = QPushButton("🔬 Test GPU")
        self.btn_test_gpu.clicked.connect(self.test_gpu)
        self.btn_test_gpu.setStyleSheet("padding: 6px 12px; font-size: 12px;")
        info_layout.addWidget(self.btn_test_gpu)
        
        controls_panel.addWidget(info_group)
        
        main_layout.addLayout(controls_panel, stretch=1)
        
        # Status bar
        self.statusBar().showMessage("Ready")
    
    def create_separator(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #0f3460;")
        return line
    
    def start_camera(self, camera_id=0):
        if self.video_thread:
            self.video_thread.stop()
        
        self.video_thread = VideoThread(camera_id)
        self.video_thread.frame_ready.connect(self.update_frame)
        self.video_thread.error_signal.connect(self.show_camera_error)
        self.video_thread.start()
        self.statusBar().showMessage(f"Starting camera {camera_id}...")
    
    def show_camera_error(self, error_msg):
        self.video_label.setText(f"📹 Camera Error\n\n{error_msg}\n\nPlease connect a webcam and restart.")
        self.statusBar().showMessage(f"Camera error: {error_msg}")
    
    def update_frame(self, frame):
        self.current_frame = frame
        
        # Convert to QImage and display
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        
        # Scale to fit label
        pixmap = QPixmap.fromImage(qt_image)
        scaled = pixmap.scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.video_label.setPixmap(scaled)
    
    def change_camera(self, index):
        self.start_camera(index)
    
    def toggle_effect(self, effect_name):
        buttons = {
            "green_screen": self.btn_green_screen,
            "denoise": self.btn_denoise,
            "superres": self.btn_superres,
            "artifact": self.btn_artifact
        }
        
        # Only one effect at a time for now
        for name, btn in buttons.items():
            if name != effect_name:
                btn.setChecked(False)
        
        if buttons[effect_name].isChecked():
            # If in test mode, apply effect immediately to test image
            if self.test_mode:
                self.apply_test_effect(effect_name)
            else:
                # For camera mode, set effect on video thread
                if self.video_thread:
                    self.video_thread.set_effect(effect_name)
                self.statusBar().showMessage(f"Effect enabled: {effect_name}")
        else:
            if self.test_mode and hasattr(self, 'test_image_original') and self.test_image_original is not None:
                # Show original image when effect is disabled
                self.update_frame(self.test_image_original)
                self.statusBar().showMessage("Effect disabled - showing original image")
            elif self.video_thread:
                self.video_thread.set_effect(None)
                self.statusBar().showMessage("Effect disabled")
    
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
            self.bg_label.setText(f"Background: {Path(file_path).name}")
            self.video_thread.set_background(file_path)
    
    def toggle_virtual_camera(self):
        if self.btn_virtual_cam.isChecked():
            # Try to enable virtual camera
            try:
                import pyfakewebcam
                self.video_thread.virtual_cam = pyfakewebcam.FakeWebcam(
                    self.virtual_cam_device, 1280, 720
                )
                self.video_thread.virtual_cam_enabled = True
                self.vcam_status.setText("Status: Active ✅")
                self.vcam_status.setStyleSheet("color: #00a86b; font-size: 12px;")
                self.btn_virtual_cam.setText("🎬 Virtual Camera: ON")
                self.statusBar().showMessage("Virtual camera enabled")
            except Exception as e:
                self.btn_virtual_cam.setChecked(False)
                self.vcam_status.setText(f"Error: {str(e)[:30]}")
                self.statusBar().showMessage(f"Virtual camera error: {e}")
        else:
            self.video_thread.virtual_cam_enabled = False
            self.video_thread.virtual_cam = None
            self.vcam_status.setText("Status: Disabled")
            self.vcam_status.setStyleSheet("color: #ff6b6b; font-size: 12px;")
            self.btn_virtual_cam.setText("🎬 Enable Virtual Camera")
            self.statusBar().showMessage("Virtual camera disabled")
    
    def detect_gpu(self):
        """Detect and display GPU information"""
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu_info = result.stdout.strip().split(',')
                gpu_name = gpu_info[0].strip() if len(gpu_info) > 0 else "Unknown"
                gpu_mem = f"{int(gpu_info[1].strip())//1024}GB" if len(gpu_info) > 1 else ""
                self.gpu_label.setText(f"GPU: {gpu_name} ({gpu_mem})")
                self.gpu_label.setStyleSheet("color: #00a86b;")
            else:
                self.gpu_label.setText("GPU: Not detected ❌")
                self.gpu_label.setStyleSheet("color: #ff6b6b;")
        except Exception as e:
            self.gpu_label.setText(f"GPU: Error ({str(e)[:20]})")
            self.gpu_label.setStyleSheet("color: #ff6b6b;")
    
    def toggle_test_mode(self):
        """Toggle test mode with a sample image instead of camera"""
        if self.btn_test_mode.isChecked():
            self.test_mode = True
            self.btn_test_mode.setText("📷 Test Mode: ON")
            
            # Stop camera if running
            if self.video_thread:
                self.video_thread.stop()
            
            # Load and store test image
            self.test_image_original = self.load_sample_image()
            if self.test_image_original is not None:
                self.current_frame = self.test_image_original.copy()
                self.update_frame(self.test_image_original)
                self.statusBar().showMessage("Test mode enabled - click an effect button to apply it!")
            else:
                self.statusBar().showMessage("Test mode enabled - sample image not found")
        else:
            self.test_mode = False
            self.test_image_original = None
            self.btn_test_mode.setText("📷 Use Test Image")
            self.start_camera()
            self.statusBar().showMessage("Test mode disabled - using camera")
    
    def apply_test_effect(self, effect_name):
        """Apply an effect to the test image and display result"""
        if not self.test_mode or self.test_image_original is None:
            return
        
        self.statusBar().showMessage(f"Processing {effect_name} effect...")
        
        try:
            # Save original test image to temp file
            input_path = "/tmp/videofx_frames/input.png"
            output_path = "/tmp/videofx_frames/output.png"
            cv2.imwrite(input_path, self.test_image_original)
            
            # Build command based on effect type
            cmd = None
            model_dir = "/usr/local/VideoFX/lib/models"
            
            if effect_name == "green_screen":
                aigs_app = "/build/samples/AigsEffectApp/AigsEffectApp"
                cmd = [aigs_app, 
                       f"--model_dir={model_dir}",
                       f"--in_file={input_path}",
                       f"--out_file={output_path}",
                       "--mode=0"]
                       
            elif effect_name == "denoise":
                denoise_app = "/build/samples/DenoiseEffectApp/DenoiseEffectApp"
                cmd = [denoise_app,
                       f"--model_dir={model_dir}",
                       f"--in_file={input_path}",
                       f"--out_file={output_path}",
                       "--strength=1.0"]
                       
            elif effect_name == "superres":
                effects_app = "/build/samples/VideoEffectsApp/VideoEffectsApp"
                cmd = [effects_app,
                       f"--model_dir={model_dir}",
                       f"--in_file={input_path}",
                       f"--out_file={output_path}",
                       "--effect=SuperRes",
                       "--resolution=1080",
                       "--mode=0"]
                       
            elif effect_name == "artifact":
                effects_app = "/build/samples/VideoEffectsApp/VideoEffectsApp"
                cmd = [effects_app,
                       f"--model_dir={model_dir}",
                       f"--in_file={input_path}",
                       f"--out_file={output_path}",
                       "--effect=ArtifactReduction",
                       "--mode=0"]
            
            if cmd:
                # Run the effect
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                # Load processed result
                if os.path.exists(output_path):
                    processed = cv2.imread(output_path)
                    if processed is not None:
                        # Resize to display size if needed
                        if processed.shape[:2] != self.test_image_original.shape[:2]:
                            processed = cv2.resize(processed, 
                                (self.test_image_original.shape[1], self.test_image_original.shape[0]))
                        
                        # Add effect label
                        cv2.putText(processed, f"Effect: {effect_name.upper()}", (20, 50), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        
                        self.update_frame(processed)
                        self.statusBar().showMessage(f"✅ {effect_name} effect applied successfully!")
                        return
                    else:
                        self.statusBar().showMessage(f"❌ Failed to load processed image")
                else:
                    error_msg = result.stderr[:100] if result.stderr else "No output file created"
                    self.statusBar().showMessage(f"❌ Effect failed: {error_msg}")
                    
        except subprocess.TimeoutExpired:
            self.statusBar().showMessage(f"❌ Effect timed out (may need GPU)")
        except FileNotFoundError:
            self.statusBar().showMessage(f"❌ Effect app not found - rebuild container")
        except Exception as e:
            self.statusBar().showMessage(f"❌ Error: {str(e)[:50]}")
    
    def load_sample_image(self):
        """Load actual sample image from VideoFX SDK"""
        # Try to load sample images with people (for testing green screen)
        sample_paths = [
            "/usr/local/VideoFX/share/samples/input/LeFret_003400.jpg",
            "/usr/local/VideoFX/share/samples/input/LeFret_001400.jpg",
            "/usr/local/VideoFX/share/samples/input/input1.jpg",
            "/usr/local/VideoFX/share/samples/input/input2.jpg",
        ]
        
        for path in sample_paths:
            if os.path.exists(path):
                img = cv2.imread(path)
                if img is not None:
                    # Resize to 1280x720 if needed
                    h, w = img.shape[:2]
                    if w != 1280 or h != 720:
                        img = cv2.resize(img, (1280, 720))
                    
                    # Add overlay text
                    cv2.putText(img, "TEST MODE - Sample Image", (20, 50), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    cv2.putText(img, f"Source: {os.path.basename(path)}", (20, 90),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    cv2.putText(img, "Enable effects to see them applied!", (20, 680),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                    return img
        
        # Fallback: create a test pattern if no sample images found
        return self.create_test_pattern()
    
    def create_test_pattern(self):
        """Create a colorful test pattern image as fallback"""
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        
        # Gradient background
        for i in range(720):
            img[i, :, 0] = int(50 + (i / 720) * 100)
            img[i, :, 1] = int(30 + (i / 720) * 50)
            img[i, :, 2] = int(60 + (i / 720) * 80)
        
        # Add colored rectangles
        cv2.rectangle(img, (100, 100), (400, 300), (0, 255, 0), -1)
        cv2.rectangle(img, (450, 100), (750, 300), (0, 0, 255), -1)
        cv2.rectangle(img, (800, 100), (1100, 300), (255, 0, 0), -1)
        
        cv2.putText(img, "VideoFX Test Pattern", (350, 450), 
                    cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        cv2.putText(img, "Sample images not found in container", (300, 520),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2)
        
        return img
    
    def test_gpu(self):
        """Test GPU functionality with nvidia-smi"""
        self.statusBar().showMessage("Testing GPU...")
        
        try:
            # Run nvidia-smi to test GPU access
            result = subprocess.run(
                ['nvidia-smi'],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                # Parse output for key info
                lines = result.stdout.strip().split('\n')
                gpu_found = False
                for line in lines:
                    if 'NVIDIA' in line and 'GeForce' in line or 'RTX' in line or 'GTX' in line:
                        gpu_found = True
                        break
                
                if gpu_found or 'NVIDIA-SMI' in result.stdout:
                    self.gpu_label.setText("GPU: Working ✅")
                    self.gpu_label.setStyleSheet("color: #00a86b;")
                    self.statusBar().showMessage("GPU test passed! NVIDIA driver is working.")
                    
                    # Show detailed info in dialog
                    from PyQt5.QtWidgets import QMessageBox
                    msg = QMessageBox()
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("GPU Test Results")
                    msg.setText("✅ GPU is working correctly!")
                    msg.setDetailedText(result.stdout[:2000])
                    msg.exec_()
                else:
                    self.gpu_label.setText("GPU: Driver issue ⚠️")
                    self.gpu_label.setStyleSheet("color: #ffcc00;")
                    self.statusBar().showMessage("GPU driver may have issues")
            else:
                self.gpu_label.setText("GPU: Not available ❌")
                self.gpu_label.setStyleSheet("color: #ff6b6b;")
                self.statusBar().showMessage(f"GPU test failed: {result.stderr[:50]}")
                
        except FileNotFoundError:
            self.gpu_label.setText("GPU: nvidia-smi not found")
            self.gpu_label.setStyleSheet("color: #ff6b6b;")
            self.statusBar().showMessage("nvidia-smi command not found in container")
        except Exception as e:
            self.gpu_label.setText(f"GPU: Error")
            self.gpu_label.setStyleSheet("color: #ff6b6b;")
            self.statusBar().showMessage(f"GPU test error: {e}")
    
    def closeEvent(self, event):
        if self.video_thread:
            self.video_thread.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    # app.setStyle("Fusion")
    
    window = VideoFXApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
