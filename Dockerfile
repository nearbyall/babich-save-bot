FROM mwader/static-ffmpeg:7.1 AS ffmpeg
FROM denoland/deno:bin-2.5.6 AS deno

FROM python:3.12-slim

LABEL org.opencontainers.image.title=babichsavebot

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_ARENA_MAX=2

# Only ffmpeg (merging, probing, thumbnails); ffprobe would add another 135 MB
COPY --from=ffmpeg /ffmpeg /usr/local/bin/
# yt-dlp needs a JS runtime (deno) to solve YouTube challenges
COPY --from=deno /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY entrypoint.sh .

ENTRYPOINT ["sh", "/app/entrypoint.sh"]
