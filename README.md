<div align="center">

<p align="center">
  <img src="assets/logo.svg" alt="ClearCastFX Logo" width="80" style="vertical-align: middle;" />
  <span style="font-size: 2em; font-weight: bold; vertical-align: middle; margin-left: 12px;">
    ClearCastFX
  </span>
</p>

Real-time AI-powered video effects using NVIDIA Maxine VideoFX SDK.<br>
Basically NVIDIA Broadcast, but for Linux.

</div>

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Building from Source](#building-from-source)
- [Usage](#usage)
- [Virtual Camera Setup](#virtual-camera-setup)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [License](#license)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)

## Features

- **Background Removal**
- **Background Replacement** - Use any image as your background
- **Background Blur**
- **Noise Reduction** - AI denoising for cleaner video
- **On-demand camera usage** - Camera (and processing power) is only used when needed

## Prerequisites

The following must be installed on your host system **before** installing ClearCastFC:

- **NVIDIA GPU** (GTX 1060 or better recommended)
- **NVIDIA drivers** with CUDA support — verify with `nvidia-smi`
- **Podman or Docker**
- **[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)** — required for GPU passthrough into the container
  - Fedora: `sudo dnf install nvidia-container-toolkit`
  - Ubuntu: follow the [official install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- **[v4l2loopback](https://github.com/umlaeute/v4l2loopback)** — kernel module for the virtual camera device
  - Fedora: `sudo dnf install v4l2loopback`
  - Ubuntu: `sudo apt install v4l2loopback-dkms`

## Quick Start

The easiest way to get ClearCastFX running:

```bash
curl -fsSL https://raw.githubusercontent.com/Andrei9383/ClearCastFX/main/scripts/install-remote.sh | bash
```

Or manually:

```bash
# Pull the container
podman pull ghcr.io/andrei9383/clearcastfx:latest

# Setup virtual camera (requires v4l2loopback)
sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="ClearCastFX Camera" exclusive_caps=1

# Run
podman run --rm \
  --device nvidia.com/gpu=all \
  --device /dev/video0 \
  --device /dev/video10 \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.config/clearcastfx:/root/.config/clearcastfx \
  --network host \
  ghcr.io/andrei9383/clearcastfx:latest
```

After installation, run `clearcastfx` from terminal or find it in your application menu.

## Building from Source

If you prefer to build locally (if you have the SDK available):

[!NOTE]
The Maxine SDK (for version v0.7.2.0), as per my trials, requires (very) specific versions of cuDNN and TensorRT:
- CUDA 11.8.0
- cuDNN 8.6.0.163
- TensorRT 8.5.1.7

### 1. Clone the repository

```bash
git clone https://github.com/Andrei9383/ClearCastFX.git
cd ClearCastFX
```

### 2. Download the NVIDIA Maxine SDK, if you have an AI Enterprise subscription :(

1. Visit [NVIDIA Catalog](https://catalog.ngc.nvidia.com/)
3. Download the **Video Effects SDK** for Linux
4. Download **TensorRT 8.5.x** and **cuDNN 8.x** (check the versions specified in the documentation of the SDK, usually they are pretty strict)

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

1. Launch ClearCastFX by running the desktop entry application or by running `./run.sh` at the install location
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

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) for details.

### Third-Party Components

- **NVIDIA Maxine SDK**
- **OpenCV**
- **PySide6**
- **TensorRT**

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Acknowledgments

- NVIDIA Maxine team for the VideoFX SDK
- OpenCV community
- Qt/PySide6 project
