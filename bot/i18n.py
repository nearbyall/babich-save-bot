"""The bot's texts in Russian, the default, and English, which a user picks with /lang.

The language of whoever the bot is answering sits in a context variable set for each update, so t() anywhere
below the handlers speaks it, background tasks started from there included. Both versions of a text take the
same {placeholders}."""
from contextvars import ContextVar
from typing import Literal

Lang = Literal["ru", "en"]
LANGS: tuple[Lang, ...] = ("ru", "en")
DEFAULT: Lang = "ru"
NAMES = {"ru": "🇷🇺 Русский", "en": "🇬🇧 English"}

current: ContextVar[Lang] = ContextVar("lang", default=DEFAULT)


def t(key: str, lang: Lang | None = None, **params: object) -> str:
    """The text in `lang`, or else in the language of whoever the bot is answering."""
    ru, en = TEXTS[key]
    text = en if (lang or current.get()) == "en" else ru
    return text.format(**params) if params else text


def variants(key: str) -> tuple[str, ...]:
    """The text in every language, for recognizing it in a message."""
    return TEXTS[key]


HELP_RU = (
    "<b>Видео и фото из TikTok, Instagram и YouTube Shorts</b>\n"
    "📥 Пришли ссылку — пришлю видео, фото-пост, карусель или слайдшоу со звуком.\n"
    "💬 Любой чат: набери <code>@{username} ссылка</code> и нажми на результат или просто отправь. "
    "У фото-постов — первое фото и кнопка «Весь пост».\n"
    "👥 Группы, где я есть: <code>/dl ссылка</code> или ответь <code>/dl</code> на сообщение со ссылкой.\n"
    "🎬 Под видео в личке: «🎵 Шазам» — узнать, что за трек, «🎧 Аудио» — звук отдельным файлом, "
    "«⚪ Кружок» — видеосообщение, по минуте. Пришли или перешли мне любое видео, GIF или кружок — "
    "под ним будут те же кнопки.\n"
    "🎭 Видеостикеры: «🎭 Стикер» под видео. Кнопки под стикером двигают его, меняют скорость (×0.25–×8) "
    "и форму (1:1, 16:9, 9:16, круг) и добавляют в твой стикерпак. Ответь на видео <code>0:12</code> "
    "или <code>0:12-0:20</code> — вырежу с этого места.\n"
    "📮 Нашёл ошибку или есть идея? <code>/report текст</code> — что сломалось или что добавить. Про "
    "конкретное сообщение — ответь на него <code>/report</code>. Разработчик получит и сможет ответить здесь.\n"
    "🌐 English — /lang"
)
HELP_EN = (
    "<b>Videos and photos from TikTok, Instagram and YouTube Shorts</b>\n"
    "📥 Send me a link — I'll send back the video, photo post, carousel or slideshow with its sound.\n"
    "💬 Any chat: type <code>@{username} link</code> and tap the result, or just send it. "
    "Photo posts show the first photo and a «Whole post» button.\n"
    "👥 Groups I'm in: <code>/dl link</code>, or reply <code>/dl</code> to a message with a link.\n"
    "🎬 Under a video in our chat: «🎵 Shazam» finds out what track is playing, «🎧 Audio» sends its sound "
    "as an audio file, «⚪ Round video» makes a round video message of it, a minute at a time. Send or forward "
    "me any video, GIF or round video to get these buttons under it too.\n"
    "🎭 Video stickers: tap «🎭 Sticker» under a video. Buttons under the sticker move it, change the speed "
    "(×0.25–×8) and the shape (1:1, 16:9, 9:16, circle), and add it to your own sticker pack. "
    "Reply to the video with <code>0:12</code> or <code>0:12-0:20</code> to cut from that moment.\n"
    "📮 Found a bug or have an idea? <code>/report your text</code>: what's broken or what you'd like added. "
    "About a particular message, reply <code>/report</code> to it. The developer gets it and can answer you here.\n"
    "🌐 Русский — /lang"
)

# key: (Russian, English)
TEXTS: dict[str, tuple[str, str]] = {
    "help": (HELP_RU, HELP_EN),

    # Bot menu
    "cmd_start": ("Как пользоваться", "How to use"),
    "cmd_report": ("Ошибка или предложение", "Report a bug or suggest an idea"),
    "cmd_lang": ("Язык · Language", "Language · Язык"),
    "cmd_dl": ("Скачать видео по ссылке", "Download a video by link"),

    # /lang
    "lang_choose": ("🌐 Выбери язык · Choose your language", "🌐 Choose your language · Выбери язык"),
    "lang_set": ("✅ Теперь говорю по-русски. Что я умею — /help", "✅ I speak English now. What I can do: /help"),

    # Links and downloads
    "no_links": ("Пришли ссылку на TikTok, Instagram или YouTube Shorts.",
                 "Send me a TikTok, Instagram or YouTube Shorts link."),
    "loading": ("⏳ Скачиваю из {platform}…", "⏳ Downloading from {platform}…"),
    "download_failed": ("Не удалось скачать видео. Попробуй ещё раз чуть позже.",
                        "Couldn't download the video. Try again a bit later."),
    "download_too_slow": ("Видео качается слишком долго, попробуй позже.",
                          "The video takes too long to download, try later."),
    "post_too_slow": ("Пост качается слишком долго, попробуй позже.",
                      "The post takes too long to download, try later."),
    "post_empty": ("Не получилось скачать ни одного фото или видео из поста.",
                   "Couldn't download a single photo or video from the post."),
    "no_video_in_post": ("В этом посте нет видео.", "There's no video in this post."),
    "too_long": ("Видео длиннее {minutes} мин — такие не качаю.",
                 "The video is longer than {minutes} min, I don't download those."),
    "too_big": ("Видео больше 50 МБ — Telegram не даст боту его отправить.",
                "The video is over 50 MB, Telegram won't let a bot send it."),
    "geo_blocked": ("Платформа не отдаёт это видео в регион сервера.",
                    "The platform doesn't serve this video to the server's region."),
    "youtube_blocked": ("YouTube временно ограничил доступ серверу. Попробуй позже.",
                        "YouTube has limited the server's access for now. Try later."),
    "login_required": ("Видео недоступно без входа в аккаунт (приватное или с ограничениями).",
                       "The video can't be watched without logging in (it's private or restricted)."),
    "unsupported_link": ("Не удалось распознать ссылку как видео.", "Couldn't recognize the link as a video."),
    "video_unavailable": ("Видео удалено или недоступно.", "The video has been deleted or is unavailable."),
    "too_many_requests": ("Сейчас слишком много запросов, попробуй через минуту.",
                          "Too many requests right now, try in a minute."),
    "wait_previous": ("Подожди, пока скачаются предыдущие видео.", "Wait until your previous videos are downloaded."),
    "disk_full": ("На сервере заканчивается место, загрузки временно приостановлены.",
                  "The server is running out of space, downloads are paused for now."),
    "file_rejected": ("Telegram не принял файл. Попробуй ещё раз.", "Telegram didn't take the file. Try again."),
    "open_dm_first": ("Сначала открой @{username} в личке и нажми «Старт», потом повтори.",
                      "First open @{username} in a private chat and tap Start, then try again."),

    # Inline and guest mode
    "inline_hint": ("Вставь ссылку на TikTok, Reels или Shorts", "Paste a TikTok, Reels or Shorts link"),
    "send": ("📥 Отправить", "📥 Send"),
    "send_video": ("📥 Отправить видео", "📥 Send video"),
    "still_downloading": ("Ещё скачивается — сообщение обновится само",
                          "Still downloading, the message will update by itself"),
    "inline_failed": ("Не получилось вставить файл в сообщение. Попробуй ещё раз.",
                      "Couldn't put the file into the message. Try again."),
    "link_expired": ("Ссылка устарела — отправь её заново.", "The link has expired, send it again."),
    "loading_now": ("Загружаю…", "Loading…"),
    "refresh": ("🔄 Обновить", "🔄 Refresh"),
    "whole_post": ("🖼 Весь пост: {summary}", "🖼 Whole post: {summary}"),
    "photo": ("{n} фото", "{n} photo"),
    "photos": ("{n} фото", "{n} photos"),
    "video": ("{n} видео", "{n} video"),
    "videos": ("{n} видео", "{n} videos"),
    "and": (" и ", " and "),
    "with_sound": (" + звук", " + sound"),

    # Buttons under videos
    "video_actions": ("🎬 Что сделать с этим видео?", "🎬 What should I do with this video?"),
    "btn_shazam": ("🎵 Шазам", "🎵 Shazam"),
    "btn_audio": ("🎧 Аудио", "🎧 Audio"),
    "btn_sticker": ("🎭 Стикер", "🎭 Sticker"),
    "btn_round": ("⚪ Кружок", "⚪ Round video"),
    "video_gone": ("Видео не найдено — пришли его заново.", "Video not found, send it again."),
    "video_deleted": ("Видео удалено — пришли его заново.", "The video has been deleted, send it again."),
    "video_missing": ("Не вижу видео — пришли его заново.", "I can't see the video, send it again."),
    "message_expired": ("Сообщение устарело — пришли видео заново.", "This message has expired, send the video again."),
    "button_expired": ("Кнопка устарела — пришли ссылку или видео заново.",
                       "This button has expired, send the link or the video again."),
    "too_big_to_fetch": ("Видео больше 20 МБ — такие бот не может забрать из Telegram. "
                         "Пришли ссылку на него или файл поменьше.",
                         "The video is over 20 MB, bots can't get files that big from Telegram. "
                         "Send a link to it or a smaller file."),
    "video_only": ("В видео всего {duration}.", "The video is only {duration} long."),
    "no_frames_here": ("На этом месте в видео уже нет кадров.", "There are no frames at this point of the video."),

    # Shazam and audio
    "listening": ("🎵 Слушаю…", "🎵 Listening…"),
    "extracting": ("🎧 Достаю звук…", "🎧 Getting the sound…"),
    "sounds_busy": ("Секунду, ещё занят прошлым видео…", "A moment, still busy with the previous video…"),
    "no_track": ("🤷 Не узнал трек — похоже, это оригинальный звук или речь.",
                 "🤷 Couldn't recognize the track. It's probably original sound or speech."),
    "track_failed": ("Не получилось распознать трек.", "Couldn't recognize the track."),
    "shazam_busy": ("Shazam сейчас перегружен — попробуй через минуту.", "Shazam is overloaded, try in a minute."),
    "shazam_down": ("Shazam не отвечает — попробуй позже.", "Shazam isn't answering, try later."),
    "sound_failed": ("Не получилось достать звук.", "Couldn't get the sound."),
    "no_sound": ("В этом видео нет звука.", "This video has no sound."),
    "sound_from": ("Звук из {source}", "Sound from {source}"),
    "sound_from_video": ("Звук из видео", "Sound from a video"),

    # Round videos
    "round_making": ("⚪ Делаю кружок…", "⚪ Making a round video…"),
    "round_first_minute": ("⚪ Делаю кружок из первой минуты, под ним будут кнопки следующих.",
                           "⚪ Making a round video of the first minute, with buttons for the next ones under it."),
    "rounds_busy": ("Секунду, ещё делаю прошлый кружок…", "A moment, still making the previous round video…"),
    "round_failed": ("Не получилось сделать кружок.", "Couldn't make the round video."),
    "round_render_failed": ("Не получилось сделать кружок из этого видео.",
                            "Couldn't make a round video of this video."),
    "rounds_forbidden": ("Кружки закрыты в настройках конфиденциальности Telegram (Голосовые сообщения). "
                         "Разреши их и нажми ещё раз.",
                         "Round videos are blocked in your Telegram privacy settings (Voice messages). "
                         "Allow them and tap again."),

    # Stickers
    "making_sticker": ("🎭 Делаю стикер из первых {seconds:g} секунд. Под ним — сдвиг, скорость и форма. Точный "
                       "момент — ответь на видео временем, например 0:12 или 0:12-0:14",
                       "🎭 Making a sticker of the first {seconds:g} seconds, with move, speed and shape buttons "
                       "under it. For an exact moment, reply to the video with a time like 0:12 or 0:12-0:14"),
    "sticker_busy": ("Подожди, ещё делаю предыдущий стикер.", "Wait, I'm still making the previous sticker."),
    "sticker_failed": ("Не получилось сделать стикер.", "Couldn't make the sticker."),
    "sticker_rejected": ("Telegram не принял стикер. Попробуй другой момент.",
                         "Telegram didn't take the sticker. Try another moment."),
    "sticker_render_failed": ("Не получилось сделать стикер из этого видео.",
                              "Couldn't make a sticker of this video."),
    "too_much_motion": ("Тут слишком много движения — не влезает в 256 КБ. Попробуй другой момент.",
                        "Too much motion here, it doesn't fit into 256 KB. Try another moment."),
    "already_so": ("Уже так", "Already like this"),
    "sticker_not_found": ("Стикер не найден.", "Sticker not found."),
    "one_moment": ("Секунду…", "One moment…"),
    "pack_failed": ("Не получилось добавить в пак, попробуй ещё раз.", "Couldn't add it to the pack, try again."),
    "pack_added": ("✅ Добавил в твой пак", "✅ Added to your pack"),
    "time_to_video": ("Чтобы сделать стикер с этого момента, ответь этим временем на видео.",
                      "To make a sticker from that moment, reply to the video with this time."),
    "time_to_sticker": ("Чтобы сделать стикер с этого момента, ответь временем на само видео, а не на стикер.",
                        "To make a sticker from that moment, reply with the time to the video, not the sticker."),
    "seconds": ("{n:g}с", "{n:g}s"),
    "shape_original": ("Ориг", "Orig"),
    "shape_round": ("⚪ Круг", "⚪ Circle"),
    "keep": ("➕ В мой пак · {cut}", "➕ Add to my pack · {cut}"),
    "kept": ("✅ В паке — открыть", "✅ In the pack, open it"),

    # Reports
    "report_prompt": ("📮 Что не так или что добавить? Напиши одним сообщением — можно со скриншотом или ссылкой.",
                      "📮 What's wrong, or what should I add? Write it in one message, a screenshot or a link "
                      "is welcome."),
    "report_placeholder": ("Ошибка или идея…", "A bug or an idea…"),
    "report_wait": ("Подожди немного перед следующим репортом.", "Wait a little before the next report."),
    "report_sent": ("✅ Передал разработчику, спасибо! Ответ, если будет, придёт сюда.",
                    "✅ Passed on to the developer, thanks! If there's an answer, it will come here."),
    "report_failed": ("❌ Не получилось отправить репорт. Попробуй ещё раз чуть позже.",
                      "❌ Couldn't send the report. Try again a bit later."),
    "report_answer": ("💬 Ответ на твой репорт:", "💬 An answer to your report:"),

    # For the owner
    "report_mark": ("📮 Репорт", "📮 Report"),
    "report_no_text": ("<i>без описания</i>", "<i>no description</i>"),
    "report_reply_hint": ("↩️ Ответь на это сообщение — перешлю ответ.",
                          "↩️ Reply to this message and I'll pass the answer on."),
    "answer_sent": ("✅ Отправил.", "✅ Sent."),
    "answer_blocked": ("❌ Не доставил: пользователь заблокировал бота.",
                       "❌ Not delivered: the user has blocked the bot."),
    "answer_failed": ("❌ Не доставил: {error}", "❌ Not delivered: {error}"),
    "disk_low": ("⚠️ На сервере осталось {mb} МБ — загрузки приостановлены, пока место не освободится.",
                 "⚠️ {mb} MB left on the server, downloads are paused until there's more space."),
    "disk_ok": ("✅ Место на диске освободилось ({mb} МБ), загрузки снова работают.",
                "✅ Disk space is back ({mb} MB), downloads work again."),
}
