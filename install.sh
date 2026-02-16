#!/bin/bash
# BluCast Installation Script

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="blucast"
IMAGE_NAME="blucast"

echo -e "${BLUE}"
echo "======================================"
echo "         BluCast Installer"
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

    refresh_camera_portal() {
        local restarted=false
        for svc in wireplumber.service xdg-desktop-portal.service xdg-desktop-portal-gtk.service xdg-desktop-portal-gnome.service xdg-desktop-portal-wlr.service; do
            if systemctl --user list-unit-files "$svc" >/dev/null 2>&1; then
                systemctl --user restart "$svc" 2>/dev/null || true
                restarted=true
            fi
        done
        if [ "$restarted" = true ]; then
            sleep 2
        fi
    }
    
    if ! command -v modprobe &> /dev/null; then
        echo -e "  ${YELLOW}Skipping v4l2loopback (modprobe not available)${NC}"
        return
    fi
    
    if ! modinfo v4l2loopback &>/dev/null; then
        echo -e "  ${YELLOW}v4l2loopback not installed${NC}"
        echo -e "  Install with: ${BLUE}sudo dnf install v4l2loopback${NC} (Fedora)"
        echo -e "  Install with: ${BLUE}sudo apt install v4l2loopback-dkms${NC} (Ubuntu/Debian)"
        return
    fi
    
    if [ -e /dev/video10 ]; then
        echo -e "  v4l2loopback already loaded at /dev/video10"
        sudo chmod 666 /dev/video10 2>/dev/null || true
    else
        if lsmod | grep -q v4l2loopback; then
            echo -e "  v4l2loopback loaded with wrong device number, reloading..."
            sudo modprobe -r v4l2loopback || true
            sleep 1
        fi

        sudo modprobe v4l2loopback \
            devices=1 \
            video_nr=10 \
            card_label="BluCast Camera" \
            exclusive_caps=1 \
            max_buffers=2 \
            max_openers=10 || true

        sleep 1
    fi

    # Persist v4l2loopback options so the module loads correctly across reboots
    MODPROBE_CONF="/etc/modprobe.d/v4l2loopback.conf"
    MODPROBE_LINE='options v4l2loopback devices=1 video_nr=10 card_label="BluCast Camera" exclusive_caps=1 max_buffers=2 max_openers=10'
    if [ ! -f "$MODPROBE_CONF" ] || ! grep -q 'video_nr=10' "$MODPROBE_CONF" 2>/dev/null; then
        echo "$MODPROBE_LINE" | sudo tee "$MODPROBE_CONF" >/dev/null 2>&1 || true
        echo -e "  Created ${BLUE}$MODPROBE_CONF${NC} for persistence"
    fi
    
    if [ -e /dev/video10 ]; then
        sudo chmod 666 /dev/video10 2>/dev/null || true
        echo -e "  Virtual camera created at /dev/video10"
        
        # Install udev rule to force capture caps (omg firefox)
        UDEV_RULE='SUBSYSTEM=="video4linux", KERNEL=="video10", ENV{ID_V4L_PRODUCT}="BluCast Camera", ENV{ID_V4L_CAPABILITIES}=":capture:"'
        UDEV_RULE_FILE="/etc/udev/rules.d/83-blucast-vcam.rules"
        if [ ! -f "$UDEV_RULE_FILE" ] || ! grep -q "KERNEL==\"video10\"" "$UDEV_RULE_FILE" 2>/dev/null; then
            echo "$UDEV_RULE" | sudo tee "$UDEV_RULE_FILE" >/dev/null 2>&1 || true
            sudo udevadm control --reload-rules 2>/dev/null || true
        fi
        if command -v udevadm &>/dev/null; then
            sudo udevadm trigger --action=change /dev/video10 2>/dev/null || true
            sleep 1
        fi
        # Restart WirePlumber to pick up corrected udev properties
        if command -v wpctl &> /dev/null; then
            echo -e "  Registering virtual camera with PipeWire..."
            refresh_camera_portal
            if wpctl status 2>/dev/null | grep -qi "blucast\|video10"; then
                echo -e "  Virtual camera registered with PipeWire"
            else
                echo -e "  ${YELLOW}Warning: Virtual camera may not be visible to PipeWire apps${NC}"
                echo -e "  Try: ${BLUE}systemctl --user restart wireplumber xdg-desktop-portal${NC}"
            fi
        fi
    else
        echo -e "  ${YELLOW}Warning: Could not create virtual camera at /dev/video10${NC}"
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
    
    DESKTOP_FILE="$HOME/.local/share/applications/blucast.desktop"
    mkdir -p "$(dirname "$DESKTOP_FILE")"
    
    cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Name=BluCast
Comment=AI-Powered Video Effects
Exec=$SCRIPT_DIR/run.sh
Icon=$SCRIPT_DIR/assets/logo.svg
Terminal=false
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
    echo -e "To start BluCast:"
    echo -e "  ${BLUE}cd $SCRIPT_DIR && ./run.sh${NC}"
    echo ""
}

main "$@"
