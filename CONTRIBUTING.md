# Contributing to ClearCastFX

Thank you for your interest in contributing to ClearCastFX! This document provides guidelines and information for contributors.

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How to Contribute

### Reporting Bugs

Before creating a bug report, please check the existing issues to avoid duplicates. When filing a bug report, include:

- **Clear title** describing the issue
- **Steps to reproduce** the problem
- **Expected behavior** vs actual behavior
- **System information**: OS, GPU model, driver version
- **Logs** from the terminal output if applicable

### Suggesting Features

Feature requests are welcome! Please:

- Check existing issues and discussions first
- Clearly describe the use case
- Explain why this would benefit other users

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Follow the code style** of the project
3. **Write clear commit messages**
4. **Test your changes** thoroughly
5. **Update documentation** if needed
6. **Submit the PR** with a clear description

## Development Setup

### Prerequisites

- Linux (Fedora or Ubuntu recommended)
- NVIDIA GPU with drivers
- Podman or Docker with NVIDIA Container Toolkit
- Python 3.8+
- CMake 3.10+
- GCC/G++ with C++17 support

### Setting Up for Development

1. Clone your fork:
   ```bash
   git clone https://github.com/yourusername/clearcastfx.git
   cd clearcastfx
   ```

2. Download the NVIDIA Maxine SDK from [NVIDIA Developer](https://developer.nvidia.com/maxine-getting-started) and extract to `sdk/`

3. Build the container:
   ```bash
   ./install.sh
   ```

### Code Structure

```
clearcastfx/
├── app/
│   ├── control_panel.py    # Qt GUI application
│   ├── videofx_server.cpp  # C++ video processing server
│   └── CMakeLists.txt      # Build configuration
├── scripts/
│   └── vcam_watcher.sh     # Virtual camera monitor
├── Containerfile           # Container build definition
├── run.sh                  # Launch script
└── install.sh              # Installation script
```

### Code Style

**Python:**
- Follow PEP 8
- Use type hints where appropriate
- Docstrings for classes and functions

**C++:**
- C++17 standard
- Use meaningful variable names
- Comment complex logic

**Shell scripts:**
- Use `set -e` for error handling
- Quote variables: `"$var"`
- Use `[[ ]]` for conditionals

### Testing

Before submitting a PR:

1. Test with different effect modes
2. Verify virtual camera works in video apps
3. Check for memory leaks with valgrind (if applicable)
4. Test on different GPU generations if possible

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Questions?

Feel free to open an issue or discussion for any questions about contributing.
