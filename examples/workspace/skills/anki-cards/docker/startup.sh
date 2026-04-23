#!/bin/bash
# Start Xvfb / openbox / x11vnc / Anki, each with its own restart loop.

# Clean stale X lock files from previous unclean exits
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

start_watchdog() {
    local name=$1
    shift
    (
        while true; do
            echo "[watchdog] starting $name"
            "$@"
            echo "[watchdog] $name exited (code $?), cleaning + restarting in 2s"
            if [ "$name" = "xvfb" ]; then
                rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
            fi
            sleep 2
        done
    ) &
}

start_watchdog xvfb Xvfb :99 -screen 0 1920x1080x24
# wait until X is actually accepting connections
for i in 1 2 3 4 5 6 7 8 9 10; do
    if [ -S /tmp/.X11-unix/X99 ]; then break; fi
    sleep 0.5
done

export DISPLAY=:99

start_watchdog openbox openbox
sleep 1

start_watchdog x11vnc x11vnc -display :99 -forever -shared -nopw -rfbport 5900
sleep 1

# Anki in the foreground
while true; do
    anki -p "User 1" -b /data
    echo "[watchdog] anki exited, restarting in 2s"
    sleep 2
done
