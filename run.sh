#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VCAM_DEVICE="/dev/video10"
SHARED_DIR="/tmp/blucast"
GHCR_IMAGE="ghcr.io/andrei9383/blucast:latest"
LOCAL_IMAGE="localhost/blucast:latest"

if command -v podman &>/dev/null; then
    CONTAINER_CMD="podman"
elif command -v docker &>/dev/null; then
    CONTAINER_CMD="docker"
else
    echo "Error: podman or docker required"
    exit 1
fi

if $CONTAINER_CMD image exists "$LOCAL_IMAGE" 2>/dev/null || \
   $CONTAINER_CMD inspect "$LOCAL_IMAGE" &>/dev/null 2>&1; then
    IMAGE_NAME="$LOCAL_IMAGE"
else
    IMAGE_NAME="$GHCR_IMAGE"
    if ! $CONTAINER_CMD inspect "$IMAGE_NAME" &>/dev/null 2>&1; then
        echo "Pulling BluCast image..."
        $CONTAINER_CMD pull "$IMAGE_NAME"
    fi
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
        echo "Run: sudo modprobe v4l2loopback devices=1 video_nr=10 card_label='BluCast Virtual Camera' exclusive_caps=1"
        exit 1
    fi
fi

if [ ! -e "$VCAM_DEVICE" ]; then
    echo "Error: Virtual camera $VCAM_DEVICE not found"
    exit 1
fi

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
if [ -x "$SCRIPT_DIR/scripts/vcam_watcher.sh" ]; then
    "$SCRIPT_DIR/scripts/vcam_watcher.sh" "$VCAM_DEVICE" &
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
    "$IMAGE_NAME" 2>&1
