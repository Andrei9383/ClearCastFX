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
# Note: Podman uses CDI (--device nvidia.com/gpu=all), Docker uses --gpus all
if [ "$CONTAINER_CMD" = "podman" ]; then
    GPU_ARGS="--device nvidia.com/gpu=all"
else
    GPU_ARGS="--gpus all"
fi

# Handle Xauthority - may be in different locations or not exist (Wayland)
XAUTH_ARGS=""
if [ -n "$XAUTHORITY" ] && [ -f "$XAUTHORITY" ]; then
    XAUTH_ARGS="-v $XAUTHORITY:/root/.Xauthority:ro"
elif [ -f "$HOME/.Xauthority" ]; then
    XAUTH_ARGS="-v $HOME/.Xauthority:/root/.Xauthority:ro"
fi

$CONTAINER_CMD run --rm -it \
    --security-opt label=disable \
    $GPU_ARGS \
    $CAMERA_ARGS \
    -e DISPLAY=$DISPLAY \
    -e QT_X11_NO_MITSHM=1 \
    -e NVIDIA_DRIVER_CAPABILITIES=all \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -e HOME=/host_home \
    -e XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-}" \
    -e QT_QPA_PLATFORMTHEME="${QT_QPA_PLATFORMTHEME:-gtk2}" \
    -e GTK_THEME="${GTK_THEME:-}" \
    -e KDE_FULL_SESSION="${KDE_FULL_SESSION:-}" \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    $XAUTH_ARGS \
    -v "$HOME:/host_home:ro" \
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
