#!/bin/bash
# ClearCastFX Launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="localhost/clearcastfx:latest"

# Detect container runtime
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
else
    CONTAINER_CMD="docker"
fi

# Ensure v4l2loopback is loaded
if ! lsmod | grep -q v4l2loopback 2>/dev/null; then
    sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="ClearCastFX Camera" exclusive_caps=1 2>/dev/null || true
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
    echo "Warning: No camera devices found. The app will start but camera may not work."
fi

echo "Starting ClearCastFX..."

# Shared IPC directory
mkdir -p /tmp/clearcastfx

# Start the vcam consumer watcher
WATCHER_PID=""
if [ -f "$SCRIPT_DIR/scripts/vcam_watcher.sh" ]; then
    "$SCRIPT_DIR/scripts/vcam_watcher.sh" /dev/video10 &
    WATCHER_PID=$!
fi

cleanup() {
    if [ -n "$WATCHER_PID" ] && kill -0 "$WATCHER_PID" 2>/dev/null; then
        kill "$WATCHER_PID" 2>/dev/null
    fi
}
trap cleanup EXIT

# Create config directory for persistent settings
CONFIG_DIR="$HOME/.config/clearcastfx"
mkdir -p "$CONFIG_DIR"

# Configure GPU arguments based on container runtime
if [ "$CONTAINER_CMD" = "podman" ]; then
    GPU_ARGS="--device nvidia.com/gpu=all"
else
    GPU_ARGS="--gpus all"
fi

# Handle Xauthority
XAUTH_ARGS=""
if [ -n "$XAUTHORITY" ] && [ -f "$XAUTHORITY" ]; then
    XAUTH_ARGS="-v $XAUTHORITY:/root/.Xauthority:ro"
elif [ -f "$HOME/.Xauthority" ]; then
    XAUTH_ARGS="-v $HOME/.Xauthority:/root/.Xauthority:ro"
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
    -v "$CONFIG_DIR:/root/.config/clearcastfx:rw" \
    -v "/tmp/clearcastfx:/tmp/clearcastfx:rw" \
    -v "$SCRIPT_DIR/output:/output" \
    --ipc=host \
    --network host \
    "$IMAGE_NAME" 2>&1

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "ClearCastFX exited with code $EXIT_CODE"
    echo ""
    echo "Common issues:"
    echo "  - No camera: Plug in a webcam and try again"
    echo "  - Display error: Run 'xhost +local:' first"
    echo "  - GPU error: Check 'nvidia-smi' works"
fi
