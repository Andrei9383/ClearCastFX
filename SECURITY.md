# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it by emailing the maintainers directly rather than opening a public issue.

When reporting:
1. Describe the vulnerability in detail
2. Include steps to reproduce if possible
3. Suggest a fix if you have one

We will acknowledge receipt within 48 hours and aim to provide a fix within 7 days for critical issues.

## Security Considerations

### Container Security
- ClearCastFX runs inside a container with GPU access
- The container requires `--security-opt label=disable` for device access
- Network is in host mode for X11 display

### Data Privacy
- All video processing happens locally on your GPU
- No data is sent to external servers
- Configuration is stored locally in `~/.config/clearcastfx/`

### Dependencies
- Uses NVIDIA proprietary SDK components
- Container is based on nvidia/cuda official images
