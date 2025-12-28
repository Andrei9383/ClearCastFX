# 🎥 VideoFX Studio

**NVIDIA AI Video Effects for Linux** - A portable, self-contained webcam effects application with virtual camera output.

## Features

- 🌿 **AI Green Screen** - Background removal/replacement
- 🔇 **Video Denoise** - Remove video noise  
- 🔍 **Super Resolution** - Upscale video quality
- ✨ **Artifact Reduction** - Remove compression artifacts
- 📹 **Virtual Camera** - Use in OBS, Discord, Google Meet, Zoom, etc.

## Requirements

- NVIDIA GPU (Turing architecture or newer)
- NVIDIA Driver 520+ installed
- Podman or Docker
- Linux (Fedora, Ubuntu, etc.)

## Quick Install

```bash
# One-line install
./install.sh
```

## Usage

```bash
# Launch the app
./run.sh
```

Or search for "VideoFX Studio" in your applications menu.

## Virtual Camera

The processed video output appears as "VideoFX Camera" in other applications:

1. Enable virtual camera in the app
2. In OBS/Discord/Meet, select "VideoFX Camera" as your camera

## What's Included

- NVIDIA VideoFX SDK
- TensorRT 8.5.1.7
- cuDNN 8.6.0
- OpenCV
- PyQt5 UI

## License

This distribution includes NVIDIA SDKs subject to NVIDIA's license terms.
See the SDK license agreements for details.

---
*Powered by NVIDIA Maxine VideoFX SDK*
