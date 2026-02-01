#!/bin/bash
# ClearCastFX Installation Script

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="clearcastfx"
IMAGE_NAME="clearcastfx"

echo -e "${BLUE}"
echo "======================================"
echo "         ClearCastFX Installer"
echo "    AI-Powered Video Effects"
echo "======================================"
echo -e "${NC}"

check_requirements() {
    echo -e "${YELLOW}[1/5]${NC} Checking requirements..."
    
    if command -v podman &> /dev/null; then
        CONTAINER_CMD="podman"
        echo -e "  Found podman"
    elif command -v docker &> /dev/null; then
        CONTAINER_CMD="docker"
        echo -e "  Found docker"
    else
        echo -e "  ${RED}Error: podman or docker is required${NC}"
        echo -e "  Install with: ${BLUE}sudo dnf install podman${NC}"
        exit 1
    fi
    
    if ! command -v nvidia-smi &> /dev/null; then
        echo -e "  ${RED}Error: NVIDIA driver not found${NC}"
        exit 1
    fi
    
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    echo -e "  NVIDIA GPU detected: ${GREEN}${GPU_NAME}${NC}"
    
    if ! $CONTAINER_CMD run --rm --device nvidia.com/gpu=all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null; then
        echo -e "  ${YELLOW}Warning: NVIDIA Container Toolkit may not be configured${NC}"
    else
        echo -e "  NVIDIA Container Toolkit working"
    fi
}

install_v4l2loopback() {
    echo -e "${YELLOW}[2/5]${NC} Setting up virtual camera..."
    
    if lsmod | grep -q v4l2loopback; then
        echo -e "  v4l2loopback already loaded"
        return
    fi
    
    if ! command -v modprobe &> /dev/null; then
        echo -e "  ${YELLOW}Skipping v4l2loopback (modprobe not available)${NC}"
        return
    fi
    
    if modinfo v4l2loopback &>/dev/null; then
        sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="ClearCastFX Camera" exclusive_caps=1 || true
        echo -e "  Virtual camera created at /dev/video10"
    else
        echo -e "  ${YELLOW}v4l2loopback not installed${NC}"
        echo -e "  Install with: ${BLUE}sudo dnf install v4l2loopback${NC}"
    fi
}

prepare_sdk() {
    echo -e "${YELLOW}[3/5]${NC} Preparing SDK files..."
    
    SDK_DIR="$SCRIPT_DIR/sdk"
    SDK_ARCHIVE="$SCRIPT_DIR/sdk.tar.gz"
    
    if [ ! -d "$SDK_DIR/VideoFX" ]; then
        if [ -f "$SDK_ARCHIVE" ]; then
            echo -e "  Extracting SDK..."
            tar -xzf "$SDK_ARCHIVE" -C "$SCRIPT_DIR"
            echo -e "  SDK extracted"
        else
            echo -e "  ${RED}SDK archive not found at $SDK_ARCHIVE${NC}"
            exit 1
        fi
    else
        echo -e "  SDK already extracted"
    fi
    
    if [ ! -d "$SDK_DIR/VideoFX" ]; then
        echo -e "  ${RED}VideoFX SDK not found${NC}"
        exit 1
    fi
    echo -e "  VideoFX SDK ready"
    
    if [ ! -d "$SDK_DIR/TensorRT-8.5.1.7" ]; then
        echo -e "  ${RED}TensorRT SDK not found${NC}"
        exit 1
    fi
    echo -e "  TensorRT SDK ready"
    
    if [ ! -d "$SDK_DIR/cudnn" ]; then
        echo -e "  ${RED}cuDNN libraries not found${NC}"
        exit 1
    fi
    echo -e "  cuDNN libraries ready"
}

build_container() {
    echo -e "${YELLOW}[4/5]${NC} Building container image..."
    
    cd "$SCRIPT_DIR"
    
    if $CONTAINER_CMD build -t "$IMAGE_NAME" -f Containerfile . ; then
        echo -e "  Container image built"
    else
        echo -e "  ${RED}Container build failed${NC}"
        exit 1
    fi
}

create_launcher() {
    echo -e "${YELLOW}[5/5]${NC} Creating launcher..."
    
    chmod +x "$SCRIPT_DIR/run.sh"
    echo -e "  Launcher ready: ${GREEN}$SCRIPT_DIR/run.sh${NC}"
    
    DESKTOP_FILE="$HOME/.local/share/applications/clearcastfx.desktop"
    mkdir -p "$(dirname "$DESKTOP_FILE")"
    
    cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Name=ClearCastFX
Comment=AI-Powered Video Effects
Exec=$SCRIPT_DIR/run.sh
Icon=camera-video
Terminal=true
Type=Application
Categories=Video;AudioVideo;
DESKTOP

    echo -e "  Desktop entry created"
}

main() {
    check_requirements
    install_v4l2loopback
    prepare_sdk
    build_container
    create_launcher
    
    echo ""
    echo -e "${GREEN}======================================"
    echo "       Installation Complete!"
    echo "======================================${NC}"
    echo ""
    echo -e "To start ClearCastFX:"
    echo -e "  ${BLUE}cd $SCRIPT_DIR && ./run.sh${NC}"
    echo ""
}

main "$@"
