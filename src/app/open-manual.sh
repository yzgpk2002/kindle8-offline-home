#!/bin/sh
set -eu
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
test "$(lipc-get-prop com.lab126.kaf frameworkStarted)" = 1
ready() {
 test "$(/usr/bin/curl -fsS --noproxy '*' --connect-timeout 1 --max-time 1 http://127.0.0.1:8083/probe.txt 2>/dev/null)" = KT3_OK
}
# Most library-to-home visits reuse the live service. Do not start a Python
# interpreter or add a fixed delay just to probe a ready loopback endpoint.
if ! ready; then
 /opt/kt3-home/manual-control status | grep -q 'start/running' || /opt/kt3-home/manual-control start
 attempts=0
 until ready; do
  attempts=$((attempts+1))
  if [ "$attempts" -ge 40 ]; then
   echo 'Local homepage readiness timed out' >&2
   exit 1
  fi
  /bin/busybox usleep 250000
 done
fi
sh /opt/kt3-home/app/prepare-offline-page.sh
lipc-set-prop com.lab126.appmgrd start 'app://com.kt3.home'
