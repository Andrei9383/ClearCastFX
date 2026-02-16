#!/bin/bash
# BluCast Launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GHCR_IMAGE="ghcr.io/andrei9383/blucast:latest"
LOCAL_IMAGE="localhost/blucast:latest"

# Detect container runtime
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
else
    CONTAINER_CMD="docker"
fi

# Determine which image to use: local build or GHCR
if $CONTAINER_CMD image exists "$LOCAL_IMAGE" 2>/dev/null || \
   $CONTAINER_CMD inspect "$LOCAL_IMAGE" &>/dev/null; then
    IMAGE_NAME="$LOCAL_IMAGE"
    echo "Using locally built image"
else
    IMAGE_NAME="$GHCR_IMAGE"
    # Pull if not present or if --pull flag is passed
    if [[ "$1" == "--pull" ]] || ! $CONTAINER_CMD inspect "$IMAGE_NAME" &>/dev/null; then
        echo "Pulling BluCast from GitHub Container Registry..."
        $CONTAINER_CMD pull "$IMAGE_NAME"
    fi
fi

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

# Ensure v4l2loopback is loaded with proper settings
if [ ! -e /dev/video10 ]; then
    if lsmod | grep -q v4l2loopback 2>/dev/null; then
        echo "Reloading v4l2loopback with correct device number..."
        sudo modprobe -r v4l2loopback 2>/dev/null || true
        sleep 1
    fi
    sudo modprobe v4l2loopback \
        devices=1 \
        video_nr=10 \
        card_label="BluCast Camera" \
        exclusive_caps=1 \
        max_buffers=2 \
        max_openers=10 \
        2>/dev/null || true
    sleep 1
fi

# Ensure the virtual camera device is accessible
if [ -e /dev/video10 ]; then
    sudo chmod 666 /dev/video10 2>/dev/null || true
    echo "Virtual camera ready at /dev/video10"
else
    echo "Warning: Virtual camera device /dev/video10 not found"
    echo "  Install v4l2loopback: sudo dnf install v4l2loopback (Fedora) or sudo apt install v4l2loopback-dkms (Ubuntu)"
fi

# Persist v4l2loopback options so the module loads correctly across reboots.
MODPROBE_CONF="/etc/modprobe.d/v4l2loopback.conf"
MODPROBE_LINE='options v4l2loopback devices=1 video_nr=10 card_label="BluCast Camera" exclusive_caps=1 max_buffers=2 max_openers=10'
if [ ! -f "$MODPROBE_CONF" ] || ! grep -q 'video_nr=10' "$MODPROBE_CONF" 2>/dev/null; then
    echo "$MODPROBE_LINE" | sudo tee "$MODPROBE_CONF" >/dev/null 2>&1 || true
fi

UDEV_RULE_FILE="/etc/udev/rules.d/83-blucast-vcam.rules"
UDEV_RULE='SUBSYSTEM=="video4linux", KERNEL=="video10", ENV{ID_V4L_PRODUCT}="BluCast Camera", ENV{ID_V4L_CAPABILITIES}=":capture:"'
if [ -e /dev/video10 ]; then
    # Install udev rule if not present
    if [ ! -f "$UDEV_RULE_FILE" ] || ! grep -q "KERNEL==\"video10\"" "$UDEV_RULE_FILE" 2>/dev/null; then
        echo "$UDEV_RULE" | sudo tee "$UDEV_RULE_FILE" >/dev/null 2>&1 || true
        sudo udevadm control --reload-rules 2>/dev/null || true
    fi
    sudo udevadm trigger --action=change /dev/video10 2>/dev/null || true
    sleep 1

    refresh_camera_portal
fi

register_pipewire_camera() {
    local dev="/dev/video10"
    local timeout=60
    local waited=0
    # Wait until a process has the device open for writing
    while [ $waited -lt $timeout ]; do
        if [ -e "$dev" ] && sudo lsof "$dev" 2>/dev/null | awk 'NR>1' | grep -q 'w$'; then
            sleep 2
            sudo udevadm trigger --action=change "$dev" 2>/dev/null || true
            sleep 1
            systemctl --user restart wireplumber 2>/dev/null || true
            sleep 3
            for svc in xdg-desktop-portal.service xdg-desktop-portal-gtk.service xdg-desktop-portal-gnome.service; do
                systemctl --user restart "$svc" 2>/dev/null || true
            done
            if wpctl status 2>/dev/null | grep -qi 'BluCast.*Source\|BluCast.*(V4L2)'; then
                echo "Virtual camera registered with PipeWire (Firefox should see it)"
            else
                echo "Warning: Virtual camera may not be visible to PipeWire apps"
                echo "  Try manually: systemctl --user restart wireplumber xdg-desktop-portal"
            fi
            return
        fi
        sleep 1
        waited=$((waited + 1))
    done
    echo "Warning: Timed out waiting for server to open virtual camera"
}

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
    echo "Warning: No camera devices found. The app will start but camera may not work."
fi

echo "Starting BluCast..."

# Shared IPC directory
mkdir -p /tmp/blucast

# Start the vcam consumer watcher
WATCHER_PID=""
if [ -f "$SCRIPT_DIR/scripts/vcam_watcher.sh" ]; then
    "$SCRIPT_DIR/scripts/vcam_watcher.sh" /dev/video10 &
    WATCHER_PID=$!
fi

# Start PipeWire camera registration in background
PW_REFRESH_PID=""
register_pipewire_camera &
PW_REFRESH_PID=$!

cleanup() {
    if [ -n "$WATCHER_PID" ] && kill -0 "$WATCHER_PID" 2>/dev/null; then
        kill "$WATCHER_PID" 2>/dev/null
    fi
    if [ -n "$PW_REFRESH_PID" ] && kill -0 "$PW_REFRESH_PID" 2>/dev/null; then
        kill "$PW_REFRESH_PID" 2>/dev/null
    fi
}
trap cleanup EXIT

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
    -v "$SCRIPT_DIR/output:/output" \
    -v "/dev/dri:/dev/dri" \
    --ipc=host \
    --network host \
    "$IMAGE_NAME" 2>&1

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
