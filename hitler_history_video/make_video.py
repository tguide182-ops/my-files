#!/usr/bin/env python3
"""
"Adolf Hitler: A History in One Minute" - 2D animated educational short.

Generates a 60-second 1280x720 MP4 with:
  * cartoon 2D animation drawn frame-by-frame (Pillow)
  * a historical character + an animated narrator whose mouth syncs to the voice
  * neural voice-over narration (Microsoft edge-tts, falls back to gTTS)
  * real public-domain / CC0 sound effects + Chopin's Funeral March from
    Wikimedia Commons (see assets/CREDITS.md); any clip that is missing is
    downloaded automatically, or replaced by a synthesized sound
  * burned-in subtitles

Requirements:
    pip install pillow numpy edge-tts gTTS
    ffmpeg on PATH

Run:
    python make_video.py            -> hitler_history_1min.mp4
"""
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1280, 720, 24
SR = 44100
OUT = "hitler_history_1min.mp4"
HERE = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------------
# SCRIPT  (duration in seconds, narration text, on-screen label)
# ----------------------------------------------------------------------------
SCENES = [
    (7.5, "Adolf Hitler was born in 1889, in the small Austrian town of Braunau am Inn.",
     "Braunau am Inn, Austria  -  1889"),
    (9.5, "As a young man, he was rejected by art school in Vienna. "
          "Then he fought for Germany in the First World War.",
     "Vienna 1907  /  Western Front 1914-1918"),
    (10.0, "After Germany's defeat, he led the Nazi Party, giving furious speeches "
           "that blamed Jews and others for the country's problems.",
     "Munich  -  1920s"),
    (7.5, "In 1933 he became Chancellor, and quickly made himself dictator, "
          "banning all opposition.",
     "Berlin  -  1933"),
    (9.0, "In 1939 he invaded Poland, starting the Second World War, "
          "the deadliest conflict in human history.",
     "Europe  -  1939-1945"),
    (8.0, "His regime murdered six million Jews in the Holocaust, "
          "along with millions of other victims.",
     ""),
    (8.5, "In April 1945, with Berlin in ruins, he took his own life. "
          "History remembers, so it never happens again.",
     "Berlin  -  April 1945"),
]
STARTS = np.cumsum([0] + [s[0] for s in SCENES])[:-1]
TOTAL = float(sum(s[0] for s in SCENES))
NFRAMES = int(TOTAL * FPS)

# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def font(size, bold=True, serif=False):
    names = (["DejaVuSerif-Bold.ttf", "DejaVuSerif.ttf"] if serif else
             ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"])
    if not bold:
        names = names[::-1]
    for n in names:
        for d in ["/usr/share/fonts/truetype/dejavu", "/Library/Fonts",
                  "C:/Windows/Fonts", ""]:
            p = os.path.join(d, n)
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    for n in ["arialbd.ttf", "Arial Bold.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    return ImageFont.load_default()


F_TITLE = font(78, serif=True)
F_SUB = font(34, serif=True)
F_LABEL = font(26)
F_CAP = font(28)
F_BIG = font(110, serif=True)
F_SMALL = font(22, bold=False)


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return a + (b - a) * t


def ctext(d, xy, text, f, fill, stroke=0, stroke_fill=(0, 0, 0)):
    x, y = xy
    bb = d.textbbox((0, 0), text, font=f, stroke_width=stroke)
    d.text((x - (bb[2] - bb[0]) / 2, y - (bb[3] - bb[1]) / 2), text, font=f,
           fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)


def wrap(d, text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > maxw and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


# ----------------------------------------------------------------------------
# CHARACTERS
# ----------------------------------------------------------------------------
SKIN = (238, 200, 165)
HAIR = (40, 30, 25)
COAT = (110, 92, 62)
COAT_D = (80, 66, 45)
BOOT = (30, 25, 20)


def draw_hitler(d, x, y, s=1.0, arm_l=200, arm_r=-20, mouth=0.0, child=False,
                helmet=False, coat=COAT, walk=0.0, frown=True):
    """Cartoon figure. (x, y) = feet centre. Arm angles in degrees (0 = right)."""
    if child:
        s *= 0.6
    leg = 70 * s
    body_h = 95 * s
    head_r = 34 * s * (1.25 if child else 1)
    hip_y = y - leg
    sh_y = hip_y - body_h
    # legs (walk cycle)
    sw = math.sin(walk) * 16 * s
    for dx, k in ((-12 * s, 1), (12 * s, -1)):
        d.line([(x + dx, hip_y), (x + dx + sw * k, y)], fill=COAT_D, width=int(18 * s))
        d.ellipse([x + dx + sw * k - 13 * s, y - 8 * s, x + dx + sw * k + 15 * s, y + 6 * s],
                  fill=BOOT)
    # body / coat
    d.rounded_rectangle([x - 34 * s, sh_y, x + 34 * s, hip_y + 12 * s],
                        radius=int(14 * s), fill=coat)
    d.line([(x, sh_y + 8 * s), (x, hip_y + 10 * s)], fill=COAT_D, width=max(1, int(3 * s)))
    for i in range(3):
        by = sh_y + (22 + i * 24) * s
        d.ellipse([x + 6 * s, by, x + 12 * s, by + 6 * s], fill=(200, 180, 120))
    d.line([(x - 34 * s, hip_y - 26 * s), (x + 34 * s, hip_y - 26 * s)],
           fill=COAT_D, width=int(7 * s))  # belt
    # arms
    for ang, sx in ((arm_l, x - 30 * s), (arm_r, x + 30 * s)):
        a = math.radians(ang)
        ex = sx + math.cos(a) * 62 * s
        ey = sh_y + 14 * s - math.sin(a) * 62 * s
        d.line([(sx, sh_y + 14 * s), (ex, ey)], fill=coat, width=int(17 * s))
        d.ellipse([ex - 9 * s, ey - 9 * s, ex + 9 * s, ey + 9 * s], fill=SKIN)
    # head
    hx, hy = x, sh_y - head_r * 0.85
    d.rectangle([hx - 10 * s, sh_y - 14 * s, hx + 10 * s, sh_y + 2 * s], fill=SKIN)
    d.ellipse([hx - head_r, hy - head_r, hx + head_r, hy + head_r], fill=SKIN)
    if helmet:
        d.chord([hx - head_r - 8 * s, hy - head_r - 8 * s, hx + head_r + 8 * s,
                 hy + head_r * 0.6], 180, 360, fill=(70, 80, 60))
        d.rectangle([hx - head_r - 12 * s, hy - 6 * s, hx + head_r + 12 * s, hy + 2 * s],
                    fill=(60, 70, 50))
    else:
        # dark side-swept hair with fringe across the forehead
        d.chord([hx - head_r - 2, hy - head_r - 3, hx + head_r + 2, hy + head_r * 0.4],
                180, 360, fill=HAIR)
        if not child:
            d.polygon([(hx - head_r * 0.2, hy - head_r * 0.7), (hx + head_r, hy - head_r * 0.4),
                       (hx - head_r * 0.6, hy - head_r * 0.05)], fill=HAIR)
    # eyes / brows
    ey_ = hy - 2 * s
    for ex in (hx - 12 * s, hx + 12 * s):
        d.ellipse([ex - 4 * s, ey_ - 4 * s, ex + 4 * s, ey_ + 4 * s], fill=(20, 20, 20))
        if frown and not child:
            k = 1 if ex < hx else -1
            d.line([(ex - 8 * s, ey_ - 12 * s + (-3 * s) * k), (ex + 8 * s, ey_ - 12 * s + (3 * s) * k)],
                   fill=HAIR, width=max(2, int(4 * s)))
    # mustache + mouth
    my = hy + 13 * s
    if not child:
        d.rectangle([hx - 7 * s, my - 6 * s, hx + 7 * s, my + 2 * s], fill=HAIR)
    mo = 2 + mouth * 12
    d.ellipse([hx - 8 * s, my + 5 * s, hx + 8 * s, my + 5 * s + mo * s], fill=(110, 30, 30))


def draw_narrator(img, mouth, t):
    """Friendly historian in a framed corner panel; mouth follows the voice."""
    d = ImageDraw.Draw(img)
    px, py, pw, ph = W - 230, 20, 210, 210
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=22, fill=(245, 235, 210),
                        outline=(90, 60, 30), width=5)
    cx, cy = px + pw / 2, py + 110 + math.sin(t * 2) * 2
    # body
    d.pieslice([cx - 80, cy + 45, cx + 80, cy + 210], 180, 360, fill=(60, 80, 120))
    d.polygon([(cx - 14, cy + 50), (cx + 14, cy + 50), (cx, cy + 75)], fill=(240, 240, 240))
    d.polygon([(cx - 14, cy + 58), (cx, cy + 64), (cx - 14, cy + 70)], fill=(170, 30, 40))
    d.polygon([(cx + 14, cy + 58), (cx, cy + 64), (cx + 14, cy + 70)], fill=(170, 30, 40))
    # head
    d.ellipse([cx - 45, cy - 55, cx + 45, cy + 50], fill=(230, 190, 150))
    d.chord([cx - 48, cy - 62, cx + 48, cy + 10], 180, 360, fill=(190, 190, 195))
    d.ellipse([cx - 52, cy - 15, cx - 38, cy + 12], fill=(230, 190, 150))
    d.ellipse([cx + 38, cy - 15, cx + 52, cy + 12], fill=(230, 190, 150))
    # glasses + eyes (blink)
    blink = (t % 3.7) < 0.12
    for ex in (cx - 18, cx + 18):
        d.ellipse([ex - 14, cy - 14, ex + 14, cy + 12], outline=(40, 40, 40), width=3)
        if blink:
            d.line([(ex - 6, cy - 1), (ex + 6, cy - 1)], fill=(30, 30, 30), width=3)
        else:
            d.ellipse([ex - 4, cy - 5, ex + 4, cy + 3], fill=(30, 30, 30))
    d.line([(cx - 4, cy - 2), (cx + 4, cy - 2)], fill=(40, 40, 40), width=3)
    # beard + mouth
    d.chord([cx - 34, cy + 5, cx + 34, cy + 55], 0, 180, fill=(200, 200, 205))
    mo = 3 + mouth * 16
    d.ellipse([cx - 12, cy + 22 - mo / 2, cx + 12, cy + 22 + mo / 2], fill=(90, 25, 25))
    d.rounded_rectangle([px + 45, py + ph - 14, px + pw - 45, py + ph + 14], radius=8,
                        fill=(90, 60, 30))
    ctext(d, (cx, py + ph), "NARRATOR", F_SMALL, (245, 235, 210))


# ----------------------------------------------------------------------------
# SCENES  (each: draw(img, d, t, dur))
# ----------------------------------------------------------------------------
def sky(d, top, bot, y1=H):
    for y in range(0, y1, 4):
        k = y / y1
        d.rectangle([0, y, W, y + 4], fill=tuple(int(lerp(a, b, k)) for a, b in zip(top, bot)))


def scene_birth(img, d, t, dur):
    sky(d, (250, 225, 180), (235, 200, 150))
    d.ellipse([980, 60, 1080, 160], fill=(255, 240, 200))
    # hills
    d.ellipse([-200, 470, 700, 900], fill=(150, 160, 100))
    d.ellipse([400, 500, 1500, 950], fill=(130, 145, 90))
    # little town houses
    for i, hx in enumerate([180, 330, 820, 980]):
        hh = 120 + (i % 2) * 30
        d.rectangle([hx, 520 - hh, hx + 110, 520], fill=(225, 205, 170), outline=(120, 90, 60), width=3)
        d.polygon([(hx - 10, 520 - hh), (hx + 55, 450 - hh), (hx + 120, 520 - hh)], fill=(160, 70, 50))
        d.rectangle([hx + 40, 470, hx + 70, 520], fill=(100, 70, 40))
    # church steeple
    d.rectangle([600, 300, 660, 520], fill=(220, 200, 165), outline=(120, 90, 60), width=3)
    d.polygon([(590, 300), (630, 180), (670, 300)], fill=(80, 100, 90))
    d.rectangle([0, 600, W, H], fill=(120, 135, 80))
    # child walks in
    cx = lerp(-60, 520, ease(t / 5.5))
    draw_hitler(d, cx, 640, 1.3, arm_l=250, arm_r=-70, child=True, walk=t * 9 if t < 5.5 else 0,
                coat=(90, 110, 140), frown=False)
    # title card
    a = ease(t / 0.8) * (1 - ease((t - 5.5) / 1.0))
    if a > 0.01:
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        od.rectangle([0, 230, W, 400], fill=(20, 15, 10, int(200 * a)))
        ctext(od, (W / 2 - 100, 290), "ADOLF HITLER", F_TITLE, (245, 230, 200, int(255 * a)))
        ctext(od, (W / 2 - 100, 360), "A history in one minute  |  1889 - 1945", F_SUB,
              (220, 190, 140, int(255 * a)))
        img.alpha_composite(ov)


def scene_vienna_war(img, d, t, dur):
    if t < 4.6:
        # Vienna art academy
        d.rectangle([0, 0, W, H], fill=(225, 215, 195))
        for cx in range(80, W, 220):  # classical columns
            d.rectangle([cx, 80, cx + 50, 560], fill=(240, 232, 215), outline=(170, 150, 120), width=3)
        d.rectangle([0, 50, W, 90], fill=(200, 185, 160))
        d.rectangle([0, 560, W, H], fill=(150, 120, 90))
        # easel
        d.line([(700, 600), (760, 330)], fill=(110, 70, 40), width=10)
        d.line([(860, 600), (800, 330)], fill=(110, 70, 40), width=10)
        d.rectangle([660, 340, 900, 520], fill=(250, 248, 240), outline=(110, 70, 40), width=6)
        # painting: buildings
        d.rectangle([690, 420, 740, 500], fill=(180, 140, 110))
        d.rectangle([760, 390, 820, 500], fill=(160, 150, 130))
        d.rectangle([835, 440, 875, 500], fill=(190, 160, 120))
        brush = math.sin(t * 10) * 20
        draw_hitler(d, 560, 640, 1.25, arm_l=210, arm_r=25 + brush, mouth=0, coat=(70, 70, 80))
        if t > 2.6:  # REJECTED stamp slams in
            k = ease((t - 2.6) / 0.25)
            sc = lerp(2.2, 1.0, k)
            st = Image.new("RGBA", (420, 130), (0, 0, 0, 0))
            sd = ImageDraw.Draw(st)
            sd.rounded_rectangle([5, 5, 415, 125], radius=12, outline=(200, 20, 20, 230), width=10)
            ctext(sd, (210, 62), "REJECTED", font(70), (200, 20, 20, 230))
            st = st.resize((int(420 * sc), int(130 * sc))).rotate(-12, expand=True)
            img.alpha_composite(st, (int(780 - st.width / 2), int(430 - st.height / 2)))
    else:
        tt = t - 4.6
        # WWI trench, night
        sky(d, (60, 55, 60), (120, 100, 85), 450)
        d.rectangle([0, 430, W, H], fill=(75, 60, 45))
        d.polygon([(0, 470), (W, 450), (W, 520), (0, 540)], fill=(55, 42, 32))
        # barbed wire
        for xx in range(0, W, 60):
            d.line([(xx, 420), (xx + 30, 400), (xx + 60, 420)], fill=(40, 40, 40), width=3)
            d.line([(xx + 30, 400), (xx + 30, 440)], fill=(40, 40, 40), width=4)
        # explosions
        for i, (ex, et) in enumerate([(300, 0.4), (950, 1.6), (620, 3.0), (1100, 3.9)]):
            k = (tt - et) / 0.9
            if 0 <= k <= 1:
                r = 40 + 160 * k
                col = (255, int(200 - 120 * k), 60)
                d.ellipse([ex - r, 400 - r * 1.3, ex + r, 400 + r * 0.4], fill=col)
                d.ellipse([ex - r * 0.6, 400 - r, ex + r * 0.6, 400], fill=(255, 245, 180))
                for j in range(10):
                    a = j * 0.63 + i
                    d.ellipse([ex + math.cos(a) * r * 1.2 - 6, 400 - abs(math.sin(a)) * r * 1.4 - 6,
                               ex + math.cos(a) * r * 1.2 + 6, 400 - abs(math.sin(a)) * r * 1.4 + 6],
                              fill=(60, 50, 40))
        # soldier in trench (sandbags in front)
        draw_hitler(d, 640, 690, 1.3, arm_l=190, arm_r=10, helmet=True, coat=(110, 115, 90))
        for sx in range(380, 920, 70):
            d.ellipse([sx, 600, sx + 90, 660], fill=(150, 130, 95), outline=(90, 75, 55), width=3)
        d.rectangle([0, 650, W, H], fill=(65, 50, 38))


def scene_rally(img, d, t, dur):
    d.rectangle([0, 0, W, H], fill=(60, 35, 30))
    # hall arches + plain red banners (no symbols)
    for bx in range(60, W, 260):
        d.rectangle([bx, 40, bx + 110, 360], fill=(150, 20, 25))
        d.rectangle([bx, 40, bx + 110, 60], fill=(100, 15, 20))
    d.rectangle([0, 360, W, H], fill=(45, 28, 22))
    # spotlight cone
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.polygon([(560, 0), (720, 0), (860, 560), (420, 560)], fill=(255, 240, 190, 50))
    img.alpha_composite(ov)
    # podium + speaker
    gest = math.sin(t * 5.0)
    draw_hitler(d, 640, 470, 1.35, arm_l=150 + 50 * gest, arm_r=40 - 50 * math.sin(t * 5 + 1.3),
                mouth=abs(math.sin(t * 13)), walk=0)
    d.polygon([(540, 400), (740, 400), (720, 560), (560, 560)], fill=(120, 75, 45))
    d.rectangle([530, 390, 750, 410], fill=(90, 55, 30))
    # angry speech marks
    if int(t * 4) % 2 == 0:
        for i in range(3):
            d.line([(760 + i * 18, 200 - i * 10), (790 + i * 22, 175 - i * 14)], fill=(255, 230, 120), width=6)
    # crowd (silhouettes, bobbing)
    random.seed(4)
    for row in range(3):
        for i in range(16):
            cx = i * 85 + (row % 2) * 40 + 20
            cy = 600 + row * 45 + math.sin(t * 6 + i + row) * 4
            shade = 25 + row * 10
            d.ellipse([cx - 26, cy - 50, cx + 26, cy + 2], fill=(shade, shade - 5, shade - 8))
            d.rounded_rectangle([cx - 40, cy - 5, cx + 40, cy + 90], radius=20,
                                fill=(shade, shade - 5, shade - 8))
    # propaganda/hate callout
    if t > 4.5:
        a = ease((t - 4.5) / 0.6)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        od.rounded_rectangle([60, 120, 470, 260], radius=14, fill=(250, 240, 220, int(235 * a)))
        ctext(od, (265, 160), "Hate & scapegoating", F_LABEL, (150, 20, 20, int(255 * a)))
        ctext(od, (265, 210), "blamed Jews for", F_SMALL, (40, 30, 20, int(255 * a)))
        ctext(od, (265, 238), "Germany's problems", F_SMALL, (40, 30, 20, int(255 * a)))
        img.alpha_composite(ov)


def scene_dictator(img, d, t, dur):
    if t < 2.4:
        # calendar flip
        d.rectangle([0, 0, W, H], fill=(70, 60, 55))
        d.rounded_rectangle([440, 130, 840, 560], radius=20, fill=(245, 240, 230))
        d.rectangle([440, 130, 840, 230], fill=(160, 25, 30))
        days = ["1931", "1932", "1933"]
        idx = min(2, int(t / 0.6))
        ctext(d, (640, 180), "JANUARY", F_SUB, (255, 255, 255))
        ctext(d, (640, 360), "30", F_BIG, (40, 30, 30))
        ctext(d, (640, 480), days[idx], F_TITLE, (160, 25, 30))
        return
    tt = t - 2.4
    # office; shadow on the wall grows huge = dictatorship
    d.rectangle([0, 0, W, H], fill=(190, 170, 140))
    d.rectangle([0, 520, W, H], fill=(100, 70, 50))
    for wx in (120, 1000):  # tall windows
        d.rectangle([wx, 90, wx + 160, 420], fill=(150, 175, 195), outline=(80, 60, 40), width=8)
        d.line([(wx + 80, 90), (wx + 80, 420)], fill=(80, 60, 40), width=6)
    sc = lerp(1.2, 3.6, ease(tt / 3.5))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    draw_hitler(sd, 700, 560, sc, arm_l=200, arm_r=60, coat=(0, 0, 0))
    sh = sh.filter(ImageFilter.GaussianBlur(4))
    alpha = sh.split()[3].point(lambda v: int(v * 0.45))
    sh.putalpha(alpha)
    img.alpha_composite(sh)
    d = ImageDraw.Draw(img)
    draw_hitler(d, 640, 640, 1.3, arm_l=220, arm_r=70, mouth=0.3)
    d.rectangle([420, 560, 860, 590], fill=(80, 50, 30))
    d.rectangle([440, 590, 470, 700], fill=(70, 45, 25))
    d.rectangle([810, 590, 840, 700], fill=(70, 45, 25))
    for i, (txt, ts) in enumerate([("PARTIES BANNED", 1.0), ("PRESS SILENCED", 2.0),
                                   ("OPPONENTS JAILED", 3.0)]):
        if tt > ts:
            k = ease((tt - ts) / 0.2)
            stx, sty = [(260, 470), (640, 140), (1040, 470)][i]
            st = Image.new("RGBA", (360, 80), (0, 0, 0, 0))
            s2 = ImageDraw.Draw(st)
            s2.rounded_rectangle([3, 3, 357, 77], radius=8, fill=(255, 250, 235, 230),
                                 outline=(170, 20, 20, 255), width=6)
            ctext(s2, (180, 40), txt, F_LABEL, (170, 20, 20, 255))
            st = st.resize((int(360 * lerp(1.6, 1, k)), int(80 * lerp(1.6, 1, k)))).rotate(
                [-8, 5, 7][i], expand=True)
            img.alpha_composite(st, (int(stx - st.width / 2), int(sty - st.height / 2)))


EUROPE = {  # stylised positions
    "GERMANY": (600, 360, 85), "POLAND": (780, 330, 70), "FRANCE": (420, 470, 95),
    "BRITAIN": (370, 250, 60), "NORWAY": (620, 120, 55), "USSR": (990, 330, 120),
    "LOW C.": (480, 340, 40), "ITALY": (640, 560, 55), "DENMARK": (590, 235, 30),
}


def scene_war(img, d, t, dur):
    d.rectangle([0, 0, W, H], fill=(70, 100, 125))
    for y in range(0, H, 40):  # sea lines
        d.line([(0, y + math.sin(t + y) * 3), (W, y)], fill=(80, 112, 138), width=2)
    labels = []
    conquer = {"POLAND": 1.2, "DENMARK": 2.4, "NORWAY": 2.8, "LOW C.": 3.3, "FRANCE": 3.8}
    for name, (x, y, r) in EUROPE.items():
        col = (205, 190, 150)
        if name == "GERMANY":
            col = (60, 55, 50)
        elif name in conquer and t > conquer[name] + 0.4:
            col = (120, 100, 90)
        d.ellipse([x - r, y - r * 0.8, x + r, y + r * 0.8], fill=col, outline=(90, 75, 55), width=3)
        labels.append((x, y, name, (255, 255, 255) if col[0] < 130 else (60, 45, 30)))
    gx, gy, _ = EUROPE["GERMANY"]
    for name, ts in conquer.items():
        k = ease((t - ts) / 0.5)
        if k > 0:
            tx, ty, _ = EUROPE[name]
            ex, ey = lerp(gx, tx, k), lerp(gy, ty, k)
            d.line([(gx, gy), (ex, ey)], fill=(200, 30, 30), width=10)
            a = math.atan2(ey - gy, ex - gx)
            d.polygon([(ex + math.cos(a) * 18, ey + math.sin(a) * 18),
                       (ex + math.cos(a + 2.4) * 18, ey + math.sin(a + 2.4) * 18),
                       (ex + math.cos(a - 2.4) * 18, ey + math.sin(a - 2.4) * 18)], fill=(200, 30, 30))
    # 1941: attack on USSR
    k = ease((t - 5.0) / 0.8)
    if k > 0:
        tx, ty, _ = EUROPE["USSR"]
        d.line([(gx + 60, gy), (lerp(gx + 60, tx - 60, k), lerp(gy, ty, k))], fill=(200, 30, 30), width=10)
    for x, y, name, c in labels:
        ctext(d, (x, y), name, F_SMALL, c, 3, (40, 35, 30) if c[0] > 200 else (230, 220, 190))
    # planes crossing
    for i in range(3):
        px = (t * 260 - i * 160) % (W + 400) - 200
        py = 160 + i * 60
        d.polygon([(px, py), (px - 60, py - 6), (px - 60, py + 6)], fill=(40, 40, 45))
        d.polygon([(px - 25, py), (px - 45, py - 30), (px - 50, py - 30), (px - 38, py)], fill=(40, 40, 45))
        d.polygon([(px - 25, py), (px - 45, py + 30), (px - 50, py + 30), (px - 38, py)], fill=(40, 40, 45))
    yr = min(1945, 1939 + int(t / 1.3))
    d.rounded_rectangle([40, 30, 260, 110], radius=12, fill=(30, 25, 25))
    ctext(d, (150, 70), str(yr), F_TITLE, (240, 70, 60))
    if t > 6.3:
        ctext(d, (W / 2 + 60, 70), "~70-85 million people died in WWII", F_SUB, (255, 245, 220), 4, (20, 10, 10))


def scene_holocaust(img, d, t, dur):
    d.rectangle([0, 0, W, H], fill=(12, 12, 16))
    a = ease(t / 1.2)
    # candles
    for i in range(9):
        cx = 200 + i * 110
        cy = 560
        d.rectangle([cx - 14, cy - 60, cx + 14, cy + 40], fill=(230, 225, 210))
        fl = math.sin(t * 9 + i * 1.7) * 3
        glow = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([20, 20, 100, 100], fill=(255, 190, 80, int(70 * a)))
        glow = glow.filter(ImageFilter.GaussianBlur(14))
        img.alpha_composite(glow, (cx - 60, cy - 135))
        d = ImageDraw.Draw(img)
        d.ellipse([cx - 8 + fl * 0.3, cy - 95, cx + 8 + fl * 0.3, cy - 62], fill=(255, 200, 90))
        d.ellipse([cx - 4, cy - 82, cx + 4, cy - 66], fill=(255, 250, 220))
    c = int(235 * a)
    ctext(d, (W / 2, 140), "THE HOLOCAUST", F_SUB, (c, c, c))
    n = int(6_000_000 * ease((t - 0.8) / 3.0))
    ctext(d, (W / 2, 250), f"{n:,}", F_BIG, (int(220 * a), int(200 * a), int(160 * a)))
    ctext(d, (W / 2, 340), "Jewish men, women and children murdered", F_LABEL, (c, c, c))
    if t > 4.0:
        b = int(200 * ease((t - 4.0) / 1.0))
        ctext(d, (W / 2, 395), "and millions more: Roma, disabled people, Poles,", F_SMALL, (b, b, b))
        ctext(d, (W / 2, 425), "Soviet POWs, gay men, political opponents...", F_SMALL, (b, b, b))


def scene_end(img, d, t, dur):
    sky(d, (60, 30, 30), (230, 110, 50), 520)
    # ruined skyline
    random.seed(7)
    x = 0
    while x < W:
        w = random.randint(60, 140)
        h = random.randint(120, 320)
        pts = [(x, 520), (x, 520 - h)]
        for k in range(4):
            pts.append((x + w * (k + 1) / 5, 520 - h + random.randint(-50, 40)))
        pts += [(x + w, 520 - h + random.randint(0, 60)), (x + w, 520)]
        d.polygon(pts, fill=(45, 35, 35))
        for wy in range(520 - h + 50, 500, 40):
            for wx in range(x + 12, x + w - 20, 30):
                if random.random() < 0.5:
                    d.rectangle([wx, wy, wx + 12, wy + 18], fill=(255, 150, 60) if random.random() < 0.3 else (25, 20, 20))
        x += w + random.randint(0, 20)
    # smoke
    for i in range(6):
        sx = 150 + i * 200
        sy = 300 - (t * 30 + i * 50) % 260
        r = 40 + (t * 10 + i * 20) % 50
        d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(80, 70, 70))
    d.rectangle([0, 520, W, H], fill=(55, 50, 48))
    # bunker
    d.polygon([(780, 520), (1180, 520), (1150, 430), (810, 430)], fill=(110, 110, 105))
    door_close = ease((t - 3.2) / 0.4)
    d.rectangle([920, 450, 1020, 520], fill=(10, 10, 10))
    d.rectangle([920, 450, 920 + 100 * door_close, 520], fill=(70, 70, 68))
    if t < 3.3:
        hx = lerp(500, 970, ease(t / 3.0))
        draw_hitler(d, hx, 600 - 80 * ease((t - 2.4) / 0.8), 0.9, arm_l=250, arm_r=-70,
                    walk=t * 7, mouth=0)
    # final card
    if t > 4.6:
        a = ease((t - 4.6) / 0.8)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, int(225 * a)))
        od = ImageDraw.Draw(ov)
        ctext(od, (W / 2, 300), "REMEMBER.", F_TITLE, (240, 230, 210, int(255 * a)))
        ctext(od, (W / 2, 390), "So it never happens again.", F_SUB, (220, 190, 140, int(255 * a)))
        ctext(od, (W / 2, 470), "Music: Chopin, Marche funebre (CC0)  |  Sound effects: Wikimedia Commons",
              F_SMALL, (150, 140, 120, int(255 * a)))
        img.alpha_composite(ov)


DRAW = [scene_birth, scene_vienna_war, scene_rally, scene_dictator, scene_war,
        scene_holocaust, scene_end]

# ----------------------------------------------------------------------------
# AUDIO: narration
# ----------------------------------------------------------------------------
def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


VOICE = "en-GB-RyanNeural"   # try also: en-US-GuyNeural, en-GB-ThomasNeural


def tts_edge(text, path):
    import asyncio
    import ssl
    import edge_tts
    import edge_tts.communicate as comm
    # Respect a custom CA bundle (corporate proxies etc.); edge-tts pins certifi.
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        comm._SSL_CTX = ssl.create_default_context(cafile=ca)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    asyncio.run(edge_tts.Communicate(text, VOICE, rate="-4%", pitch="-4Hz",
                                     proxy=proxy).save(path))
    return os.path.getsize(path) > 1000


def tts(text, path):
    try:
        if tts_edge(text, path):
            return True
    except Exception as e:
        print("  edge-tts unavailable (", type(e).__name__, ") - falling back to gTTS")
    try:
        from gtts import gTTS
        gTTS(text, lang="en", tld="co.uk").save(path)
        return True
    except Exception as e:
        print("  ! TTS failed:", e)
        return False


def build_narration(tmp):
    track = np.zeros(int(TOTAL * SR) + SR, dtype=np.float32)
    for i, (dur, text, _) in enumerate(SCENES):
        mp3 = os.path.join(tmp, f"n{i}.mp3")
        print(f"  narration {i + 1}/{len(SCENES)}")
        if not tts(text, mp3):
            continue
        v = decode(mp3)
        # trim silence
        nz = np.where(np.abs(v) > 0.01)[0]
        if len(nz):
            v = v[max(0, nz[0] - 800): nz[-1] + 2000]
        room = (dur - 0.55) * SR
        if len(v) > room:  # speed up (pitch-preserving) to fit the scene
            tempo = min(2.0, len(v) / room)
            wav_in = os.path.join(tmp, f"n{i}.wav")
            write_wav(wav_in, v)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", wav_in, "-filter:a",
                                  f"atempo={tempo:.3f}", "-f", "f32le", "-ac", "1", "-ar",
                                  str(SR), "-"], capture_output=True, check=True).stdout
            v = np.frombuffer(raw, dtype=np.float32).copy()
        v = v / (np.abs(v).max() + 1e-9) * 0.9
        s = int((STARTS[i] + 0.3) * SR)
        track[s:s + len(v)] += v[:len(track) - s]
    return track


# ----------------------------------------------------------------------------
# AUDIO: synthesized sound effects + music
# ----------------------------------------------------------------------------
rng = np.random.default_rng(1)


def env(n, a=0.01, r=None):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4))
    if r:
        e *= np.exp(-t / r)
    return e


def lowpass(x, k):
    k = max(1, int(k))
    return np.convolve(x, np.ones(k) / k, mode="same")


def sfx_explosion(dur=1.8):
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    boom = lowpass(noise, 60) * 6 + lowpass(noise, 12) * 0.8
    sub = np.sin(2 * np.pi * np.cumsum(np.linspace(70, 30, n)) / SR) * 0.8
    return (boom + sub) * env(n, 0.005, 0.45)


def sfx_gunshot():
    n = int(0.25 * SR)
    return lowpass(rng.standard_normal(n), 4) * env(n, 0.001, 0.04) * 1.2


def sfx_stamp():
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 90 * t) * 1.2 + lowpass(rng.standard_normal(n), 8)) * env(n, 0.001, 0.07)


def sfx_whoosh(dur=0.9):
    n = int(dur * SR)
    x = rng.standard_normal(n)
    out = np.zeros(n)
    for i, k in enumerate(np.linspace(40, 4, 8)):
        seg = slice(i * n // 8, (i + 1) * n // 8)
        out[seg] = lowpass(x, k)[seg]
    return out * np.sin(np.linspace(0, np.pi, n)) * 1.5


def sfx_crowd(dur):
    n = int(dur * SR)
    x = lowpass(rng.standard_normal(n), 25) * 3
    mod = 0.6 + 0.4 * np.sin(2 * np.pi * 0.7 * np.arange(n) / SR) * np.sin(2 * np.pi * 0.23 * np.arange(n) / SR)
    swell = np.minimum(1, np.arange(n) / (SR * 1.5))
    return x * mod * swell


def sfx_cheer(dur=2.0):
    n = int(dur * SR)
    return lowpass(rng.standard_normal(n), 6) * 1.4 * np.sin(np.linspace(0, np.pi, n)) ** 0.5


def sfx_siren(dur=4.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 500 + 300 * np.sin(2 * np.pi * 0.35 * t - np.pi / 2)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.3 * np.sin(4 * np.pi * np.cumsum(f) / SR)
    return s * 0.35 * np.minimum(1, t / 0.5) * np.minimum(1, (dur - t) / 0.8)


def sfx_planes(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * f * t) for f in (82, 85.5, 164))
    s = s * (0.7 + 0.3 * np.sin(2 * np.pi * 6 * t)) + lowpass(rng.standard_normal(n), 30)
    return s * 0.15 * np.sin(np.linspace(0, np.pi, n))


def sfx_typewriter(dur=1.2):
    out = np.zeros(int(dur * SR))
    pos = 0
    while pos < len(out) - 3000:
        c = lowpass(rng.standard_normal(1500), 2) * env(1500, 0.0005, 0.006)
        out[pos:pos + 1500] += c
        pos += int(rng.uniform(0.06, 0.13) * SR)
    return out * 0.8


def sfx_bell(dur=4.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t / d) for f, a, d in
            [(220, 1, 2.5), (440.6, .5, 1.6), (528, .35, 1.2), (660.5, .25, .9), (880, .15, .6)])
    return s * env(n, 0.003)


def sfx_door():
    n = int(0.8 * SR)
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 55 * t) + lowpass(rng.standard_normal(n), 30) * 3) * env(n, 0.002, 0.18)


def sfx_flip():
    n = int(0.15 * SR)
    return lowpass(rng.standard_normal(n), 3) * env(n, 0.005, 0.03) * 0.6


def sfx_drums(dur):  # military snare march
    out = np.zeros(int(dur * SR))
    beat = 60 / 112
    pattern = [1, 0, .6, .6, 1, 0, .6, 0]
    i = 0
    while i * beat / 2 * SR < len(out) - SR * 0.2:
        v = pattern[i % 8]
        if v:
            n = int(0.15 * SR)
            hit = (lowpass(rng.standard_normal(n), 2) * 0.7 +
                   np.sin(2 * np.pi * 180 * np.arange(n) / SR)) * env(n, 0.001, 0.035) * v
            p = int(i * beat / 2 * SR)
            out[p:p + n] += hit
        i += 1
    return out * 0.5


def music(total):
    """Sombre drone score in D minor that darkens over time."""
    n = int(total * SR)
    t = np.arange(n) / SR
    chords = [(146.8, 174.6, 220.0), (116.5, 146.8, 174.6), (130.8, 164.8, 196.0),
              (110.0, 138.6, 164.8)]
    out = np.zeros(n)
    seg = 7.5
    for i in range(int(total / seg) + 1):
        a, b = int(i * seg * SR), min(n, int((i + 1) * seg * SR + SR))
        if a >= n:
            break
        tt = t[a:b] - t[a]
        fade = np.minimum(1, tt / 1.0) * np.minimum(1, (tt[-1] - tt) / 1.0 + 0.001)
        c = sum(np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2 * tt) for f in chords[i % 4])
        bass = np.sin(2 * np.pi * chords[i % 4][0] / 2 * tt)
        out[a:b] += (c * 0.12 + bass * 0.25) * fade
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.1 * t)
    return lowpass(out * lfo, 3) * 0.6


# ----------------------------------------------------------------------------
# AUDIO: real recordings from Wikimedia Commons (public domain / CC0 / CC BY)
# ----------------------------------------------------------------------------
ASSET_DIR = os.path.join(HERE, "assets")
ASSETS = {  # local name: Commons file name
    "siren.ogg": "Civil-defense-siren-waver.ogg",
    "explosion1.ogg": "Explosion-LS100155.ogg",
    "explosion2.ogg": "Explosion 10.ogg",
    "explosions.ogg": "Explosions-LS100150.ogg",
    "drums.ogg": "Militarydrumbeat.ogg",
    "applause.ogg": "Applause i.ogg",
    "gunshots.ogg": "Gunshots 8.ogg",
    "door.wav": "Slam closet door (Gravity Sound).wav",
    "typewriter.wav": "406243 stubb typewriter-ding-near-mono.wav",
    "chopin.ogg": "Frederic Chopin Piano Sonata No.2 in B flat minor Op35 - III Marche Funebre.ogg",
}


def fetch_assets():
    import hashlib
    import time
    import urllib.parse
    import urllib.request
    os.makedirs(ASSET_DIR, exist_ok=True)
    ua = {"User-Agent": "EduHistoryVideo/1.0 (educational video generator)"}
    for local, name in ASSETS.items():
        path = os.path.join(ASSET_DIR, local)
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            continue
        n = name.replace(" ", "_")
        h = hashlib.md5(n.encode()).hexdigest()
        url = f"https://upload.wikimedia.org/wikipedia/commons/{h[0]}/{h[:2]}/{urllib.parse.quote(n)}"
        for attempt in range(3):
            try:
                data = urllib.request.urlopen(urllib.request.Request(url, headers=ua),
                                              timeout=60).read()
                open(path, "wb").write(data)
                print(f"  downloaded {local}")
                break
            except Exception as e:
                print(f"  {local}: {e} (retrying)")
                time.sleep(10 * (attempt + 1))
        time.sleep(2)


def clip(local, start=0.0, dur=None, fade=0.05):
    """Load part of an asset as mono float array, peak-normalised. None if missing."""
    path = os.path.join(ASSET_DIR, local)
    if not os.path.exists(path):
        return None
    args = ["ffmpeg", "-v", "error", "-ss", str(start)]
    if dur:
        args += ["-t", str(dur)]
    args += ["-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"]
    try:
        x = np.frombuffer(subprocess.run(args, capture_output=True, check=True).stdout,
                          dtype=np.float32).astype(np.float64)
    except subprocess.CalledProcessError:
        return None
    if len(x) == 0:
        return None
    f = min(len(x) // 2, int(fade * SR))
    if f:
        x[:f] *= np.linspace(0, 1, f)
        x[-f:] *= np.linspace(1, 0, f)
    return x / (np.abs(x).max() + 1e-9)


def real_or(local, fallback, start=0.0, dur=None, fade=0.05):
    x = clip(local, start, dur, fade)
    return fallback() if x is None else x


def build_sfx():
    tr = np.zeros(int(TOTAL * SR) + SR * 5)

    def put(sec, x, g=1.0):
        s = int(sec * SR)
        e = min(len(tr), s + len(x))
        tr[s:e] += x[:e - s] * g

    S = STARTS
    boom1 = lambda: real_or("explosion1.ogg", sfx_explosion)
    boom2 = lambda: real_or("explosion2.ogg", sfx_explosion)
    put(0.0, sfx_whoosh(1.2), .5)
    put(0.2, sfx_bell(3), .25)
    put(S[1] + 0.1, sfx_whoosh(), .4)
    put(S[1] + 1.2, real_or("typewriter.wav", sfx_typewriter), .25)
    put(S[1] + 2.6, sfx_stamp(), .9)
    put(S[1] + 4.5, sfx_whoosh(), .4)
    for k, et in enumerate((0.4, 1.6, 3.0, 3.9)):
        put(S[1] + 4.6 + et, boom1() if k % 2 else boom2(), .7)
    gun = clip("gunshots.ogg", 0, 4.5, 0.2)
    if gun is not None:
        put(S[1] + 4.8, gun, .35)
    else:
        for k in range(14):
            put(S[1] + 4.8 + k * 0.33 + rng.uniform(0, .1), sfx_gunshot(), .25)
    put(S[2], sfx_crowd(SCENES[2][0]), .12)
    put(S[2], real_or("drums.ogg", lambda: sfx_drums(SCENES[2][0]), 0, SCENES[2][0], 0.6), .3)
    put(S[2] + 3.0, real_or("applause.ogg", lambda: sfx_cheer(2.5), 1.0, 3.0, 0.6), .3)
    put(S[2] + 7.0, real_or("applause.ogg", lambda: sfx_cheer(2.5), 6.0, 3.0, 0.6), .3)
    for k in range(3):
        put(S[3] + k * 0.6, sfx_flip(), .9)
    put(S[3] + 1.8, sfx_typewriter(), .5)
    for k in range(3):
        put(S[3] + 2.4 + 1.0 + k, sfx_stamp(), .8)
    put(S[4], real_or("siren.ogg", lambda: sfx_siren(4.5), 2.0, 5.0, 1.0), .4)
    put(S[4], sfx_planes(SCENES[4][0]), .6)
    many = clip("explosions.ogg")
    if many is not None:
        put(S[4] + 1.1, many, .45)
        put(S[4] + 5.0, boom1(), .45)
    else:
        for ts in (1.2, 2.4, 2.8, 3.3, 3.8, 5.0):
            put(S[4] + ts, sfx_explosion(1.4), .35)
    put(S[5] + 0.2, sfx_bell(5), .2)
    put(S[6], sfx_whoosh(1.2), .3)
    put(S[6] + 0.5, boom2(), .3)
    put(S[6] + 3.35, real_or("door.wav", sfx_door), .8)
    put(S[6] + 4.6, sfx_bell(4), .4)
    return tr[:int(TOTAL * SR)]


def score(total):
    """Chopin's Funeral March (CC0 recording); synthesized drone if unavailable."""
    x = clip("chopin.ogg", 0.0, total, 2.0)
    if x is None:
        return music(total)
    x = np.pad(x, (0, max(0, int(total * SR) - len(x))))[:int(total * SR)]
    # quieter under the busy war scenes, fuller for the Holocaust + ending
    t = np.arange(len(x)) / SR
    g = np.interp(t, [0, STARTS[1], STARTS[5] - 1, STARTS[5], TOTAL],
                  [0.55, 0.4, 0.4, 0.8, 0.8])
    return x * g


def write_wav(path, x, ch=1):
    x = np.clip(x, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


# ----------------------------------------------------------------------------
# VIDEO
# ----------------------------------------------------------------------------
def make_vignette():
    v = Image.new("L", (W, H), 0)
    ImageDraw.Draw(v).ellipse([-200, -150, W + 200, H + 150], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(120))
    grain = Image.effect_noise((W, H), 18).convert("L")
    return v, grain


def render(narr, out_mp4, audio_wav):
    vig, grain = make_vignette()
    dark = Image.new("RGB", (W, H), (10, 6, 4))
    # mouth envelope for the narrator from narration loudness
    hop = SR // FPS
    mouth = np.array([np.sqrt(np.mean(narr[i * hop:(i + 1) * hop] ** 2)) for i in range(NFRAMES)])
    mouth = np.clip(mouth / (np.percentile(mouth, 95) + 1e-9), 0, 1)

    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", audio_wav,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
           "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(NFRAMES):
        gt = f / FPS
        i = int(np.searchsorted(STARTS, gt, side="right") - 1)
        t = gt - STARTS[i]
        dur, text, label = SCENES[i]
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        # camera shake during explosions
        DRAW[i](img, d, t, dur)
        img = img.convert("RGB")
        if i in (1, 4) and (i == 4 or t > 4.6):
            sh = int(4 * abs(math.sin(gt * 37)))
            img = img.transform(img.size, Image.AFFINE, (1, 0, sh - 2, 0, 1, sh // 2 - 1))
        # film look: sepia-ish grain + vignette
        img = Image.composite(img, dark, vig.point(lambda v: 90 + v * 165 // 255))
        img = Image.blend(img, Image.merge("RGB", (grain, grain, grain)), 0.05)
        img = img.convert("RGBA")
        draw_narrator(img, mouth[f], gt)
        d = ImageDraw.Draw(img)
        if label:
            d.rounded_rectangle([20, H - 175, 30 + d.textlength(label, font=F_LABEL) + 20, H - 135],
                                radius=8, fill=(30, 20, 15))
            d.text((35, H - 171), label, font=F_LABEL, fill=(240, 210, 150))
        # subtitles
        lines = wrap(d, text, F_CAP, W - 160)
        for li, ln in enumerate(lines):
            ctext(d, (W / 2, H - 95 + li * 36 - (len(lines) - 1) * 18), ln, F_CAP,
                  (255, 255, 255), 3, (0, 0, 0))
        # scene fade in/out
        fade = min(1, t / 0.35, (dur - t) / 0.35)
        img = img.convert("RGB")
        if fade < 1:
            img = Image.blend(Image.new("RGB", (W, H)), img, max(0, fade))
        p.stdin.write(img.tobytes())
        if f % FPS == 0:
            print(f"\r  rendering {gt:4.0f}s / {TOTAL:.0f}s", end="", flush=True)
    p.stdin.close()
    p.wait()
    print()


def main():
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is required (https://ffmpeg.org/download.html)")
    out = os.path.join(HERE, OUT) if len(sys.argv) < 2 else sys.argv[1]
    with tempfile.TemporaryDirectory() as tmp:
        print("0/3 Fetching sound assets (Wikimedia Commons) ...")
        fetch_assets()
        print("1/3 Generating narration ...")
        narr = build_narration(tmp)[:int(TOTAL * SR)]
        print("2/3 Synthesizing sound effects + music ...")
        mix = narr * 1.0 + build_sfx() * 0.55 + score(TOTAL) * 0.35
        # duck sfx/music under the voice a little, then normalise
        mix = mix / (np.abs(mix).max() + 1e-9) * 0.95
        stereo = np.repeat(mix[:, None], 2, axis=1).reshape(-1)
        wav = os.path.join(tmp, "mix.wav")
        write_wav(wav, stereo, ch=2)
        print("3/3 Rendering animation ...")
        render(narr, out, wav)
    print("Done ->", out)


if __name__ == "__main__":
    main()
