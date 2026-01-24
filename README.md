# VideoFX Studio

Real-time AI-powered video effects using NVIDIA Maxine VideoFX SDK.

![NVIDIA Maxine](https://img.shields.io/badge/NVIDIA-Maxine_SDK-76B900?logo=nvidia)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Linux-orange)

## 🚀 Quick Start

### Option 1: Download Pre-built Release (Recommended)

Download the latest release from the [Releases page](../../releases) and run:

```bash
tar -xzf videofx-app-*.tar.gz
cd videofx-app
./run.sh
```

### Option 2: Build from Source

See [Building from Source](#building-from-source) below.

## ✨ Features

- Real-time AI background removal (Green Screen)
- Custom background replacement
- Background blur
- Virtual camera output for video conferencing
- Low-latency processing with persistent model loading

## 📋 Requirements

- NVIDIA GPU (required by SDK license)
- NVIDIA drivers with CUDA support
- Podman or Docker with NVIDIA container toolkit

## 🔧 Building from Source

The NVIDIA Maxine SDK cannot be redistributed in source form. To build from source:

### 1. Download the NVIDIA Maxine SDK

1. Visit [NVIDIA Maxine Getting Started](https://developer.nvidia.com/maxine-getting-started)
2. Sign in with your NVIDIA Developer account (free registration)
3. Download the **Video Effects SDK** for Linux

### 2. Install the SDK

```bash
# Extract the SDK to the project's sdk/ directory
mkdir -p sdk
tar -xzf NVIDIA_Video_Effects_SDK_*.tar.gz -C sdk/
```

### 3. Build the Application

```bash
cd app
mkdir build && cd build
cmake ..
make -j$(nproc)
```

### 4. Run

```bash
./run.sh
```

## 📦 Distribution Notes

This application includes the NVIDIA Maxine SDK in pre-built releases as permitted by
NVIDIA's license (object code format, incorporated into the application).

**Source code** in this repository is MIT licensed. The SDK components included in
binary releases remain subject to NVIDIA's license terms.

## 📜 License

### Application Code (MIT License)

The application code in this repository (`app/`, `run.sh`, `Containerfile`, etc.) 
is licensed under the MIT License - see [LICENSE](LICENSE) for details.

### NVIDIA Maxine SDK

This application uses the NVIDIA Maxine VideoFX SDK, which is subject to 
NVIDIA's proprietary license. The SDK is redistributable in object code format
as part of this application under NVIDIA's terms.

**NVIDIA Maxine SDK Branding Requirement:**  
This application uses NVIDIA Maxine™ for AI-powered video effects.

## 🙏 Acknowledgments

- **NVIDIA Maxine™ VideoFX SDK** - AI video effects engine
- **OpenCV** - Computer vision library (Apache 2.0)
- **PyQt5** - GUI framework (GPL/Commercial)
- **TensorRT** - NVIDIA deep learning inference optimizer

## 📄 Third-Party Licenses

See `sdk/VideoFX/share/bin/ThirdPartyLicenses.txt` for third-party component licenses.
