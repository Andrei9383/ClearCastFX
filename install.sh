#!/bin/bash
#
# VideoFX Portable App - Installation Script
# One-line installer for NVIDIA VideoFX SDK with webcam UI
#
# Usage: ./install.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="videofx-app"
IMAGE_NAME="videofx-studio"

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                                                              ║"
echo "║     🎥 VideoFX Studio - NVIDIA AI Video Effects             ║"
echo "║                                                              ║"
echo "║     Powered by NVIDIA Maxine VideoFX SDK                    ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check for required tools
check_requirements() {
    echo -e "${YELLOW}[1/5]${NC} Checking requirements..."
    
    # Check for podman or docker
    if command -v podman &> /dev/null; then
        CONTAINER_CMD="podman"
        echo -e "  ✅ Found podman"
    elif command -v docker &> /dev/null; then
        CONTAINER_CMD="docker"
        echo -e "  ✅ Found docker"
    else
        echo -e "  ${RED}❌ Error: podman or docker is required${NC}"
        echo -e "  Install with: ${BLUE}sudo dnf install podman${NC}"
        exit 1
    fi
    
    # Check for NVIDIA driver
    if ! command -v nvidia-smi &> /dev/null; then
        echo -e "  ${RED}❌ Error: NVIDIA driver not found${NC}"
        echo -e "  Please install NVIDIA drivers first"
        exit 1
    fi
    
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    echo -e "  ✅ NVIDIA GPU detected: ${GREEN}${GPU_NAME}${NC}"
    
    # Check for NVIDIA Container Toolkit
    if ! $CONTAINER_CMD run --rm --device nvidia.com/gpu=all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null; then
        echo -e "  ${YELLOW}⚠️  NVIDIA Container Toolkit may not be configured${NC}"
        echo -e "  Install with: ${BLUE}sudo dnf install nvidia-container-toolkit${NC}"
    else
        echo -e "  ✅ NVIDIA Container Toolkit working"
    fi
}

# Install v4l2loopback for virtual camera
install_v4l2loopback() {
    echo -e "${YELLOW}[2/5]${NC} Setting up virtual camera support..."
    
    if lsmod | grep -q v4l2loopback; then
        echo -e "  ✅ v4l2loopback already loaded"
        return
    fi
    
    if ! command -v modprobe &> /dev/null; then
        echo -e "  ${YELLOW}⚠️  Skipping v4l2loopback (modprobe not available)${NC}"
        return
    fi
    
    # Check if module is available
    if modinfo v4l2loopback &>/dev/null; then
        echo -e "  Loading v4l2loopback module..."
        sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="VideoFX Camera" exclusive_caps=1 || true
        echo -e "  ✅ Virtual camera device created at /dev/video10"
    else
        echo -e "  ${YELLOW}⚠️  v4l2loopback not installed${NC}"
        echo -e "  Install with: ${BLUE}sudo dnf install v4l2loopback${NC}"
        echo -e "  Or: ${BLUE}sudo dnf install akmod-v4l2loopback${NC} (for DKMS)"
    fi
}

# Extract SDK from archive
prepare_sdk() {
    echo -e "${YELLOW}[3/5]${NC} Preparing SDK files..."
    
    SDK_DIR="$SCRIPT_DIR/sdk"
    SDK_ARCHIVE="$SCRIPT_DIR/sdk.tar.gz"
    
    # Check if SDK needs to be extracted from archive
    if [ ! -d "$SDK_DIR/VideoFX" ]; then
        if [ -f "$SDK_ARCHIVE" ]; then
            echo -e "  Extracting SDK from archive (this may take a moment)..."
            tar -xzf "$SDK_ARCHIVE" -C "$SCRIPT_DIR"
            echo -e "  ✅ SDK extracted successfully"
        else
            echo -e "  ${RED}❌ SDK archive not found at $SDK_ARCHIVE${NC}"
            echo -e "  ${YELLOW}Please ensure sdk.tar.gz is present in the project directory${NC}"
            exit 1
        fi
    else
        echo -e "  ✅ SDK already extracted"
    fi
    
    # Verify all required SDK components are present
    if [ ! -d "$SDK_DIR/VideoFX" ]; then
        echo -e "  ${RED}❌ VideoFX SDK not found${NC}"
        exit 1
    fi
    echo -e "  ✅ VideoFX SDK ready"
    
    if [ ! -d "$SDK_DIR/TensorRT-8.5.1.7" ]; then
        echo -e "  ${RED}❌ TensorRT SDK not found${NC}"
        exit 1
    fi
    echo -e "  ✅ TensorRT SDK ready"
    
    if [ ! -d "$SDK_DIR/cudnn" ]; then
        echo -e "  ${RED}❌ cuDNN libraries not found${NC}"
        exit 1
    fi
    echo -e "  ✅ cuDNN libraries ready"
}

# Build container image
build_container() {
    echo -e "${YELLOW}[4/5]${NC} Building container image..."
    echo -e "  This may take a few minutes..."
    
    cd "$SCRIPT_DIR"
    
    if $CONTAINER_CMD build -t "$IMAGE_NAME" -f Containerfile . ; then
        echo -e "  ✅ Container image built successfully"
    else
        echo -e "  ${RED}❌ Container build failed${NC}"
        exit 1
    fi
}

# Create launcher script
create_launcher() {
    echo -e "${YELLOW}[5/5]${NC} Creating launcher..."
    
    cat > "$SCRIPT_DIR/run.sh" << 'LAUNCHER'
#!/bin/bash
# VideoFX Studio Launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="videofx-studio"

# Detect container runtime
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
else
    CONTAINER_CMD="docker"
fi

# Ensure v4l2loopback is loaded (silent fail is ok)
if ! lsmod | grep -q v4l2loopback 2>/dev/null; then
    sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="VideoFX Camera" exclusive_caps=1 2>/dev/null || true
fi

# Allow X11 connections from container
xhost +local: 2>/dev/null || true

# Build device arguments for cameras
CAMERA_ARGS=""
for cam in /dev/video*; do
    if [ -e "$cam" ]; then
        CAMERA_ARGS="$CAMERA_ARGS --device $cam:$cam"
    fi
done

if [ -z "$CAMERA_ARGS" ]; then
    echo "⚠️  No camera devices found. The app will start but camera may not work."
fi

echo "🎥 Starting VideoFX Studio..."

# Run the container with GPU and display access
$CONTAINER_CMD run --rm -it \
    --security-opt label=disable \
    --device nvidia.com/gpu=all \
    --runtime=nvidia 2>/dev/null || true \
    $CAMERA_ARGS \
    -e DISPLAY=$DISPLAY \
    -e QT_X11_NO_MITSHM=1 \
    -e NVIDIA_DRIVER_CAPABILITIES=all \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -v "$HOME/.Xauthority:/root/.Xauthority:ro" \
    -v "$SCRIPT_DIR/output:/output" \
    --ipc=host \
    --network host \
    "$IMAGE_NAME" 2>&1

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ VideoFX Studio exited with code $EXIT_CODE"
    echo ""
    echo "Common issues:"
    echo "  • No camera: Plug in a webcam and try again"
    echo "  • Display error: Run 'xhost +local:' first"
    echo "  • GPU error: Check 'nvidia-smi' works"
    echo ""
fi
LAUNCHER

    chmod +x "$SCRIPT_DIR/run.sh"
    echo -e "  ✅ Launcher created: ${GREEN}$SCRIPT_DIR/run.sh${NC}"
    
    # Create desktop entry
    DESKTOP_FILE="$HOME/.local/share/applications/videofx-studio.desktop"
    mkdir -p "$(dirname "$DESKTOP_FILE")"
    
    cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Name=VideoFX Studio
Comment=NVIDIA AI Video Effects
Exec=$SCRIPT_DIR/run.sh
Icon=camera-video
Terminal=true
Type=Application
Categories=Video;AudioVideo;
DESKTOP

    echo -e "  ✅ Desktop entry created"
}

# Main installation
main() {
    check_requirements
    install_v4l2loopback
    prepare_sdk
    build_container
    create_launcher
    
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                              ║${NC}"
    echo -e "${GREEN}║     ✅ Installation Complete!                                ║${NC}"
    echo -e "${GREEN}║                                                              ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "To start VideoFX Studio, run:"
    echo -e "  ${BLUE}cd $SCRIPT_DIR && ./run.sh${NC}"
    echo ""
    echo -e "Or launch from your applications menu."
    echo ""
}

main "$@"
