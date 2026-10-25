#!/bin/sh
# Runs as framework. Obtain the existing loopback page's CSRF token; never log it.
set -eu
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
D=/mnt/us/kt3-home/offline-home
mkdir -p "$D"
token=$(curl -fsS --noproxy '*' --connect-timeout 1 --max-time 3 http://127.0.0.1:8083/ | sed -n "s/^var token='\([a-f0-9]*\)'.*/\1/p")
[ "${#token}" = 48 ] || { echo 'Invalid homepage token' >&2; exit 1; }
case "$token" in *[!a-f0-9]*) exit 1;; esac
sed "s/__TOKEN__/$token/g" /opt/kt3-home/app/home-offline.html > "$D/index.html.new"
test -s "$D/index.html.new"
mv "$D/index.html.new" "$D/index.html"
