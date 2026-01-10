# VideoFX Studio

Real-time AI-powered video effects using NVIDIA Maxine VideoFX SDK.

## License

This project consists of two parts with different licenses:

### Your Code (MIT License)

The application code in this repository (`app/`, `run.sh`, `Containerfile`, etc.) 
is licensed under the MIT License - see [LICENSE](LICENSE) for details.

### NVIDIA Maxine SDK

This application uses the NVIDIA Maxine VideoFX SDK, which is subject to 
NVIDIA's proprietary license. The SDK is redistributable under NVIDIA's terms.

**NVIDIA Maxine SDK Branding Requirement:**  
This application uses NVIDIA Maxine™ for AI-powered video effects.
See [NVIDIA Maxine SDK Guidelines](https://www.nvidia.com/maxine-sdk-guidelines) for branding requirements.

## Features

- Real-time AI background removal (Green Screen)
- Custom background replacement
- Background blur
- Virtual camera output for video conferencing
- Low-latency processing with persistent model loading

## Requirements

- NVIDIA GPU (required by SDK license)
- NVIDIA drivers with CUDA support
- Podman or Docker with NVIDIA container toolkit

## Quick Start

```bash
./run.sh
```

## Acknowledgments

- **NVIDIA Maxine™ VideoFX SDK** - AI video effects engine
- **OpenCV** - Computer vision library (Apache 2.0)
- **PyQt5** - GUI framework (GPL/Commercial)
- **TensorRT** - NVIDIA deep learning inference optimizer

## Third-Party Licenses

See `sdk/VideoFX/share/bin/ThirdPartyLicenses.txt` for third-party component licenses.
