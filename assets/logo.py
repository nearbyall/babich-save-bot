"""Matrix-style avatar for @babichsavebot: digital rain with hidden phrases + glowing download arrow.

python logo.py OUT.png            -> static 640x640 PNG
python logo.py FRAMES_DIR anim    -> looping frames for an animated avatar (8 s at 25 fps)
"""
import math
import os
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

S = 1280  # draw at 2x, downscale to 640
OUT = sys.argv[1]
ANIM = len(sys.argv) > 2 and sys.argv[2] == "anim"
FRAMES = 200
STATIC_T = 0.37  # moment of the loop used for the static picture

KATAKANA = [chr(c) for c in range(0xFF66, 0xFF9E)]
GLYPHS = KATAKANA * 3 + list("0123456789Z:.=*+-<>¦|")
rain_font = ImageFont.truetype("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 40)
text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 36)

GREEN = (0, 255, 65)
DARK = (0, 59, 0)
HEAD = (215, 255, 215)
BLACK = (0, 0, 0)
STEP_X, STEP_Y = 42, 46
COLS = S // STEP_X + 1
ROWS = S // STEP_Y + 1
CYCLE = ROWS + 34  # a drop's trip: enters at the top, leaves fully at the bottom
TAIL = 6  # katakana trailing above a phrase

# Phrase columns: (column, phrase, row of its last letter in the static picture).
# A second phrase in the same column runs half a cycle behind and shows up in the animation.
PHRASES = [
    (1, "NO ADS", 17),
    (4, "BABICH SAVE BOT", 20),
    (7, "REELS", 7),
    (10, "TIKTOK", 6),
    (13, "FREE", 25),
    (21, "SHORTS", 7),
    (24, "FREE DOWNLOADING", 20),
    (26, "ZHEKA BABICH BOT", 21),
]
LATER = {1: "FREE", 4: "@BABICHSAVEBOT", 7: "SAVE IT", 10: "NO LOGIN", 13: "GET IT",
         21: "REELS", 24: "REELS TIKTOKS SHORTS", 26: "NO SUBSCRIPTIONS"}


def lerp(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def glow(layer: Image.Image, radii, strength) -> Image.Image:
    out = layer
    for r, k in zip(radii, strength):
        out = ImageChops.add(out, layer.filter(ImageFilter.GaussianBlur(r)).point(lambda v, k=k: int(v * k)))
    return out


def head_at(phase: float, speed: int, t: float) -> int:
    return math.floor((phase + speed * CYCLE * t) % CYCLE) - 4


def phase_for(head_row: int, speed: int, t: float) -> float:
    return (head_row + 4.5 - speed * CYCLE * t) % CYCLE


# Mirrored glyph masks, like the film; phrases stay readable
tiles = {}
for ch in set(GLYPHS):
    tile = Image.new("L", (STEP_X, STEP_Y), 0)
    ImageDraw.Draw(tile).text((STEP_X / 2, STEP_Y / 2), ch, font=rain_font, fill=255, anchor="mm")
    tiles[ch] = tile.transpose(Image.FLIP_LEFT_RIGHT)

rng = random.Random(7)
text_cols = {col for col, _, _ in PHRASES}
drops = []  # katakana: (column, phase in rows, speed in cycles per loop, trail length)
for col in range(COLS):
    if col in text_cols:
        continue
    for _ in range(rng.choice([1, 1, 2])):
        drops.append((col, rng.uniform(0, CYCLE), rng.choice([1, 1, 2]), rng.randint(6, 26)))
phrase_drops = []  # (column, phase, text); speed is always 1 so they're easy to read
for col, text, head_row in PHRASES:
    phase = phase_for(head_row, 1, STATIC_T)
    phrase_drops.append((col, phase, text))
    phrase_drops.append((col, (phase + CYCLE / 2) % CYCLE, LATER[col]))
cell_seed = {(c, r): rng.random() for c in range(COLS) for r in range(-CYCLE, CYCLE)}


def glyph(col: int, row: int, t: float) -> tuple[str, bool]:
    """Glyph at a cell; it flickers to a new one 6 times per loop at its own moment."""
    tick = math.floor(t * 6 + cell_seed[(col, row)] * 6) % 6
    r = random.Random(hash((col, row, tick)))
    return r.choice(GLYPHS), r.random() < 0.08


def rain_layer(t: float) -> Image.Image:
    img = Image.new("RGB", (S, S), BLACK)
    draw = ImageDraw.Draw(img)

    def kana(col, row, color):
        if 0 <= row < ROWS:
            img.paste(color, (col * STEP_X, row * STEP_Y), tiles[glyph(col, row, t)[0]])

    for col, phase, speed, length in drops:
        head = head_at(phase, speed, t)
        for i in range(length):
            color = HEAD if i == 0 else lerp(GREEN, DARK, (i / length) ** 0.8)
            if i and glyph(col, head - i, t)[1]:  # a few glitchy bright cells
                color = lerp(GREEN, HEAD, 0.4)
            kana(col, head - i, color)

    for col, phase, text in phrase_drops:
        head = head_at(phase, 1, t)
        for i, ch in enumerate(reversed(text)):  # last letter leads, the phrase reads top to bottom
            row = head - i
            if ch == " " or not 0 <= row < ROWS:
                continue
            color = HEAD if i == 0 else lerp(GREEN, DARK, 0.35 * i / len(text))
            draw.text((col * STEP_X + STEP_X / 2, row * STEP_Y + STEP_Y / 2), ch,
                      font=text_font, fill=color, anchor="mm")
        for j in range(TAIL):
            kana(col, head - len(text) - j, lerp(GREEN, DARK, 0.45 + 0.55 * (j + 1) / TAIL))
    return img


def radial_mask(floor: int) -> Image.Image:
    """Dim behind the emblem and fade out at the circle's edge (Telegram crops avatars)."""
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    for r in range(S // 2, 0, -4):
        d = r / (S / 2)
        inner = max(0.0, min(1.0, (d - 0.38) / 0.25))
        edge = max(0.0, min(1.0, (1.02 - d) / 0.12))
        md.ellipse((S / 2 - r, S / 2 - r, S / 2 + r, S / 2 + r), fill=int((floor + (255 - floor) * inner) * edge))
    return mask.filter(ImageFilter.GaussianBlur(20))


vignette = radial_mask(70)

# --- emblem: download arrow over a tray ---
emblem = Image.new("RGB", (S, S), BLACK)
ed = ImageDraw.Draw(emblem)
c = S // 2
shaft_w, top, head_top, tip = 120, c - 330, c - 20, c + 170
ed.rectangle((c - shaft_w // 2, top, c + shaft_w // 2, head_top + 5), fill=GREEN)
ed.polygon([(c - 250, head_top), (c + 250, head_top), (c, tip)], fill=GREEN)
tw, ty, th, bar = 330, c + 175, 150, 62
ed.rectangle((c - tw, ty, c - tw + bar, ty + th), fill=GREEN)
ed.rectangle((c + tw - bar, ty, c + tw, ty + th), fill=GREEN)
ed.rectangle((c - tw, ty + th - bar, c + tw, ty + th), fill=GREEN)

scan = Image.new("L", (S, S), 255)  # CRT scanlines inside the emblem
sd = ImageDraw.Draw(scan)
for y in range(0, S, 10):
    sd.rectangle((0, y, S, y + 3), fill=150)
emblem = Image.composite(emblem, Image.new("RGB", (S, S), BLACK), scan)
# dark halo so the emblem separates from the rain behind it
halo = emblem.convert("L").point(lambda v: 255 if v > 20 else 0).filter(ImageFilter.MaxFilter(41))
halo = halo.filter(ImageFilter.GaussianBlur(6))
emblem_core = glow(emblem, (6,), (0.9,))
emblem_aura = ImageChops.add(emblem.filter(ImageFilter.GaussianBlur(22)).point(lambda v: int(v * 0.7)),
                             emblem.filter(ImageFilter.GaussianBlur(60)).point(lambda v: int(v * 0.55)))

lines = Image.new("L", (S, S), 255)  # subtle scanlines over everything
ld = ImageDraw.Draw(lines)
for y in range(0, S, 6):
    ld.line((0, y, S, y), fill=215, width=2)
lines = Image.merge("RGB", (lines, lines, lines))
background = Image.new("RGB", (S, S), (0, 6, 2))


def frame(t: float) -> Image.Image:
    rain = Image.composite(rain_layer(t), Image.new("RGB", (S, S), BLACK), vignette)
    img = ImageChops.add(background, glow(rain, (6,), (0.7,)))
    img = Image.composite(Image.new("RGB", (S, S), (0, 4, 1)), img, halo)
    pulse = 0.85 + 0.15 * math.cos(2 * math.pi * t)  # the aura breathes once per loop
    img = ImageChops.add(img, emblem_aura.point(lambda v: int(v * pulse)))
    img = ImageChops.add(img, emblem_core)
    return ImageChops.multiply(img, lines).resize((640, 640), Image.LANCZOS)


if ANIM:
    os.makedirs(OUT, exist_ok=True)
    for n in range(FRAMES):
        frame(n / FRAMES).save(f"{OUT}/{n:04d}.png")
    print("saved", FRAMES, "frames to", OUT)
else:
    frame(STATIC_T).save(OUT, optimize=True)
    print("saved", OUT)
