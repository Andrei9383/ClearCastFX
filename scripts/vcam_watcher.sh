#!/bin/bash
# BluCast - Virtual camera consumer watcher
# Monitors for applications using the virtual camera device

VCAM_DEVICE="${1:-/dev/video10}"
CMD_PIPE="/tmp/blucast/blucast_cmd"

send_consumers() {
    local count="$1"
    if [[ -p "$CMD_PIPE" ]]; then
        echo "VCAM_CONSUMERS:$count" > "$CMD_PIPE" 2>/dev/null
    fi
}

last_consumers=-1

while true; do
    openers=$(lsof "$VCAM_DEVICE" 2>/dev/null | grep -v "^COMMAND" | wc -l)
    consumers=$((openers > 1 ? openers - 1 : 0))
    
    if [[ "$consumers" != "$last_consumers" ]]; then
        send_consumers "$consumers"
        last_consumers="$consumers"
    fi
    
    sleep 1
done
