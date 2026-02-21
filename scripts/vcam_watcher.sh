#!/bin/bash
# BluCast - Virtual camera consumer watcher
# Monitors for applications using the virtual camera device

VCAM_DEVICE="${1:-/dev/video10}"
CMD_PIPE="/tmp/blucast/blucast_cmd"

send_consumers() {
    local count="$1"
    if [[ -p "$CMD_PIPE" ]]; then
        echo "VCAM_CONSUMERS:$count" <> "$CMD_PIPE" 1>&0 2>/dev/null
        return 0
    fi
    return 1
}

last_consumers=-1

while true; do
    consumers=$(lsof "$VCAM_DEVICE" 2>/dev/null | awk 'NR>1 && $4 !~ /w$/ {print $2}' | sort -u | wc -l)
    
    if [[ "$consumers" != "$last_consumers" ]]; then
        if send_consumers "$consumers"; then
            last_consumers="$consumers"
        fi
    fi
    
    sleep 1
done
