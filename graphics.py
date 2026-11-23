"""گرافیک بازی غفون — کارت‌ها، دست بازیکن، میز بازی، جدول و بنرها.

نکته: ایموجی‌ها در تصاویر پی ال نشان داده نمی‌شوند، بنابراین هر متن قبل از رسم
پاک‌سازی می‌شود و به جای آن‌ها از اشکال رسم‌شده استفاده می‌کنیم.
"""
from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from engine import (SUITS, SUIT_SYMBOLS, SUIT_COLORS, RANK_LABEL, RANK_NAMES,
                    card_suit, card_rank, card_name, TEAM_NAMES, TEAM_COLORS, TEAM_EMOJI)

BASE = os.path.dirname(os.path.abspath(__file__))
FDIR = os.path.join(BASE, "fonts")
_cache: dict = {}

FELT_TOP = (20, 124, 86)
FELT_BOT = (5, 54, 36)
DARK_TOP = (38, 33, 96)
DARK_BOT = (11, 15, 32)


def font(weight: str = "Regular", size: int = 40) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(os.path.join(FDIR, f"Vazirmatn-{weight}.ttf"), size)
    return _cache[key]


def rtl(text) -> str:
    return get_display(arabic_reshaper.reshape(clean(text)))


def clean(text) -> str:
    """حذف ایموجی‌ها و نویسه‌های خارج از BMP تا در تصویر تیکه نایند."""
    return "".join(ch for ch in str(text) if ord(ch) <= 0xFFFF)


FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(x) -> str:
    return str(x).translate(FA)


def hex_rgba(h: str, a: int = 255):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def gradient(size, top, bottom) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def text(d: ImageDraw.ImageDraw, xy, s, f, fill, anchor: str = "mm"):
    d.text(xy, rtl(s), font=f, fill=fill, anchor=anchor)


def draw_suit(d: ImageDraw.ImageDraw, suit: int, cx: float, cy: float, s: float, color):
    """رسم خال ورق (پیک/دل/خشت/گشنیز)"""
    if suit == 1:  # دل
        r = s * 0.25
        d.ellipse([cx - 0.22 * s - r, cy - 0.15 * s - r, cx - 0.22 * s + r, cy - 0.15 * s + r], fill=color)
        d.ellipse([cx + 0.22 * s - r, cy - 0.15 * s - r, cx + 0.22 * s + r, cy - 0.15 * s + r], fill=color)
        d.polygon([(cx - 0.44 * s, cy - 0.10 * s), (cx + 0.44 * s, cy - 0.10 * s), (cx, cy + 0.50 * s)], fill=color)
    elif suit == 2:  # خشت
        d.polygon([(cx, cy - 0.50 * s), (cx + 0.32 * s, cy), (cx, cy + 0.50 * s), (cx - 0.32 * s, cy)], fill=color)
    elif suit == 0:  # پیک
        r = s * 0.22
        d.ellipse([cx - 0.20 * s - r, cy + 0.08 * s - r, cx - 0.20 * s + r, cy + 0.08 * s + r], fill=color)
        d.ellipse([cx + 0.20 * s - r, cy + 0.08 * s - r, cx + 0.20 * s + r, cy + 0.08 * s + r], fill=color)
        d.polygon([(cx - 0.40 * s, cy + 0.12 * s), (cx + 0.40 * s, cy + 0.12 * s), (cx, cy - 0.45 * s)], fill=color)
        d.polygon([(cx - 0.06 * s, cy + 0.25 * s), (cx + 0.06 * s, cy + 0.25 * s),
                   (cx + 0.13 * s, cy + 0.50 * s), (cx - 0.13 * s, cy + 0.50 * s)], fill=color)
    else:  # گشنیز
        r = s * 0.20
        d.ellipse([cx - r, cy - 0.18 * s - r, cx + r, cy - 0.18 * s + r], fill=color)
        d.ellipse([cx - 0.20 * s - r, cy + 0.08 * s - r, cx - 0.20 * s + r, cy + 0.08 * s + r], fill=color)
        d.ellipse([cx + 0.20 * s - r, cy + 0.08 * s - r, cx + 0.20 * s + r, cy + 0.08 * s + r], fill=color)
        d.polygon([(cx - 0.05 * s, cy + 0.20 * s), (cx + 0.05 * s, cy + 0.20 * s),
                   (cx + 0.13 * s, cy + 0.50 * s), (cx - 0.13 * s, cy + 0.50 * s)], fill=color)


def draw_star(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    d.polygon(pts, fill=color)


def make_card(card: int, w: int = 200, h: int = 280) -> Image.Image:
    """ساخت تصویر یک کارت (RGBA)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 6, w, h + 2], radius=int(w * 0.09), fill=(0, 0, 0, 70))
    d.rounded_rectangle([0, 0, w - 4, h - 4], radius=int(w * 0.09),
                        fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=2)
    d.rounded_rectangle([6, 6, w - 10, h - 10], radius=int(w * 0.075),
                        outline=(241, 245, 249, 255), width=2)
    suit = card_suit(card)
    rank = card_rank(card)
    color = SUIT_COLORS[suit]
    label = RANK_LABEL[rank]
    if rank >= 11:  # کارت‌های تصویر: پنل رنگی پشت خال
        d.rounded_rectangle([int(w * 0.26), int(h * 0.28), int(w * 0.74), int(h * 0.76)],
                            radius=16, fill=hex_rgba(color, 30))
    d.text((w * 0.12, h * 0.075), label, font=font("Black", int(w * 0.24)), fill=color, anchor="mm")
    draw_suit(d, suit, w * 0.135, h * 0.235, w * 0.15, color)
    draw_suit(d, suit, w * 0.5, h * 0.55, w * 0.34, color)
    small = Image.new("RGBA", (int(w * 0.3), int(w * 0.3)), (0, 0, 0, 0))
    sd = ImageDraw.Draw(small)
    sd.text((small.width / 2, small.height / 2), label, font=font("Black", int(w * 0.22)),
            fill=color, anchor="mm")
    small = small.rotate(180)
    img.alpha_composite(small, (int(w * 0.66), int(h * 0.72)))
    return img


def paste_card(canvas: Image.Image, card_img: Image.Image, x: float, y: float,
               dim: bool = False, glow: bool = False):
    if glow:
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle([x - 7, y - 7, x + card_img.width + 7, y + card_img.height + 7],
                            radius=24, outline=(74, 222, 128, 255), width=5)
    if dim:
        overlay = card_img.copy()
        alpha = overlay.split()[3].point(lambda a: int(a * 0.4))
        overlay.putalpha(alpha)
        card_img = overlay
    canvas.alpha_composite(card_img, (int(x), int(y)))


def make_hand_image(hand, playable, is_turn: bool, title: str) -> Image.Image:
    """دست بازیکن: ۱۳ کارت در دو ردیف؛ کارت‌های قابل‌بازی روشن، بقیه کم‌رنگ."""
    W, H = 1440, 800
    img = gradient((W, H), FELT_TOP, FELT_BOT).convert("RGBA")
    d = ImageDraw.Draw(img)
    for _ in range(10):
        x = random.randint(-80, W)
        y = random.randint(-80, H)
        r = random.randint(50, 170)
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255, 10), width=2)
    # نوار عنوان
    d.rounded_rectangle([0, 0, W, 84], radius=0, fill=(0, 0, 0, 70))
    text(d, (W / 2, 44), title, font("Bold", 42), (255, 255, 255, 240))
    cw, ch = 188, 264
    overlap = 24
    rows = [hand[:7], hand[7:]]
    y0 = 104
    row_gap = 46
    playable_set = set(playable)
    for ri, row in enumerate(rows):
        if not row:
            continue
        n = len(row)
        row_w = n * cw - (n - 1) * overlap
        x = (W - row_w) / 2
        y = y0 + ri * (ch + row_gap)
        for c in row:
            paste_card(img, make_card(c, cw, ch), x, y,
                       dim=(c not in playable_set),
                       glow=(is_turn and c in playable_set))
            x += cw - overlap
    # قاب تزئینی
    d.rounded_rectangle([10, 96, W - 10, H - 10], radius=28,
                        outline=(255, 255, 255, 26), width=2)
    return img.convert("RGB")


def _seat_pos(seat: int, W: int, H: int):
    return {0: (W / 2, 185), 1: (W - 215, H / 2), 2: (W / 2, H - 185), 3: (215, H / 2)}[seat]


def make_table_image(room, names) -> Image.Image:
    """میز بازی: کارت‌های روی میز، خال حکم، امتیازات و نوبت."""
    W, H = 1280, 840
    img = gradient((W, H), FELT_TOP, FELT_BOT).convert("RGBA")
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x = random.randint(-80, W)
        y = random.randint(-80, H)
        r = random.randint(60, 200)
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255, 8), width=2)
    # قاب میز
    d.rounded_rectangle([8, 8, W - 8, H - 8], radius=34, outline=(255, 255, 255, 30), width=3)
    # هدر امتیازات
    for i, (team, col) in enumerate(zip(TEAM_NAMES, TEAM_COLORS)):
        x = 40 if i == 0 else W - 40 - 380
        d.rounded_rectangle([x, 22, x + 380, 80], radius=26, fill=hex_rgba(col, 235))
        d.ellipse([x + 20, 40, x + 48, 68], fill=(255, 255, 255, 235))
        text(d, (x + 205, 51), f"{team}: {fa(room.scores[i])}", font("Bold", 30), "white")
    cw, ch = 148, 208
    for seat in range(4):
        px, py = _seat_pos(seat, W, H)
        name = names.get(seat, "؟")
        if room.turn == seat and room.state == "play":
            d.rounded_rectangle([px - cw / 2 - 12, py - ch / 2 - 12, px + cw / 2 + 12, py + ch / 2 + 12],
                                radius=26, outline=(74, 222, 128, 255), width=6)
        label = f"{name} | {fa(len(room.hands[seat]))}"
        text(d, (px, py - ch / 2 - 34), label, font("Medium", 26), (255, 255, 255, 235))
        played = next((c for s, c in room.played if s == seat), None)
        if played is not None:
            paste_card(img, make_card(played, cw, ch), px - cw / 2, py - ch / 2)
        else:
            d.rounded_rectangle([px - cw / 2, py - ch / 2, px + cw / 2, py + ch / 2],
                                radius=18, outline=(255, 255, 255, 60), width=3)
    cx, cy = W / 2, H / 2
    d.ellipse([cx - 122, cy - 122, cx + 122, cy + 122], fill=(0, 0, 0, 110),
              outline=(255, 255, 255, 70), width=3)
    if room.state in ("play", "round_end") and room.trump is not None:
        draw_suit(d, room.trump, cx, cy - 30, 92, "#fbbf24")
        text(d, (cx, cy + 50), f"حکم: {SUITS[room.trump]}", font("Bold", 30), "white")
        text(d, (cx, cy + 92), f"اعلام حاکم: {fa(room.bid_value)}", font("Medium", 24), (255, 220, 150))
    else:
        text(d, (cx, cy - 12), "مرحله اعلام دست", font("Bold", 34), "white")
        if room.bid_max:
            text(d, (cx, cy + 40), f"بیشترین بید: {fa(room.bid_max)}", font("Medium", 26), (255, 220, 150))
    text(d, (W / 2, H - 32),
         f"دور {fa(room.round_no)}  |  دست‌ها: {fa(room.tricks[0])} - {fa(room.tricks[1])}",
         font("Medium", 24), (255, 255, 255, 205))
    return img.convert("RGB")


def make_result_image(room, names, res) -> Image.Image:
    team, y, x, ok = res
    W, H = 1000, 560
    img = gradient((W, H), DARK_TOP, DARK_BOT).convert("RGBA")
    d = ImageDraw.Draw(img)
    for gx, gy, gr, col in [(90, 90, 220, (139, 92, 246, 30)), (930, 480, 240, (34, 211, 238, 22))]:
        d.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=col)
    text(d, (W / 2, 70), f"پایان دور {fa(room.round_no)}", font("Black", 52), "white")
    col = TEAM_COLORS[team]
    d.rounded_rectangle([W / 2 - 330, 128, W / 2 + 330, 250], radius=28, fill=hex_rgba(col, 240))
    d.ellipse([W / 2 - 300, 166, W / 2 - 262, 212], fill=(255, 255, 255, 235))
    text(d, (W / 2 + 16, 190), TEAM_NAMES[team], font("Bold", 40), "white", anchor="mm")
    text(d, (W / 2, 300), f"اعلام حاکم: {fa(x)}   |   دست‌های گرفته‌شده: {fa(y)}",
         font("Medium", 32), (255, 220, 150))
    if ok:
        text(d, (W / 2, 362), f"+{fa(y)} امتیاز", font("Black", 44), (74, 222, 128))
    else:
        text(d, (W / 2, 362), f"تیم حریف +{fa(2 * x)} امتیاز (۲×اعلام)", font("Black", 40), (248, 113, 113))
    text(d, (W / 2, 462), f"{fa(room.scores[0])}  —  {fa(room.scores[1])}",
         font("Bold", 38), "white")
    return img.convert("RGB")


def make_lobby_banner() -> Image.Image:
    W, H = 1000, 560
    img = gradient((W, H), DARK_TOP, DARK_BOT).convert("RGBA")
    d = ImageDraw.Draw(img)
    for gx, gy, gr, col in [(120, 120, 240, (139, 92, 246, 34)), (900, 470, 260, (34, 211, 238, 24))]:
        d.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=col)
    deco = [make_card(0, 150, 210), make_card(13, 150, 210), make_card(27, 150, 210), make_card(40, 150, 210)]
    for i, c in enumerate(deco):
        c = c.rotate([-18, -6, 6, 18][i], expand=True)
        paste_card(img, c, 90 + i * 250, 300)
    text(d, (W / 2, 118), "بازی غفون", font("Black", 96), "white")
    text(d, (W / 2, 208), "حکم با اعلام دست — ۴ نفره", font("Bold", 40), (255, 220, 150))
    text(d, (W / 2, 480), "در گروه تلگرام، همراه دوستانتان", font("Medium", 28), (205, 210, 230))
    return img.convert("RGB")


def make_winner(team: int, scores) -> Image.Image:
    W, H = 1000, 600
    img = gradient((W, H), DARK_TOP, DARK_BOT).convert("RGBA")
    d = ImageDraw.Draw(img)
    random.seed(7)
    for _ in range(70):
        x = random.randint(0, W)
        y = random.randint(0, H)
        r = random.randint(3, 9)
        col = random.choice(["#fbbf24", "#34d399", "#60a5fa", "#f472b6", "#f87171"])
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    draw_star(d, W / 2, 120, 62, "#fbbf24")
    col = TEAM_COLORS[team]
    d.rounded_rectangle([W / 2 - 340, 200, W / 2 + 340, 330], radius=30, fill=hex_rgba(col, 240))
    d.ellipse([W / 2 - 310, 240, W / 2 - 268, 292], fill=(255, 255, 255, 235))
    text(d, (W / 2 + 16, 266), f"{TEAM_NAMES[team]} برنده شد!", font("Black", 50), "white")
    text(d, (W / 2, 400), f"امتیاز نهایی: {fa(scores[0])} — {fa(scores[1])}",
         font("Bold", 40), (255, 220, 150))
    return img.convert("RGB")
