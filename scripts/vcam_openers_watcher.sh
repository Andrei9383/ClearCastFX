#!/usr/bin/env bash
set -u

VCAM_DEV="${1:-/dev/video10}"
VCAM_NAME="$(basename "$VCAM_DEV")"
FIFO="/tmp/videofx/videofx_cmd"

find_openers_path() {
  local name="$1"
  local candidates=(
    "/sys/devices/virtual/video4linux/${name}/openers"
    "/sys/class/video4linux/${name}/device/openers"
    "/sys/class/video4linux/${name}/openers"
  )
  local p
  for p in "${candidates[@]}"; do
    if [[ -r "$p" ]]; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

OPENERS_PATH=""
OPENERS_MODE=""
if OPENERS_PATH="$(find_openers_path "$VCAM_NAME")"; then
  OPENERS_MODE="sysfs"
  echo "vcam_openers_watcher: using sysfs ${OPENERS_PATH}" >&2
else
  # Many systems/container setups don't expose v4l2loopback's sysfs 'openers'.
  # Fall back to counting processes using the device.
  # Prefer lsof since it can distinguish writer-only fds (the server) from readers.
  if command -v lsof >/dev/null 2>&1; then
    OPENERS_MODE="lsof"
    echo "vcam_openers_watcher: sysfs openers missing; using lsof on ${VCAM_DEV}" >&2
  elif command -v fuser >/dev/null 2>&1; then
    OPENERS_MODE="fuser"
    echo "vcam_openers_watcher: sysfs openers missing; using fuser on ${VCAM_DEV}" >&2
  else
    echo "vcam_openers_watcher: no sysfs openers and neither fuser nor lsof is available" >&2
    exit 1
  fi
fi

get_consumers() {
  case "$OPENERS_MODE" in
    sysfs)
      # sysfs reports total openers (readers + writer). Server keeps the writer open,
      # so treat consumers as max(openers - 1, 0).
      openers="$(cat "$OPENERS_PATH" 2>/dev/null || echo 0)"
      if ! [[ "$openers" =~ ^[0-9]+$ ]]; then
        openers="0"
      fi
      consumers=$((openers - 1))
      if (( consumers < 0 )); then consumers=0; fi
      echo "$consumers"
      ;;
    fuser)
      # Count unique PIDs opening the device. fuser exits nonzero if none.
      openers="$(fuser -a "$VCAM_DEV" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u | wc -l)"
      if ! [[ "$openers" =~ ^[0-9]+$ ]]; then
        openers="0"
      fi
      consumers=$((openers - 1))
      if (( consumers < 0 )); then consumers=0; fi
      echo "$consumers"
      ;;
    lsof)
      # Count unique PIDs that are NOT writer-only (FD ending with 'w').
      # Readers often appear as 'r' or 'u' (read/write).
      lsof -nP "$VCAM_DEV" 2>/dev/null |
        awk 'NR>1 {print $2, $4}' |
        awk '$2 ~ /w$/ {next} {print $1}' |
        sort -u |
        wc -l
      ;;
    *)
      echo 0
      ;;
  esac
}

last_consumers=""

while true; do
  if [[ -p "$FIFO" ]]; then
    consumers="$(get_consumers)"
    if ! [[ "$consumers" =~ ^[0-9]+$ ]]; then
      consumers="0"
    fi

    if [[ "$consumers" != "$last_consumers" ]]; then
      timeout 0.2s bash -c "printf 'VCAM_CONSUMERS:%s\\n' '$consumers' > '$FIFO'" 2>/dev/null || true
      last_consumers="$consumers"
    fi
  fi

  sleep 0.25
done
