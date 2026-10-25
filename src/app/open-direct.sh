#!/bin/sh
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
exec >>/mnt/us/kt3-home/logs/kual-direct.log 2>&1
date
id
# mkdir serializes repeated taps; the exit trap removes only our empty lock.
LOCK=/tmp/kt3-direct-entry.lock
mkdir "$LOCK" 2>/dev/null || exit 0
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
if sh /opt/kt3-home/app/open-manual.sh; then
 echo 'DIRECT_HOME_OK'
else
 echo 'DIRECT_HOME_FAILED: restoring original menu'
 touch /mnt/us/kt3-home/USE_KUAL_MENU
 lipc-set-prop com.lab126.appmgrd stop app://com.mobileread.ixtab.kindlelauncher || true
 sleep 1
 lipc-set-prop com.lab126.appmgrd start app://com.mobileread.ixtab.kindlelauncher || true
 exit 1
fi
