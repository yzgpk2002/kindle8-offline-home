#!/bin/sh
set -eu
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
D=/mnt/us/kt3-home
mkdir -p "$D/logs" "$D/recordings"
rm -f "$D/exit-request"
grep -q ' /opt/kt3-home/runtime squashfs ' /proc/mounts || mount -t squashfs -o loop,ro /opt/kt3-home/runtime.squashfs /opt/kt3-home/runtime
sh /opt/kt3-home/app/python.sh /opt/kt3-home/app/audio_lifecycle.py startup
exec sh /opt/kt3-home/app/python.sh -u /opt/kt3-home/app/server.py >>"$D/logs/server.log" 2>&1
