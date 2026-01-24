#!/bin/bash
# Watch for virtual camera consumers using lsof polling
# Low CPU usage with 1 second intervals

VCAM_DEVICE="${1:-/dev/video10}"
CMD_PIPE="/tmp/videofx/videofx_cmd"

send_consumers() {
    local count="$1"
    if [[ -p "$CMD_PIPE" ]]; then
        echo "VCAM_CONSUMERS:$count" > "$CMD_PIPE" 2>/dev/null
    fi
}

echo "Watching $VCAM_DEVICE for consumers using lsof"

last_consumers=-1

while true; do
    # Count processes with the device open
    # lsof output: one line header + one line per opener
    openers=$(lsof "$VCAM_DEVICE" 2>/dev/null | grep -v "^COMMAND" | wc -l)
    
    # Subtract 1 for videofx_server's writer fd
    consumers=$((openers > 1 ? openers - 1 : 0))
    
    if [[ "$consumers" != "$last_consumers" ]]; then
        echo "$(date +%H:%M:%S) Openers: $openers -> consumers: $consumers"
        send_consumers "$consumers"
        last_consumers="$consumers"
    fi
    
    sleep 1
done
