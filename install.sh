#!/bin/bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="blucast"
VCAM_NR=10
VCAM_DEVICE="/dev/video${VCAM_NR}"
VCAM_LABEL="BluCast Virtual Camera"

log()  { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}!${NC} $*"; }
die()  { echo -e "  ${RED}✗${NC} $*"; exit 1; }

echo ""
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}         BluCast Installer${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE}[1/5]${NC} Checking prerequisites..."

if command -v podman &>/dev/null; then
    CONTAINER_CMD="podman"
elif command -v docker &>/dev/null; then
    CONTAINER_CMD="docker"
else
    die "Podman or Docker required.\n        Fedora:  sudo dnf install podman\n        Ubuntu:  sudo apt install podman"
fi
log "Container runtime: $CONTAINER_CMD"

command -v nvidia-smi &>/dev/null || die "NVIDIA driver not found. Install NVIDIA drivers first."
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
log "GPU: $GPU_NAME"

if $CONTAINER_CMD run --rm --device nvidia.com/gpu=all \
    nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null 2>&1; then
    log "NVIDIA Container Toolkit: working"
else
    warn "NVIDIA Container Toolkit may need configuration"
    warn "See: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
fi

echo -e "${BLUE}[2/5]${NC} Setting up virtual camera..."

if ! modinfo v4l2loopback &>/dev/null 2>&1; then
    echo "  Installing v4l2loopback..."
    if command -v dnf &>/dev/null; then
        sudo dnf install -y v4l2loopback kmod-v4l2loopback 2>/dev/null \
            || sudo dnf install -y v4l2loopback 2>/dev/null \
            || die "Failed to install v4l2loopback. Try: sudo dnf install v4l2loopback"
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y v4l2loopback-dkms v4l2loopback-utils \
            || die "Failed to install v4l2loopback. Try: sudo apt install v4l2loopback-dkms"
    else
        die "Unsupported package manager. Install v4l2loopback manually."
    fi
fi
modinfo v4l2loopback &>/dev/null 2>&1 || die "v4l2loopback module not available. Reboot may be needed."
log "v4l2loopback module available"

for tool_pkg in "lsof lsof" "fuser psmisc"; do
    tool="${tool_pkg%% *}"
    pkg="${tool_pkg##* }"
    if ! command -v "$tool" &>/dev/null; then
        if command -v dnf &>/dev/null; then
            sudo dnf install -y "$pkg" 2>/dev/null || true
        elif command -v apt-get &>/dev/null; then
            sudo apt-get install -y "$pkg" 2>/dev/null || true
        fi
    fi
done

echo "v4l2loopback" | sudo tee /etc/modules-load.d/v4l2loopback.conf >/dev/null
echo "options v4l2loopback devices=1 video_nr=${VCAM_NR} card_label=\"${VCAM_LABEL}\" exclusive_caps=1 max_buffers=2 max_openers=10" \
    | sudo tee /etc/modprobe.d/v4l2loopback.conf >/dev/null
log "Module auto-load configured for boot"

cat << EOF | sudo tee /etc/udev/rules.d/83-blucast-vcam.rules >/dev/null
SUBSYSTEM=="video4linux", ATTR{name}=="$VCAM_LABEL", MODE="0666", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules 2>/dev/null || true
log "Udev rule installed"

if lsmod | grep -q v4l2loopback; then
    if [ ! -e "$VCAM_DEVICE" ]; then
        sudo modprobe -r v4l2loopback 2>/dev/null || true
        sleep 1
    fi
fi
if [ ! -e "$VCAM_DEVICE" ]; then
    sudo modprobe v4l2loopback \
        devices=1 \
        video_nr=${VCAM_NR} \
        card_label="${VCAM_LABEL}" \
        exclusive_caps=1 \
        max_buffers=2 \
        max_openers=10
    sleep 1
fi
[ -e "$VCAM_DEVICE" ] || die "Failed to create virtual camera at $VCAM_DEVICE"
sudo chmod 666 "$VCAM_DEVICE" 2>/dev/null || true
sudo udevadm trigger --action=change "$VCAM_DEVICE" 2>/dev/null || true
log "Virtual camera active at $VCAM_DEVICE"

SUDOERS_FILE="/etc/sudoers.d/blucast-v4l2loopback"
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "$(whoami) ALL=(ALL) NOPASSWD: /sbin/modprobe v4l2loopback *" \
        | sudo tee "$SUDOERS_FILE" >/dev/null
    sudo chmod 440 "$SUDOERS_FILE"
    log "Passwordless modprobe configured"
fi

for svc in wireplumber.service xdg-desktop-portal.service \
           xdg-desktop-portal-gtk.service xdg-desktop-portal-gnome.service; do
    systemctl --user restart "$svc" 2>/dev/null || true
done
sleep 2
log "PipeWire/portals refreshed"

echo -e "${BLUE}[3/5]${NC} Checking SDK files..."

SDK_DIR="$SCRIPT_DIR/sdk"
if [ -f "$SCRIPT_DIR/sdk.tar.gz" ] && [ ! -d "$SDK_DIR/VideoFX" ]; then
    echo "  Extracting SDK..."
    tar -xzf "$SCRIPT_DIR/sdk.tar.gz" -C "$SCRIPT_DIR"
fi
[ -d "$SDK_DIR/VideoFX" ]           || die "VideoFX SDK not found in sdk/"
[ -d "$SDK_DIR/TensorRT-8.5.1.7" ]  || die "TensorRT SDK not found in sdk/"
[ -d "$SDK_DIR/cudnn" ]              || die "cuDNN libraries not found in sdk/"
log "All SDK components present"

echo -e "${BLUE}[4/5]${NC} Building container image..."

cd "$SCRIPT_DIR"
$CONTAINER_CMD build -t "$IMAGE_NAME" -f Containerfile . \
    || die "Container build failed"
log "Container image built"

echo -e "${BLUE}[5/5]${NC} Creating desktop entry..."

chmod +x "$SCRIPT_DIR/run.sh"
chmod +x "$SCRIPT_DIR/scripts/vcam_watcher.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/scripts/reset-environment.sh" 2>/dev/null || true

DESKTOP_FILE="$HOME/.local/share/applications/blucast.desktop"
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Name=BluCast
Comment=AI-Powered Virtual Camera
Exec=$SCRIPT_DIR/run.sh
Icon=$SCRIPT_DIR/assets/logo.svg
Terminal=false
Type=Application
Categories=Video;AudioVideo;
StartupWMClass=blucast
DESKTOP
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
log "Desktop entry installed"

echo ""
echo -e "${GREEN}══════════════════════════════════════${NC}"
echo -e "${GREEN}     Installation Complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════${NC}"
echo ""
echo -e "  Launch: ${BLUE}$SCRIPT_DIR/run.sh${NC}"
echo -e "  Or find ${BLUE}BluCast${NC} in your application menu."
echo -e "  Reset:  ${BLUE}$SCRIPT_DIR/scripts/reset-environment.sh${NC}"
echo ""
