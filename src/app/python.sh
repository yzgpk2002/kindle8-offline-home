#!/bin/sh
R=/opt/kt3-home/runtime
export PYTHONHOME="$R/usr"
export PYTHONPATH="$R/usr/lib/python3/dist-packages"
export PYTHONDONTWRITEBYTECODE=1
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
exec "$R/lib/ld-linux.so.3" --library-path "$R/lib/arm-linux-gnueabi:$R/usr/lib/arm-linux-gnueabi" "$R/usr/bin/python3.11" "$@"
