# ClearCastFX

Real-time AI-powered video effects using NVIDIA Maxine VideoFX SDK. Replace your background, blur it, or apply professional video effects—all processed locally on your GPU.

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Linux-orange)
![NVIDIA](https://img.shields.io/badge/NVIDIA-GPU_Required-76B900?logo=nvidia)

<p align="center">
  <img src="assets/logo.svg" alt="ClearCastFX Logo" width="200">
</p>

## Features

- **Background Removal** — AI-powered green screen effect
- **Background Replacement** — Use any image as your background
- **Background Blur** — Professional depth-of-field blur
- **Noise Reduction** — AI denoising for cleaner video
- **Virtual Camera** — Use in Zoom, Meet, OBS, and any video app
- **Low Latency** — Real-time processing with persistent model loading
- **Modern UI** — Clean, light-themed control panel

## Requirements

- Linux (tested on Fedora, Ubuntu)
- NVIDIA GPU (GTX 1060 or better recommended)
- NVIDIA drivers with CUDA support
- Podman or Docker with NVIDIA Container Toolkit
- Webcam

## Installation

> **Note:** The NVIDIA Maxine SDK cannot be redistributed, so you must download it separately and build locally.

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/clearcastfx.git
cd clearcastfx
```

### 2. Download the NVIDIA Maxine SDK

1. Visit [NVIDIA Maxine Getting Started](https://developer.nvidia.com/maxine-getting-started)
2. Sign in with your NVIDIA Developer account (free)
3. Download the **Video Effects SDK** for Linux
4. Download **TensorRT 8.5.x** and **cuDNN 8.x** if not included

### 3. Extract SDKs to the `sdk/` directory

```bash
mkdir -p sdk
# Extract VideoFX SDK
tar -xzf Video_Effects_SDK_*.tar.gz -C sdk/
mv sdk/Video_Effects_SDK* sdk/VideoFX

# Extract TensorRT
tar -xzf TensorRT-8.5.*.tar.gz -C sdk/

# Extract cuDNN (copy libraries)
mkdir -p sdk/cudnn
tar -xzf cudnn-*.tar.xz
cp -r cudnn-*/lib/* sdk/cudnn/
cp -r cudnn-*/include/* sdk/cudnn/
```

Your `sdk/` directory should look like:
```
sdk/
├── VideoFX/
├── TensorRT-8.5.1.7/
└── cudnn/
```

### 4. Build and run

```bash
./install.sh
./run.sh
```

## Usage

1. Launch ClearCastFX with `./run.sh`
2. Select your desired effect from the dropdown
3. For custom backgrounds, click "Browse" and select an image
4. The virtual camera appears as `/dev/video10`
5. Select "ClearCastFX Camera" in your video conferencing app

### Keyboard Shortcuts (Preview Window)

| Key | Action |
|-----|--------|
| Q / ESC | Quit |
| F | Toggle FPS display |

## Virtual Camera Setup

ClearCastFX uses v4l2loopback to create a virtual camera. The installer handles this automatically, but if needed:

```bash
sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="ClearCastFX Camera" exclusive_caps=1
```

To load automatically on boot, create `/etc/modules-load.d/v4l2loopback.conf`:
```
v4l2loopback
```

And `/etc/modprobe.d/v4l2loopback.conf`:
```
options v4l2loopback devices=1 video_nr=10 card_label="ClearCastFX Camera" exclusive_caps=1
```

## Configuration

Settings are stored in `~/.config/clearcastfx/settings.json` and persist between sessions.

## Troubleshooting

### No camera detected
- Ensure your webcam is connected: `ls /dev/video*`
- Check camera permissions: `groups | grep video`

### GPU errors
- Verify NVIDIA drivers: `nvidia-smi`
- Check Container Toolkit: `podman run --rm --device nvidia.com/gpu=all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi`

### Display errors
- Allow X11 connections: `xhost +local:`
- For Wayland, ensure XWayland is running

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Webcam        │────▶│  ClearCastFX     │────▶│  Virtual Camera │
│   /dev/video0   │     │  Server (C++)    │     │  /dev/video10   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               │ Named Pipe
                               ▼
                        ┌──────────────────┐
                        │  Control Panel   │
                        │  (Python/Qt)     │
                        └──────────────────┘
```

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) for details.

### Third-Party Components

- **NVIDIA Maxine SDK** — NVIDIA proprietary license (must be downloaded separately)
- **OpenCV** — Apache License 2.0
- **PySide6** — LGPL v3
- **TensorRT** — NVIDIA proprietary license

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Acknowledgments

- NVIDIA Maxine team for the VideoFX SDK
- OpenCV community
- Qt/PySide6 project
