# @babichsavebot

[Русский](README.ru.md) | **English**

Telegram bot that downloads TikTok videos and slideshows, Instagram Reels, photos and carousels, and YouTube
Shorts from a link.

- **Inline (any chat)**: type `@babichsavebot link` and pick the video in the popup. It's sent from you,
  marked "via @babichsavebot". If the video is still downloading, «⏳ Скачиваю…» ("downloading…") goes out
  first and turns into the video by itself.
- **Guest mode (any chat)**: send `@babichsavebot link` as a regular message, or reply `@babichsavebot` to a
  message with a link. The bot answers in a separate message of its own.
- **DM**: send a link.
- **Group where the bot is a member**: `/dl link`.
- **Shazam and sound (DM)**: the «🎵 Шазам» (what's the track) and «🎧 Аудио» (the video's sound as a separate
  file) buttons under a video.
- **Round videos (DM)**: the «⚪ Кружок» button under a video turns it into round video messages, a minute each.
- **Video stickers (DM)**: the «🎭 Стикер» button under a video.
- **Your own videos (DM)**: any video, GIF or round video sent or forwarded to the bot. It replies
  «🎬 Что сделать с этим видео?» ("what to do with this video?") with the same buttons.
- **Problem reports (DM)**: `/report what happened`, or `/report` in reply to the message with the problem. The
  owner gets it and can answer.

The bot's buttons and messages are in Russian; `/help` is in both English and Russian.

**Photo posts** (TikTok slideshows, Instagram photos and carousels) arrive in DMs and groups as albums of up to 10
(and at most 48 MB per album, the Bot API request limit); slideshows are followed by their sound. In inline and
guest mode a message holds a single file, so the first photo comes with a «🖼 Весь пост» ("whole post") button. It
opens the DM with the bot (`/start tt_<id>` / `ig_<code>`), and the whole post arrives there.

**Shazam**: the bot listens to the video's sound in 12-second windows, until the first match: the middle, then the
start and the end. It uses Shazam's unofficial API ([shazamio](https://github.com/shazamio/ShazamIO)) and replies
with the cover art, title, album, year and links to Shazam, Apple Music, Spotify and YouTube Music. Shazam answers
about 3 requests a minute from one IP, so requests wait in a queue. The result, "not recognized" included, is
remembered for each video, so a repeated tap answers at once. Videos without sound (Telegram turns them into GIFs)
get no Shazam or audio buttons.

**Audio**: AAC sound is copied into M4A without re-encoding (anything else becomes AAC 192k), and the cover is a
frame of the video. If the track has been recognized, the file is named after it, otherwise «Звук из TikTok»
("sound from TikTok") plus the video's author. Videos sent to the bot get «Звук из видео» ("sound from the
video"): the bot doesn't read their captions.

**Round videos**: the bot crops the video to a square around the center (H.264, up to 640 px, with its sound if it
has any) and sends a minute of it, the most Telegram shows in a round video. A round video of a longer video comes
with buttons for the neighbouring minutes («◀️ 0:00–1:00», «2:00–2:30 ▶️»). Each one sends a new round video,
and the earlier ones stay. If the user's privacy settings close voice messages, Telegram won't take round videos
either, and the bot says so.

**Video stickers**: the bot cuts 3 seconds (WEBM/VP9, 512 px, up to 256 KB, no sound, as Telegram requires) and
sends the sticker with buttons. Each tap sends a new version and deletes the previous one:

- ⏪ ◀️ ▶️ ⏩: move by a third of a sticker or a whole one (1 and 3 s, or 2 and 6 s at ×2);
- 🐢 / 🐇: half or double speed, from ×0.25 (0.75 s of video) to ×8 (24 s of video in the sticker);
- Ориг (original) · 1:1 · 16:9 · 9:16 · ⚪ Круг (circle): the shape. Other ratios are cropped around the center,
  and the circle gets transparent corners. The ratio that matches the source isn't shown, and the current one is
  marked ✓;
- «➕ В мой пак» ("add to my pack"): adds it to the personal pack `u<id>_by_babichsavebot` (120 stickers each,
  then `_2`, `_3`…).

To pick an exact moment, reply to the video with a time: `0:12` or `0:12-0:14`. The bot speeds up a range longer
than 3 seconds so it fits (`0:10-0:20` → ×4). Round videos make round stickers by default. The whole state of a
cut lives in the buttons' callback data; nothing is stored in the database. The bot takes the source from
Telegram, which gives bots files up to 20 MB, and downloads bigger videos again by the link in the caption. The
source is kept for ~15 minutes, so moves, round videos, Shazam and audio don't download it again. Under videos
sent to the bot the buttons sit on the bot's reply and work on the video it replies to.

**Reports**: the owner gets the report with the person's name, @username and a `#u<id>` tag (searching for it
finds all their reports), followed by copies of the message it's about and of the screenshot, if there is one.
The owner's reply to a report goes to the person, as text or with any attachment. A bare `/report` asks what
happened, and the answer to that question becomes the report. One person can send a report every 30 seconds.

Videos are downloaded by [yt-dlp](https://github.com/yt-dlp/yt-dlp) as H.264/MP4 up to 1080p, or in lower quality
when that doesn't fit the Bot API limit (50 MB). Sent file_ids are cached in SQLite, so a repeated link is
delivered instantly. The videos themselves aren't kept on disk: the temp file is deleted right after sending.

## Deploy

```sh
./deploy.sh                      # rebuild and restart (leaves no build cache)
docker compose logs -f           # logs
docker compose restart           # restart (also picks up a fresh yt-dlp)
```

`deploy.sh` builds the image in a temporary BuildKit and then removes it together with its cache and the old
versions of the bot image. Only the current image (~0.7 GB) stays on disk. `docker compose up --build` works too,
but leaves build cache behind.

The container comes back by itself after crashes and reboots. On start it updates yt-dlp, and every 6 hours it
checks PyPI and restarts when a new version is out.

## @BotFather settings

- **Inline mode**: `/setinline` → bot → a placeholder such as `ссылка на TikTok / Reels / Shorts`.
- **Inline feedback**: `/setinlinefeedback` → bot → Enabled. Without it «⏳ Скачиваю…» turns into the video only
  when someone taps «🔄 Обновить» ("refresh").
- **Guest mode**: Mini App → bot → Bot Settings → Guest Mode.
- The description and "about" text are set only there (`/setdescription`, `/setabouttext`); the bot doesn't
  touch them.

## Server protection

| What | How |
|---|---|
| Memory | container limit `BOT_MEM_LIMIT` (768m), no swap. Hitting it kills and restarts only the bot, and when the host runs out of memory, the kernel kills the bot first (`oom_score_adj`) |
| CPU | limit `BOT_CPUS` (1.0), half weight under contention, `nice 10` and low disk priority |
| Concurrency | 2 downloads at once by default, YouTube one at a time (deno takes ~250 MB), for a memory peak of ~500 MB. On the 2 CPU / 8 GB server: 3 downloads, YouTube two at a time, a peak of ~900 MB. Stickers and round videos: 2 at once, in one queue; a sticker takes ~2 s of one core, a minute of round video from 1080p ~20 s and ~140 MB |
| Queue | at most 12 requests in progress and 3 per person; anyone over the limit is told to try later |
| Time | a download is cut off after 3 minutes; videos longer than 10 minutes are turned away before downloading |
| Disk | below 1 GB free, downloads pause, temp files are cleaned up and the owner gets a notification |
| Cleanup | every 10 minutes the bot removes abandoned temp files, cache entries older than 30 days (20,000 at most) and yt-dlp cache older than 7 days |
| Logs | rotated, 3 × 10 MB |

## `.env` variables

| Variable | Default | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | bot token (required) |
| `BOT_MEM_LIMIT` | `768m` | container memory limit |
| `BOT_CPUS` | `1.0` | container CPU limit |
| `MAX_PARALLEL_DOWNLOADS` | `2` | downloads at once |
| `MAX_PARALLEL_YOUTUBE` | `1` | how many of them may be from YouTube (~360 MB each) |
| `MAX_PARALLEL_RENDERS` | `2` | sticker and round video renders at once |
| `MAX_QUEUE` / `MAX_JOBS_PER_USER` | `12` / `3` | queue size in total / per person |
| `MAX_DURATION_SEC` | `600` | longest video allowed |
| `DOWNLOAD_TIMEOUT_SEC` | `180` | when a hung download is cut off |
| `MIN_FREE_DISK_MB` | `1024` | below this, downloads pause |
| `CACHE_TTL_DAYS` | `30` | how long file_ids are kept |
| `STORAGE_CHAT_ID` | — | channel (with the bot as admin) where videos for inline and guest mode are uploaded. Without it they go to the DM of whoever asked, or of the owner, and the message is deleted right away |
| `OWNER_ID` | the first person to message the bot | who gets notifications and reports, and where uploads go as a last resort |

After editing `.env`: `docker compose up -d`.

If Instagram starts asking for a login, put cookies in Netscape format into `data/cookies.txt`.

## Moving to another server

Copy the project folder together with `.env` and `data/`. Run `docker compose down` on the old server, since two
instances with the same token don't work, then `./deploy.sh` on the new one.

## Structure

Layers depend only inwards: `media` knows nothing about Telegram, and `telegram` puts everything together.

```
bot/
  __main__.py          startup: bot, routers, background tasks
  config.py            settings from .env
  links.py             parsing and normalizing links, deep link payloads
  db.py                file_id cache (SQLite) and the owner
  errors.py            UserError, an error with a message for the user
  jobs.py              requests in progress (a restart waits for them), guard against repeated taps
  housekeeping.py      temp and cache cleanup, disk watch, yt-dlp updates
  media/               downloading and processing, no Telegram
    downloader.py      download(link) → Video | Album, queue and limits
    ytdlp.py           yt-dlp options, errors, videos and photos
    posts.py           Instagram photo posts, TikTok slideshows
    sticker.py         sticker cut (Cut, shape, speed) and rendering to WEBM
    rounds.py          round video: a minute of video as an H.264 square
    shazam.py          track recognition: windows, Shazam's rate limit
    audio.py           a video's sound: the M4A file and PCM for Shazam
    ffmpeg.py          probing (size, duration, sound), thumbnails, photo conversion
    workspace.py       temp dirs and disk space
    models.py          Video, Album, MediaItem
  telegram/            everything about Telegram
    delivery.py        uploading and resending by file_id, shared cache for inline
    clips.py           a video from the chat as a file: from Telegram or by its link again, one dir for all jobs
    stickers.py        a sticker from a video in the chat, personal packs
    sounds.py          Shazam and audio from a video in the chat
    rounds.py          a round video from a video in the chat
    reports.py         problem reports to the owner and the owner's answers
    keyboards.py       buttons and their callback data
    texts.py           /help and shared texts
    messages.py        reading incoming messages
    handlers/          routers: reports → stickers → sounds → rounds → chats → inline → fallback
tests/                 unit tests (pytest)
```

## Tests and git

```sh
./test.sh                        # pyflakes + pytest inside the bot image (it has ffmpeg)
```

History is kept in git, one commit per change. A new feature also goes into `/help` (`bot/telegram/texts.py`),
and `tests/test_texts.py` checks that every feature is mentioned there.
