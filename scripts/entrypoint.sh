#!/bin/sh
set -eu
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data
  chown sal0:sal0 /data
  exec gosu sal0 "$@"
fi
exec "$@"

