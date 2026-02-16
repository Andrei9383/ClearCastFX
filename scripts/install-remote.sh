#!/bin/bash
# BluCast Remote Installation Script
# Downloads and sets up BluCast from GitHub Container Registry

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

GHCR_IMAGE="ghcr.io/andrei9383/blucast:latest"
INSTALL_DIR="$HOME/.local/share/blucast"
BIN_DIR="$HOME/.local/bin"

echo -e "${BLUE}"
echo "======================================"
echo "     BluCast Quick Installer"
echo "    AI-Powered Video Effects"
echo "======================================"
echo -e "${NC}"

# Check requirements
check_requirements() {
    echo -e "${YELLOW}[1/4]${NC} Checking requirements..."
    
    # Check container runtime
    if command -v podman &> /dev/null; then
        CONTAINER_CMD="podman"
        echo -e "  Found podman"
    elif command -v docker &> /dev/null; then
        CONTAINER_CMD="docker"
        echo -e "  Found docker"
    else
        echo -e "  ${RED}Error: podman or docker is required${NC}"
        echo -e "  Install with:"
        echo -e "    Fedora: ${BLUE}sudo dnf install podman${NC}"
        echo -e "    Ubuntu: ${BLUE}sudo apt install podman${NC}"
        exit 1
    fi
    
    # Check NVIDIA driver
    if ! command -v nvidia-smi &> /dev/null; then
        echo -e "  ${RED}Error: NVIDIA driver not found${NC}"
        echo -e "  Please install NVIDIA drivers first"
        exit 1
    fi
    
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    echo -e "  NVIDIA GPU detected: ${GREEN}${GPU_NAME}${NC}"
    
    # Check NVIDIA Container Toolkit
    if ! $CONTAINER_CMD run --rm --device nvidia.com/gpu=all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null; then
        echo -e "  ${YELLOW}Warning: NVIDIA Container Toolkit may not be configured${NC}"
        echo -e "  Install with:"
        echo -e "    Fedora: ${BLUE}sudo dnf install nvidia-container-toolkit${NC}"
        echo -e "    Ubuntu: See https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
    else
        echo -e "  NVIDIA Container Toolkit working"
    fi
}

# Setup v4l2loopback for virtual camera
setup_vcam() {
    echo -e "${YELLOW}[2/4]${NC} Setting up virtual camera..."

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
    
    if modinfo v4l2loopback &>/dev/null; then
        if [ -e /dev/video10 ]; then
            echo -e "  v4l2loopback already loaded at /dev/video10"
            sudo chmod 666 /dev/video10 2>/dev/null || true
        else
            if lsmod | grep -q v4l2loopback 2>/dev/null; then
                echo -e "  v4l2loopback loaded with wrong device number, reloading..."
                sudo modprobe -r v4l2loopback 2>/dev/null || true
                sleep 1
            fi
            sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="BluCast Camera" exclusive_caps=1 max_buffers=2 max_openers=10 || true
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
        else
            echo -e "  ${YELLOW}Warning: Could not create virtual camera at /dev/video10${NC}"
        fi
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
        if command -v wpctl &> /dev/null; then
            echo -e "  Registering virtual camera with PipeWire..."
            refresh_camera_portal
        fi
    else
        echo -e "  ${YELLOW}v4l2loopback not installed${NC}"
        echo -e "  Install with:"
        echo -e "    Fedora: ${BLUE}sudo dnf install v4l2loopback${NC}"
        echo -e "    Ubuntu: ${BLUE}sudo apt install v4l2loopback-dkms${NC}"
    fi
}

# Pull container from GHCR
pull_container() {
    echo -e "${YELLOW}[3/4]${NC} Pulling BluCast container..."
    echo -e "  This may take a few minutes on first install..."
    
    if $CONTAINER_CMD pull "$GHCR_IMAGE"; then
        echo -e "  Container pulled successfully"
    else
        echo -e "  ${RED}Failed to pull container${NC}"
        exit 1
    fi
}

# Create launcher scripts
create_launcher() {
    echo -e "${YELLOW}[4/4]${NC} Creating launcher..."
    
    mkdir -p "$INSTALL_DIR" "$BIN_DIR"
    
    # Create run script
    cat > "$INSTALL_DIR/run.sh" << 'RUNSCRIPT'
#!/bin/bash
# BluCast Launcher

GHCR_IMAGE="ghcr.io/andrei9383/blucast:latest"

# Detect container runtime
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
else
    CONTAINER_CMD="docker"
fi

# Ensure v4l2loopback is loaded
if ! lsmod | grep -q v4l2loopback 2>/dev/null; then
    sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="BluCast Camera" exclusive_caps=1 2>/dev/null || true
fi

# Install udev rule and restart WirePlumber for Firefox Camera portal
UDEV_RULE='SUBSYSTEM=="video4linux", KERNEL=="video10", ENV{ID_V4L_PRODUCT}="BluCast Camera", ENV{ID_V4L_CAPABILITIES}=":capture:"'
UDEV_RULE_FILE="/etc/udev/rules.d/83-blucast-vcam.rules"
if [ -e /dev/video10 ]; then
    if [ ! -f "$UDEV_RULE_FILE" ] || ! grep -q "KERNEL==\"video10\"" "$UDEV_RULE_FILE" 2>/dev/null; then
        echo "$UDEV_RULE" | sudo tee "$UDEV_RULE_FILE" >/dev/null 2>&1 || true
        sudo udevadm control --reload-rules 2>/dev/null || true
    fi
    if command -v udevadm &>/dev/null; then
        sudo udevadm trigger --action=change /dev/video10 2>/dev/null || true
        sleep 1
    fi
    if command -v wpctl &> /dev/null; then
        for svc in wireplumber.service xdg-desktop-portal.service xdg-desktop-portal-gtk.service xdg-desktop-portal-gnome.service xdg-desktop-portal-wlr.service; do
            if systemctl --user list-unit-files "$svc" >/dev/null 2>&1; then
                systemctl --user restart "$svc" 2>/dev/null || true
            fi
        done
        sleep 2
    fi
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

echo "Starting BluCast..."

# Shared IPC directory
mkdir -p /tmp/blucast

# Create config directory for persistent settings
CONFIG_DIR="$HOME/.config/blucast"
mkdir -p "$CONFIG_DIR"

# Configure GPU arguments based on container runtime
if [ "$CONTAINER_CMD" = "podman" ]; then
    GPU_ARGS="--device nvidia.com/gpu=all"
else
    GPU_ARGS="--gpus all"
fi

# Handle Xauthority
XAUTH_ARGS=""
CONTAINER_XAUTH="/tmp/blucast/.docker.xauth"
if command -v xauth &> /dev/null && [ -n "$DISPLAY" ]; then
    # Generate a fresh Xauthority file with the current display's cookie
    touch "$CONTAINER_XAUTH"
    xauth nlist "$DISPLAY" 2>/dev/null | sed -e 's/^..../ffff/' | xauth -f "$CONTAINER_XAUTH" nmerge - 2>/dev/null
    if [ -s "$CONTAINER_XAUTH" ]; then
        XAUTH_ARGS="-v $CONTAINER_XAUTH:/root/.Xauthority:ro -e XAUTHORITY=/root/.Xauthority"
    fi
fi
# Or mount existing Xauthority file directly
if [ -z "$XAUTH_ARGS" ]; then
    if [ -n "$XAUTHORITY" ] && [ -f "$XAUTHORITY" ]; then
        XAUTH_ARGS="-v $XAUTHORITY:/root/.Xauthority:ro"
    elif [ -f "$HOME/.Xauthority" ]; then
        XAUTH_ARGS="-v $HOME/.Xauthority:/root/.Xauthority:ro"
    fi
fi

# D-Bus socket for system tray support
DBUS_ARGS=""
if [ -n "$DBUS_SESSION_BUS_ADDRESS" ]; then
    DBUS_SOCKET="${DBUS_SESSION_BUS_ADDRESS#unix:path=}"
    DBUS_SOCKET="${DBUS_SOCKET%%,*}"
    if [ -S "$DBUS_SOCKET" ]; then
        DBUS_ARGS="-v $DBUS_SOCKET:$DBUS_SOCKET -e DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
    fi
fi

$CONTAINER_CMD run --rm \
    --security-opt label=disable \
    $GPU_ARGS \
    $CAMERA_ARGS \
    -e DISPLAY=$DISPLAY \
    -e NVIDIA_DRIVER_CAPABILITIES=all \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -e HOME=/host_home \
    -e QT_QPA_PLATFORM=xcb \
    -e QT_LOGGING_RULES="*.debug=false" \
    -e XDG_RUNTIME_DIR=/tmp/runtime-root \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    $XAUTH_ARGS \
    $DBUS_ARGS \
    -v "$HOME:/host_home:ro" \
    -v "$CONFIG_DIR:/root/.config/blucast:rw" \
    -v "/tmp/blucast:/tmp/blucast:rw" \
    --ipc=host \
    --network host \
    "$GHCR_IMAGE" 2>&1

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "BluCast exited with code $EXIT_CODE"
    echo ""
    echo "Common issues:"
    echo "  - No camera: Plug in a webcam and try again"
    echo "  - Display error: Run 'xhost +local:' first"
    echo "  - GPU error: Check 'nvidia-smi' works"
fi
RUNSCRIPT

    chmod +x "$INSTALL_DIR/run.sh"
    
    # Create symlink in bin directory
    ln -sf "$INSTALL_DIR/run.sh" "$BIN_DIR/blucast"
    
    # Download logo for desktop entry
    LOGO_URL="https://raw.githubusercontent.com/Andrei9383/BluCast/main/assets/logo.svg"
    LOGO_PATH="$INSTALL_DIR/logo.svg"
    if command -v curl &> /dev/null; then
        curl -fsSL "$LOGO_URL" -o "$LOGO_PATH" 2>/dev/null || true
    elif command -v wget &> /dev/null; then
        wget -q "$LOGO_URL" -O "$LOGO_PATH" 2>/dev/null || true
    fi

    # Create desktop entry
    DESKTOP_FILE="$HOME/.local/share/applications/blucast.desktop"
    mkdir -p "$(dirname "$DESKTOP_FILE")"
    
    # Use downloaded logo if available, otherwise fall back to generic icon
    if [ -f "$LOGO_PATH" ]; then
        ICON_VALUE="$LOGO_PATH"
    else
        ICON_VALUE="camera-video"
    fi

    cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Name=BluCast
Comment=AI-Powered Video Effects
Exec=$INSTALL_DIR/run.sh
Icon=$ICON_VALUE
Terminal=false
Type=Application
Categories=Video;AudioVideo;
DESKTOP

    echo -e "  Launcher created: ${GREEN}blucast${NC}"
    echo -e "  Desktop entry created"
}

# Main
main() {
    check_requirements
    setup_vcam
    pull_container
    create_launcher
    
    echo ""
    echo -e "${GREEN}======================================"
    echo "       Installation Complete!"
    echo "======================================${NC}"
    echo ""
    echo -e "To start BluCast, run:"
    echo -e "  ${BLUE}blucast${NC}"
    echo ""
    echo -e "Or find it in your application menu."
    echo ""
    
    # Check if ~/.local/bin is in PATH
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        echo -e "${YELLOW}Note:${NC} ~/.local/bin is not in your PATH."
        echo -e "  Run the following, then ${GREEN}restart your terminal${NC} (or run ${BLUE}source ~/.bashrc${NC}):"
        echo -e "  ${BLUE}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc${NC}"
        echo ""
    else
        echo -e "${YELLOW}Note:${NC} If 'blucast' is not found, restart your terminal or run: ${BLUE}source ~/.bashrc${NC}"
        echo ""
    fi
}

main "$@"
