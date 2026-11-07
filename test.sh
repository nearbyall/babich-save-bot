#!/bin/sh
# Lint and run the tests inside the bot image, which has ffmpeg and the dependencies
set -e
cd "$(dirname "$0")"
docker run --rm -v "$PWD:/src:ro" -w /src -e PYTHONDONTWRITEBYTECODE=1 --entrypoint sh babichsavebot:local -c \
    "pip install -q --root-user-action=ignore -r requirements-dev.txt \
     && python -m pyflakes bot tests && python -m pytest -q -p no:cacheprovider $*"
