#!/bin/bash
# create-release.sh - Package VideoFX Studio for GitHub Release
#
# This script creates a distributable tarball containing the compiled
# application and NVIDIA Maxine SDK components (as permitted by NVIDIA's
# license for object code distribution in applications).

set -e

VERSION="${1:-1.0.0}"
RELEASE_NAME="videofx-app-v${VERSION}-linux-x64"
RELEASE_DIR="release/${RELEASE_NAME}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "📦 Creating release: ${RELEASE_NAME}"
echo "   Project root: ${PROJECT_ROOT}"

# Check if SDK exists
if [ ! -d "${PROJECT_ROOT}/sdk/VideoFX" ]; then
    echo "❌ Error: SDK not found at ${PROJECT_ROOT}/sdk/VideoFX"
    echo "   Please install the NVIDIA Maxine SDK first."
    exit 1
fi

# Check if compiled binary exists
if [ ! -f "${PROJECT_ROOT}/app/build/videofx_server" ]; then
    echo "⚙️  Compiled binary not found. Building..."
    cd "${PROJECT_ROOT}/app"
    mkdir -p build && cd build
    cmake ..
    make -j$(nproc)
    cd "${PROJECT_ROOT}"
fi

# Clean and create release directory
echo "📁 Creating release directory..."
rm -rf "${PROJECT_ROOT}/release"
mkdir -p "${RELEASE_DIR}"

# Copy application files
echo "📋 Copying application files..."
cp "${PROJECT_ROOT}/app/build/videofx_server" "${RELEASE_DIR}/"
cp "${PROJECT_ROOT}/app/videofx_ui.py" "${RELEASE_DIR}/"
cp "${PROJECT_ROOT}/app/control_panel.py" "${RELEASE_DIR}/"
cp "${PROJECT_ROOT}/run.sh" "${RELEASE_DIR}/"
cp "${PROJECT_ROOT}/LICENSE" "${RELEASE_DIR}/"

# Copy SDK libraries (distributable as part of the application)
echo "📚 Copying SDK components..."
mkdir -p "${RELEASE_DIR}/lib"
mkdir -p "${RELEASE_DIR}/models"

# Copy required shared libraries
if [ -d "${PROJECT_ROOT}/sdk/VideoFX/lib" ]; then
    cp -r "${PROJECT_ROOT}/sdk/VideoFX/lib/"*.so* "${RELEASE_DIR}/lib/" 2>/dev/null || true
fi

# Copy AI models
if [ -d "${PROJECT_ROOT}/sdk/VideoFX/share/models" ]; then
    cp -r "${PROJECT_ROOT}/sdk/VideoFX/share/models/"* "${RELEASE_DIR}/models/"
fi

# Create a simple launcher script
cat > "${RELEASE_DIR}/start.sh" << 'EOF'
#!/bin/bash
# VideoFX Studio Launcher
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export LD_LIBRARY_PATH="${SCRIPT_DIR}/lib:${LD_LIBRARY_PATH}"
export NVFX_MODEL_DIR="${SCRIPT_DIR}/models"

cd "${SCRIPT_DIR}"
python3 videofx_ui.py "$@"
EOF
chmod +x "${RELEASE_DIR}/start.sh"

# Create README for the release
cat > "${RELEASE_DIR}/README.txt" << EOF
VideoFX Studio v${VERSION}
========================

Real-time AI-powered video effects using NVIDIA Maxine VideoFX SDK.

REQUIREMENTS:
- NVIDIA GPU with CUDA support
- NVIDIA drivers installed
- Python 3.8+ with PyQt5

QUICK START:
1. Extract this archive
2. Run: ./start.sh

LICENSE:
- Application code: MIT License
- NVIDIA Maxine SDK: NVIDIA proprietary license (see original SDK for terms)

Source code available at: https://github.com/Andrei9383/videofx-app
EOF

# Create the tarball
echo "🗜️  Creating tarball..."
cd "${PROJECT_ROOT}/release"
tar -czvf "${RELEASE_NAME}.tar.gz" "${RELEASE_NAME}"

# Calculate checksum
echo "🔐 Generating checksums..."
sha256sum "${RELEASE_NAME}.tar.gz" > "${RELEASE_NAME}.tar.gz.sha256"

echo ""
echo "✅ Release created successfully!"
echo ""
echo "📁 Files:"
echo "   release/${RELEASE_NAME}.tar.gz"
echo "   release/${RELEASE_NAME}.tar.gz.sha256"
echo ""
echo "📤 To upload to GitHub:"
echo "   1. Go to https://github.com/Andrei9383/videofx-app/releases"
echo "   2. Click 'Draft a new release'"
echo "   3. Create tag: v${VERSION}"
echo "   4. Upload: release/${RELEASE_NAME}.tar.gz"
echo "   5. Upload: release/${RELEASE_NAME}.tar.gz.sha256"
echo "   6. Publish the release!"
