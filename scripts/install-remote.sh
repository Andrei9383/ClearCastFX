#!/bin/bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

GHCR_IMAGE="ghcr.io/andrei9383/blucast:latest"
INSTALL_DIR="$HOME/.local/share/blucast"
BIN_DIR="$HOME/.local/bin"
VCAM_NR=10
VCAM_DEVICE="/dev/video${VCAM_NR}"
VCAM_LABEL="BluCast Virtual Camera"

log()  { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}!${NC} $*"; }
die()  { echo -e "  ${RED}✗${NC} $*"; exit 1; }

echo ""
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}     BluCast Quick Installer${NC}"
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
        devices=1 video_nr=${VCAM_NR} card_label="${VCAM_LABEL}" \
        exclusive_caps=1 max_buffers=2 max_openers=10
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

echo -e "${BLUE}[3/5]${NC} Pulling BluCast container..."
echo "  This may take a few minutes on first install..."

$CONTAINER_CMD pull "$GHCR_IMAGE" || die "Failed to pull container image"
log "Container image pulled"

echo -e "${BLUE}[4/5]${NC} Creating launcher..."

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

cat > "$INSTALL_DIR/vcam_watcher.sh" << 'WATCHER_EOF'
#!/bin/bash
# BluCast Virtual Camera Consumer Watcher
# Counts processes READING from /dev/video10.
# Server opens O_WRONLY (lsof: 'w'), browsers open O_RDWR (lsof: 'u').

VCAM_DEVICE="${1:-/dev/video10}"
CONSUMERS_FILE="/tmp/blucast/consumers"

mkdir -p /tmp/blucast
echo "0" > "$CONSUMERS_FILE"

count_with_lsof() {
    lsof "$VCAM_DEVICE" 2>/dev/null | awk '
        NR > 1 && $4 ~ /[0-9]+[ru]$/ { pids[$2] = 1 }
        END { print length(pids) }
    '
}

count_with_fuser() {
    local pids total n
    pids=$(fuser "$VCAM_DEVICE" 2>/dev/null) || true
    total=$(echo "$pids" | wc -w)
    n=$((total - 1))
    [ $n -lt 0 ] && n=0
    echo "$n"
}

if command -v lsof &>/dev/null; then
    COUNT_FN="count_with_lsof"
elif command -v fuser &>/dev/null; then
    COUNT_FN="count_with_fuser"
else
    while true; do echo "0" > "$CONSUMERS_FILE"; sleep 5; done
    exit 0
fi

while true; do
    if [ ! -e "$VCAM_DEVICE" ]; then
        echo "0" > "$CONSUMERS_FILE"
        sleep 2
        continue
    fi
    n=$($COUNT_FN)
    [[ "$n" =~ ^[0-9]+$ ]] || n=0
    echo "$n" > "$CONSUMERS_FILE"
    sleep 1
done
WATCHER_EOF
chmod +x "$INSTALL_DIR/vcam_watcher.sh"

cat > "$INSTALL_DIR/run.sh" << 'RUNSCRIPT_EOF'
#!/bin/bash
set -euo pipefail

GHCR_IMAGE="ghcr.io/andrei9383/blucast:latest"
VCAM_DEVICE="/dev/video10"
SHARED_DIR="/tmp/blucast"
INSTALL_DIR="$HOME/.local/share/blucast"

if command -v podman &>/dev/null; then
    CONTAINER_CMD="podman"
elif command -v docker &>/dev/null; then
    CONTAINER_CMD="docker"
else
    echo "Error: podman or docker required"; exit 1
fi

if [ ! -e "$VCAM_DEVICE" ]; then
    echo "Loading virtual camera module..."
    if sudo -n modprobe v4l2loopback devices=1 video_nr=10 \
        card_label="BluCast Virtual Camera" exclusive_caps=1 \
        max_buffers=2 max_openers=10 2>/dev/null; then
        sleep 1
    elif command -v pkexec &>/dev/null; then
        pkexec modprobe v4l2loopback devices=1 video_nr=10 \
            card_label="BluCast Virtual Camera" exclusive_caps=1 \
            max_buffers=2 max_openers=10
        sleep 1
    else
        echo "Error: Cannot load v4l2loopback module."
        exit 1
    fi
fi

[ -e "$VCAM_DEVICE" ] || { echo "Error: $VCAM_DEVICE not found"; exit 1; }

sudo -n chmod 666 "$VCAM_DEVICE" 2>/dev/null || chmod 666 "$VCAM_DEVICE" 2>/dev/null || true
sudo -n udevadm trigger --action=change "$VCAM_DEVICE" 2>/dev/null || true
sleep 1

for svc in wireplumber.service xdg-desktop-portal.service \
           xdg-desktop-portal-gtk.service xdg-desktop-portal-gnome.service; do
    systemctl --user restart "$svc" 2>/dev/null || true
done
sleep 2

mkdir -p "$SHARED_DIR"
echo "0" > "$SHARED_DIR/consumers"
rm -f "$SHARED_DIR/preview.jpg" "$SHARED_DIR/cmd.pipe"

xhost +local: 2>/dev/null || true

WATCHER_PID=""
if [ -x "$INSTALL_DIR/vcam_watcher.sh" ]; then
    "$INSTALL_DIR/vcam_watcher.sh" "$VCAM_DEVICE" &
    WATCHER_PID=$!
fi

cleanup() {
    [ -n "$WATCHER_PID" ] && kill "$WATCHER_PID" 2>/dev/null || true
    rm -f "$SHARED_DIR/consumers" "$SHARED_DIR/preview.jpg" "$SHARED_DIR/cmd.pipe" \
          "$SHARED_DIR/server.pid" "$SHARED_DIR/.xauth"
}
trap cleanup EXIT

if [ "$CONTAINER_CMD" = "podman" ]; then
    GPU_ARGS="--device nvidia.com/gpu=all"
else
    GPU_ARGS="--gpus all"
fi

CAMERA_ARGS=""
for cam in /dev/video*; do
    [ -e "$cam" ] && CAMERA_ARGS="$CAMERA_ARGS --device $cam:$cam"
done

XAUTH_ARGS=""
XAUTH_FILE="$SHARED_DIR/.xauth"
if command -v xauth &>/dev/null && [ -n "${DISPLAY:-}" ]; then
    touch "$XAUTH_FILE"
    xauth nlist "$DISPLAY" 2>/dev/null | sed -e 's/^..../ffff/' \
        | xauth -f "$XAUTH_FILE" nmerge - 2>/dev/null || true
    if [ -s "$XAUTH_FILE" ]; then
        XAUTH_ARGS="-v $XAUTH_FILE:/root/.Xauthority:ro -e XAUTHORITY=/root/.Xauthority"
    fi
fi
if [ -z "$XAUTH_ARGS" ]; then
    for f in "${XAUTHORITY:-}" "$HOME/.Xauthority"; do
        if [ -n "$f" ] && [ -f "$f" ]; then
            XAUTH_ARGS="-v $f:/root/.Xauthority:ro"
            break
        fi
    done
fi

DBUS_ARGS=""
if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    DBUS_SOCKET="${DBUS_SESSION_BUS_ADDRESS#unix:path=}"
    DBUS_SOCKET="${DBUS_SOCKET%%,*}"
    if [ -S "$DBUS_SOCKET" ]; then
        DBUS_ARGS="-v $DBUS_SOCKET:$DBUS_SOCKET -e DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
    fi
fi

CONFIG_DIR="$HOME/.config/blucast"
mkdir -p "$CONFIG_DIR"

echo "Starting BluCast..."

$CONTAINER_CMD run --rm \
    --security-opt label=disable \
    $GPU_ARGS \
    $CAMERA_ARGS \
    -e DISPLAY="${DISPLAY:-:0}" \
    -e NVIDIA_DRIVER_CAPABILITIES=all \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -e QT_QPA_PLATFORM=xcb \
    -e QT_LOGGING_RULES="*.debug=false" \
    -e XDG_RUNTIME_DIR=/tmp/runtime-root \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    $XAUTH_ARGS \
    $DBUS_ARGS \
    -v "$HOME:/host_home:ro" \
    -v "$CONFIG_DIR:/root/.config/blucast:rw" \
    -v "$SHARED_DIR:$SHARED_DIR:rw" \
    -v "/dev/dri:/dev/dri" \
    --ipc=host \
    --network host \
    "$GHCR_IMAGE" 2>&1
RUNSCRIPT_EOF
chmod +x "$INSTALL_DIR/run.sh"

cat > "$INSTALL_DIR/reset-environment.sh" << 'RESET_EOF'
#!/bin/bash
set -euo pipefail

echo "Stopping containers..."
for cmd in podman docker; do
    command -v "$cmd" &>/dev/null || continue
    for pat in blucast "ghcr.io/andrei9383/blucast"; do
        ids=$($cmd ps -q --filter "ancestor=$pat" 2>/dev/null || true)
        [ -n "$ids" ] && $cmd stop $ids 2>/dev/null || true
    done
done

pkill -f "vcam_watcher" 2>/dev/null || true
sudo modprobe -r v4l2loopback 2>/dev/null || true
sudo rm -f /etc/modules-load.d/v4l2loopback.conf \
           /etc/modprobe.d/v4l2loopback.conf \
           /etc/udev/rules.d/83-blucast-vcam.rules \
           /etc/sudoers.d/blucast-v4l2loopback
sudo udevadm control --reload-rules 2>/dev/null || true
rm -rf "$HOME/.config/blucast"
rm -f "$HOME/.local/share/applications/blucast.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
rm -rf /tmp/blucast
rm -f "$HOME/.local/bin/blucast"

for cmd in podman docker; do
    command -v "$cmd" &>/dev/null || continue
    for img in "ghcr.io/andrei9383/blucast:latest"; do
        $cmd rmi "$img" 2>/dev/null || true
    done
done

for svc in wireplumber.service xdg-desktop-portal.service \
           xdg-desktop-portal-gtk.service xdg-desktop-portal-gnome.service; do
    systemctl --user restart "$svc" 2>/dev/null || true
done

echo "Environment fully reset. You can re-run the installer."
RESET_EOF
chmod +x "$INSTALL_DIR/reset-environment.sh"

ln -sf "$INSTALL_DIR/run.sh" "$BIN_DIR/blucast"
log "Launcher: $BIN_DIR/blucast"

echo -e "${BLUE}[5/5]${NC} Creating desktop entry..."

LOGO_PATH="$INSTALL_DIR/logo.svg"
if command -v curl &>/dev/null; then
    curl -fsSL "https://raw.githubusercontent.com/Andrei9383/BluCast/main/assets/logo.svg" \
        -o "$LOGO_PATH" 2>/dev/null || true
elif command -v wget &>/dev/null; then
    wget -q "https://raw.githubusercontent.com/Andrei9383/BluCast/main/assets/logo.svg" \
        -O "$LOGO_PATH" 2>/dev/null || true
fi
ICON_VALUE="camera-video"
[ -f "$LOGO_PATH" ] && ICON_VALUE="$LOGO_PATH"

DESKTOP_FILE="$HOME/.local/share/applications/blucast.desktop"
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Name=BluCast
Comment=AI-Powered Virtual Camera
Exec=$INSTALL_DIR/run.sh
Icon=$ICON_VALUE
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
echo -e "  Launch: ${BLUE}blucast${NC}"
echo -e "  Or find ${BLUE}BluCast${NC} in your application menu."
echo -e "  Reset:  ${BLUE}$INSTALL_DIR/reset-environment.sh${NC}"
echo ""

if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    warn "~/.local/bin is not in your PATH."
    echo -e "    Add it:  ${BLUE}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc${NC}"
    echo ""
fi
