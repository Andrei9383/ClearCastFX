#!/bin/bash

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
    local pids
    pids=$(fuser "$VCAM_DEVICE" 2>/dev/null) || true
    local total
    total=$(echo "$pids" | wc -w)
    local n=$((total - 1))
    [ $n -lt 0 ] && n=0
    echo "$n"
}

if command -v lsof &>/dev/null; then
    COUNT_FN="count_with_lsof"
elif command -v fuser &>/dev/null; then
    COUNT_FN="count_with_fuser"
else
    echo "Warning: neither lsof nor fuser available. Consumer detection disabled." >&2
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
