#!/bin/sh
# Rebuild and restart the bot without leaving anything behind: disk space on
# this VPS is tight. The image is built by a throwaway BuildKit instance, so
# removing it afterwards wipes exactly this project's build cache and leaves
# other projects' cache alone.
set -e
cd "$(dirname "$0")"

BUILDER=babichsavebot-builder
cleanup() {
    docker buildx rm "$BUILDER" >/dev/null 2>&1 || true
    # Fails harmlessly if some other builder still uses the image
    docker image rm moby/buildkit:buildx-stable-1 >/dev/null 2>&1 || true
}
cleanup
trap cleanup EXIT
docker buildx create --name "$BUILDER" --driver docker-container >/dev/null

docker buildx build --builder "$BUILDER" --load -t babichsavebot:local .
docker compose up -d
# Previous versions of this image only (matched by label)
docker image prune -f --filter label=org.opencontainers.image.title=babichsavebot >/dev/null

docker compose ps
df -h / | tail -1
