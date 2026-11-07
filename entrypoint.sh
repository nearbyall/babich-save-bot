#!/bin/sh
# Sites change often: pull the freshest yt-dlp on every (re)start.
pip install --no-cache-dir --root-user-action=ignore -q -U "yt-dlp[default,curl-cffi]" \
    || echo "yt-dlp update failed, using the bundled version"

# Drop root and run as the host user so files in ./data stay editable
PUID=${PUID:-1000}
PGID=${PGID:-1000}
mkdir -p /app/data /tmp/babichsavebot /tmp/home
chown -R "$PUID:$PGID" /app/data /tmp/babichsavebot /tmp/home
export HOME=/tmp/home
# Lowest CPU and disk priority: other services on the host always come first
exec nice -n 10 ionice -c 2 -n 7 -t setpriv --reuid="$PUID" --regid="$PGID" --clear-groups python -m bot
