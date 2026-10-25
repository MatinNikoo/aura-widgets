"""
Aura Clock  a rounded desktop card with 3D liquid chrome time, the date,
a 3D chrome star that shines now and then, and a few tiny twinkling stars.
Right click for options. Drag it anywhere.

Needs the fonts folder next to this file (Unbounded, SIL Open Font License).
"""
import sys, os, tempfile, datetime, math, random, time, logging

from PIL import Image, ImageDraw, ImageFont
from PyQt6.QtCore import Qt, QRectF, QPointF, QPoint, QLockFile, QTimer, QSize, QLocale, QDate, QCalendar
from PyQt6.QtGui import (QPainter, QColor, QImage, QPainterPath, QLinearGradient, QFont, QFontMetricsF,
                         QFontDatabase, QImageReader, QRadialGradient, QAction, QPen)

import aura_common
from aura_common import fullscreen_app_open
from aura_draw import shape_path, shadow_pil, draw_border, inset, GifPlayer, render

try:
    import numpy as np
except ImportError:          # still works without numpy, just with flatter chrome
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))
# the font can sit in a fonts folder or right next to this file, either works
FONT_SPOTS = [os.path.join(HERE, "fonts", "Unbounded.ttf"), os.path.join(HERE, "Unbounded.ttf")]

W, H = 400, 132          # same size as the music card so they stack neatly
M = 26
RADIUS = 26
PAD = 30                 # left edge that the time and the date both line up on
S = 3                    # render detail, high enough to stay sharp at the Large size
RUN_NAME = "AuraClockWidget"

TIME_TOP = 30            # top of the digits
TIME_H = 45              # height of the digits
STRETCH = 1.18           # makes the wide letters a bit taller
DATE_TOP = 89
TEXT_MAX_W = 246         # room for the time before the star

STAR_C = (W - 64, H / 2)
STAR_RV, STAR_RH = 35, 25
SHINE_TIME = 2.2
TWINKLE_TIME = 1.6

# tiny stars: x, y, size, kind
TINY = [
    (252, 20, 3.2, "star"), (378, 22, 3.4, "star"), (292, 112, 2.6, "star"),
    (374, 110, 2.0, "dot"), (296, 32, 1.8, "dot"), (282, 88, 1.6, "dot"),
    (218, 114, 2.0, "dot"), (21, 21, 1.6, "dot"), (150, 16, 1.8, "dot"),
]


# ---------------------------------------------------------------- image helpers
def pil_to_qimage(im, dpr=1):
    im = im.convert("RGBA")
    q = QImage(im.tobytes("raw", "RGBA"), im.width, im.height, im.width * 4,
               QImage.Format.Format_RGBA8888).copy()
    q = q.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)    # drawn every frame, convert once
    q.setDevicePixelRatio(dpr)
    return q


def rounded(rect, r):
    p = QPainterPath()
    p.addRoundedRect(rect, r, r)
    return p


def load_font(size, weight):
    for path in FONT_SPOTS + [r"C:\Windows\Fonts\segoeuib.ttf"]:
        try:
            f = ImageFont.truetype(path, size)
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
            return f
        except OSError:
            continue
    return ImageFont.load_default(size)


# ---------------------------------------------------------------- 3D liquid chrome
RAMP = [(-1.0, (236, 238, 243)), (-0.45, (160, 164, 173)), (-0.12, (62, 64, 72)), (0.0, (24, 25, 30)),
        (0.10, (92, 96, 106)), (0.35, (205, 209, 218)), (0.7, (246, 247, 250)), (1.0, (255, 255, 255))]


def blur(a, r):
    """Smooth gaussian blur in floating point, done with an FFT so it's quick
    (8 bit blurs leave ripples in the shading)."""
    r = max(0.5, float(r))
    rad = int(r * 3 + 1)
    a = np.pad(a.astype(np.float32), rad)
    fy = np.fft.fftfreq(a.shape[0])[:, None]
    fx = np.fft.rfftfreq(a.shape[1])[None, :]
    g = np.exp(-2 * (math.pi * r) ** 2 * (fx * fx + fy * fy))
    out = np.fft.irfft2(np.fft.rfft2(a) * g, s=a.shape)
    return out[rad:-rad, rad:-rad].astype(np.float32)


def chrome(mask_img, thick, strength=1.4, bias=0.25):
    """Turns a white on black shape into 3D liquid chrome.
    The shape is inflated into a height map, and each pixel's slope decides which part of a
    bright sky, dark horizon and grey floor it reflects, plus a sharp highlight from the top left."""
    if np is None:
        g = Image.linear_gradient("L").resize(mask_img.size).point(lambda v: 255 - v // 2)
        return Image.merge("RGBA", (g, g, g, mask_img))
    mask = np.asarray(mask_img, dtype=np.float32) / 255
    h = 0.45 * blur(mask, thick * 0.35) + 0.35 * blur(mask, thick * 0.7) + 0.2 * blur(mask, thick * 1.2)
    h = h * (0.35 + 0.65 * blur(mask, thick * 0.2))
    gy, gx = np.gradient(h)
    k = strength * thick * 3.2
    nx, ny, nz = -gx * k, -gy * k, np.ones_like(h)
    n = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / n, ny / n, nz / n
    rx, ry, rz = 2 * nz * nx, 2 * nz * ny, 2 * nz * nz - 1
    u = np.clip(-ry + bias - 0.15 * rx, -1, 1)
    ru = np.array([p[0] for p in RAMP])
    rc = np.array([p[1] for p in RAMP], dtype=np.float32)
    col = np.stack([np.interp(u, ru, rc[:, i]) for i in range(3)], -1)
    L = np.array([-0.45, -0.75, 0.5])
    L = L / np.linalg.norm(L)
    spec = np.clip(rx * L[0] + ry * L[1] + rz * L[2], 0, 1) ** 28
    col = col + spec[..., None] * 230
    edge = blur(mask, max(1, thick * 0.12))
    col = col * (0.5 + 0.5 * np.clip(edge * 1.6 - 0.3, 0, 1))[..., None]
    col[..., 2] *= 1.03
    out = np.dstack([np.clip(col, 0, 255), mask * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def star_points(cx, cy, rv, rh, k, steps=40):
    """Outline of a four point star with pinched sides."""
    P = [(cx, cy - rv), (cx + rh, cy), (cx, cy + rv), (cx - rh, cy)]
    C = [((cx + k * .4, cy - k * 2.2), (cx + k * 2.2, cy - k * .4)), ((cx + k * 2.2, cy + k * .4), (cx + k * .4, cy + k * 2.2)),
         ((cx - k * .4, cy + k * 2.2), (cx - k * 2.2, cy + k * .4)), ((cx - k * 2.2, cy - k * .4), (cx - k * .4, cy - k * 2.2))]
    pts = []
    for i in range(4):
        p0, (p1, p2), p3 = P[i], C[i], P[(i + 1) % 4]
        for j in range(steps):
            t = j / steps
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def star_path(cx, cy, rv, rh, k):
    p = QPainterPath()
    pts = star_points(cx, cy, rv, rh, k, 12)
    p.moveTo(*pts[0])
    for pt in pts[1:]:
        p.lineTo(*pt)
    p.closeSubpath()
    return p


def pulse(t):
    return math.sin(math.pi * max(0.0, min(1.0, t))) ** 2


def ms_to_next_tick(now, seconds):
    """How long until the shown time changes, plus a little so we land just past the change."""
    if seconds:
        wait = 1000 - now.microsecond // 1000
    else:
        wait = (60 - now.second) * 1000 - now.microsecond // 1000
    return max(50, wait + 20)


# ---------------------------------------------------------------- text as chrome glyphs
def flat(mask_img):
    """The plain look: soft white letters with a light top to bottom fade, no chrome."""
    g = Image.linear_gradient("L").resize(mask_img.size).point(lambda v: 255 - v // 7)
    return Image.merge("RGBA", (g, g, g, mask_img))


def qt_font(family, px, weight):
    f = QFont(family)
    f.setPixelSize(max(1, int(px)))
    f.setWeight(QFont.Weight(weight))
    return f


def qt_mask(text, font, w, h, x, baseline):
    """White text on black, drawn by Qt, so any installed font and any script works."""
    img = QImage(w, h, QImage.Format.Format_Grayscale8)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(font)
    p.setPen(QColor(255, 255, 255))
    p.drawText(QPointF(x, baseline), text)
    p.end()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return Image.frombuffer("L", (w, h), bytes(ptr), "raw", "L", img.bytesPerLine(), 1).copy()


class Glyphs:
    """Each character is turned into chrome once and reused, so updating the time is instant."""

    def __init__(self, px_size, weight, thick, stretch, family="", style="chrome"):
        self.family, self.style = family, style
        if family:
            self.qfont = qt_font(family, px_size * S, weight)
            self.font = None
        else:
            self.font = load_font(int(px_size * S), weight)
        self.thick, self.stretch = thick, stretch
        self.cache = {}

    def get(self, ch):
        if ch not in self.cache:
            pad = int(self.thick * 2 + 4)
            if self.font is not None:
                f = self.font
                asc, desc = f.getmetrics()
                adv = f.getlength(ch)
                wpx, hpx = int(adv + 2 * pad), int(asc + desc + 2 * pad)
                m = Image.new("L", (wpx, hpx), 0)
                ImageDraw.Draw(m).text((pad, pad + asc), ch, font=f, fill=255, anchor="ls")
            else:
                fm = QFontMetricsF(self.qfont)
                asc, desc, adv = fm.ascent(), fm.descent(), fm.horizontalAdvance(ch)
                wpx, hpx = int(adv + 2 * pad), int(asc + desc + 2 * pad)
                m = qt_mask(ch, self.qfont, max(1, wpx), max(1, hpx), pad, pad + asc)
            m = m.resize((wpx, int(hpx * self.stretch)), Image.Resampling.LANCZOS)
            if not ch.strip():
                img = m.convert("RGBA")
            else:
                img = chrome(m, self.thick) if self.style == "chrome" else flat(m)
            box = m.getbbox() or (pad, pad, pad, pad)
            self.cache[ch] = {
                "img": pil_to_qimage(img, S),
                "ox": pad / S, "oy": (pad + asc) * self.stretch / S,      # pen origin inside the image
                "adv": adv / S,
                "ink_l": (box[0] - pad) / S,
                "ink_t": (box[1] - (pad + asc) * self.stretch) / S,       # negative, above the baseline
            }
        return self.cache[ch]

    def width(self, text, tracking=0.0):
        return sum(self.get(c)["adv"] for c in text) + tracking * max(0, len(text) - 1)

    def draw(self, p, text, x, baseline, tracking=0.0):
        for c in text:
            g = self.get(c)
            p.drawImage(QPointF(x - g["ox"], baseline - g["oy"]), g["img"])
            x += g["adv"] + tracking


# ---------------------------------------------------------------- the card
CIRCLE = 200             # the round clock is this wide

# tiny stars on the round clock, kept off the text in the middle
TINY_ROUND = [
    (64, 46, 3.0, "star"), (138, 36, 2.6, "star"), (101, 24, 1.8, "dot"), (166, 64, 1.6, "dot"),
    (32, 84, 1.6, "dot"), (70, 170, 2.4, "star"), (130, 176, 1.8, "dot"), (162, 148, 1.6, "dot"),
]

DATE_PATTERNS = {"weekday": "dddd, MMMM d", "full": "dddd, MMMM d, yyyy", "short": "MMM d", "iso": "yyyy-MM-dd"}


class ClockCard:
    def __init__(self):
        self.h24 = False
        self.seconds = False
        self.shape, self.radius, self.border = "rounded", RADIUS, "thin"
        self.style, self.family, self.time_size = "chrome", "", 100
        self.face = "digital"
        self.date_kind, self.locale, self.lowercase = "weekday", "", True
        self.dim = 45
        self.background = None   # current frame of the background GIF or image, already fitted to the card
        self.show_shadow = True
        self.effects = {}
        self.star_img, self.star_glow = self._star()
        self.build()

    def build(self):
        """Everything that depends on the look settings."""
        k = self.time_size / 100
        digit_px = TIME_H * k / (0.77 * STRETCH)     # font size that makes the digits TIME_H tall
        self.big = Glyphs(digit_px, 700, thick=11 * S * digit_px / 48, stretch=STRETCH,
                          family=self.family, style=self.style)
        self.small = Glyphs(digit_px * 0.36, 700, thick=4.5 * S * digit_px / 48, stretch=STRETCH,
                            family=self.family, style=self.style)
        self.date_font = load_font(int(11.5 * S), 300)
        self.date_cache = (None, None)
        self.shadow = self._shadow()
        self.base = self._base()

    def apply(self, o):
        """Settings from the settings file (see aura_common.SCHEMA)."""
        self.h24, self.seconds = o["h24"], o["seconds"]
        look = (o["shape"], o["radius"], o["border"], o["style"], o["font"], o["time_size"], o["background"] != "",
                o.get("face", "digital"))
        now = (self.shape, self.radius, self.border, self.style, self.family, self.time_size,
               getattr(self, "bg_on", False), self.face)
        self.date_kind, self.locale, self.lowercase = o["date"], o["locale"], o["lowercase"]
        self.dim = o["background_dim"]
        self.show_shadow = o["shadow"]
        self.date_cache = (None, None)
        if look != now:
            self.shape, self.radius, self.border, self.style, self.family, self.time_size, self.bg_on, self.face = look
            if not self.bg_on:
                self.background = None
            self.effects = {}
            self.build()

    @property
    def round(self):
        return self.shape == "circle"

    @property
    def size(self):
        return (CIRCLE, CIRCLE) if self.round else (W, H)

    @property
    def tiny(self):
        return TINY_ROUND if self.round else TINY

    # drawn once
    def _shadow(self):
        s = 2
        w, h = self.size
        return pil_to_qimage(shadow_pil(w, h, M, self.shape, self.radius, 130, s), s)

    def _star(self):
        pad = 14
        wpx, hpx = int((STAR_RH + pad) * 2 * S), int((STAR_RV + pad) * 2 * S)
        ss = 4
        big = Image.new("L", (wpx * ss, hpx * ss), 0)
        ImageDraw.Draw(big).polygon(
            star_points(wpx * ss / 2, hpx * ss / 2, STAR_RV * S * ss, STAR_RH * S * ss, 6.5 * S * ss), fill=255)
        mask = big.resize((wpx, hpx), Image.Resampling.LANCZOS)
        img = chrome(mask, thick=20 * S, strength=2.4, bias=0.15)
        white = Image.new("L", mask.size, 255)
        glow = Image.merge("RGBA", (white, white, white, mask))
        return pil_to_qimage(img, S), pil_to_qimage(glow, S)

    def star_rect_img(self):
        w = self.star_img.width() / S
        h = self.star_img.height() / S
        return QRectF(STAR_C[0] - w / 2, STAR_C[1] - h / 2, w, h)

    def card_path(self):
        w, h = self.size
        return shape_path(self.shape, QRectF(0, 0, w, h), self.radius)

    def _base(self):
        w, h = self.size
        img = QImage(w * S, h * S, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(S)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not getattr(self, "bg_on", False):     # with a background, the fill is drawn under it instead
            p.fillPath(self.card_path(), self.fill())
        draw_border(p, self.border, self.shape, w, h, self.radius, thin_alpha=22)
        if (self.shape, self.radius) != ("rounded", RADIUS):
            p.setClipPath(self.card_path())          # keep the little stars inside other shapes
        for i in range(len(self.tiny)):
            self.draw_tiny(p, i, 0.0)
        if not self.round:
            self.draw_halo(p, 0.0)
            p.drawImage(self.star_rect_img(), self.star_img)
        if self.face == "analog":
            self.draw_dial(p)
        p.end()
        return img

    def fill(self):
        g = QLinearGradient(0, 0, 0, self.size[1])
        g.setColorAt(0, QColor(13, 13, 15))
        g.setColorAt(1, QColor(4, 4, 5))
        return g

    def set_background(self, img):
        """Fit a background frame to the card once, so drawing it later is just a copy."""
        if img is None or img.isNull():
            self.background = None
            return
        w, h = self.size
        scaled = img.scaled(QSize(w * 2, h * 2), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(2)
        self.background = scaled

    # stars
    def draw_halo(self, p, shine):
        cx, cy = STAR_C
        r = STAR_RV * 1.15
        halo = QRadialGradient(cx, cy, r)
        halo.setColorAt(0, QColor(255, 255, 255, int(24 + 30 * shine)))
        halo.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), r, r)

    def draw_shine(self, p, shine):
        """The main star never moves; it just glows brighter and fades back."""
        self.draw_halo(p, shine)
        p.drawImage(self.star_rect_img(), self.star_img)
        p.setOpacity(0.42 * shine)
        p.drawImage(self.star_rect_img(), self.star_glow)
        p.setOpacity(1)

    def draw_tiny(self, p, i, glow):
        x, y, size, kind = self.tiny[i]
        p.setPen(Qt.PenStyle.NoPen)
        if glow > 0.01:
            r = size * 4
            halo = QRadialGradient(x, y, r)
            halo.setColorAt(0, QColor(255, 255, 255, int(60 * glow)))
            halo.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(halo)
            p.drawEllipse(QPointF(x, y), r, r)
        p.setOpacity(0.28 + 0.72 * glow)
        if kind == "dot":
            p.setBrush(QColor(236, 238, 244))
            p.drawEllipse(QPointF(x, y), size * 0.5, size * 0.5)
        else:
            sz = size * (1 + 0.25 * glow)
            g = QLinearGradient(x - sz, y - sz, x + sz, y + sz)
            g.setColorAt(0, QColor("#ffffff"))
            g.setColorAt(0.5, QColor("#9a9ea8"))
            g.setColorAt(1, QColor("#e8eaef"))
            p.fillPath(star_path(x, y, sz, sz * 0.72, size * 0.12), g)
        p.setOpacity(1)

    def main_rect(self):
        return self.star_rect_img().adjusted(-8, -8, 8, 8)

    def tiny_rect(self, i):
        x, y, size, _ = self.tiny[i]
        r = size * 4 + 2
        return QRectF(x - r, y - r, 2 * r, 2 * r)

    # animation bookkeeping
    def start(self, key):
        if key == "main" and self.round:
            return                                   # the round clock has no big star
        self.effects[key] = time.monotonic()

    def active_rects(self):
        return [self.main_rect() if k == "main" else self.tiny_rect(k) for k in self.effects]

    def prune(self):
        now = time.monotonic()
        for k, t0 in list(self.effects.items()):
            if now - t0 > (SHINE_TIME if k == "main" else TWINKLE_TIME):
                del self.effects[k]

    # text
    def strings(self, now):
        if self.h24:
            t = now.strftime("%H:%M:%S" if self.seconds else "%H:%M")
            ampm = ""
        else:
            h = now.hour % 12 or 12
            t = f"{h}:{now.minute:02d}" + (f":{now.second:02d}" if self.seconds else "")
            ampm = "am" if now.hour < 12 else "pm"
        if self.locale == "" and self.date_kind == "weekday":
            date = f"{now.strftime('%A')}, {now.strftime('%B')} {now.day}"      # what 1.0 showed
        else:
            date = self.local_date(now)
        return t, ampm, date.lower() if self.lowercase else date

    def local_date(self, now):
        """The date in the chosen language, using Qt's locale data. Persian uses the Persian calendar."""
        if self.date_kind == "none":
            return ""
        loc = QLocale(self.locale or "en_US")
        d = QDate(now.year, now.month, now.day)
        cal = QCalendar(QCalendar.System.Jalali) if self.locale == "fa_IR" else QCalendar()
        if self.date_kind == "numeric":
            pattern = loc.dateFormat(QLocale.FormatType.ShortFormat)
        else:
            pattern = DATE_PATTERNS[self.date_kind]
        return loc.toString(d, pattern, cal)

    def layout(self):
        """Top of the digits, top of the date, room for the time, and whether things are centered."""
        w, h = self.size
        k = self.time_size / 100
        th = TIME_H * k
        has_date = self.date_kind != "none"
        if self.round:
            top = h * 0.5 - (th + (26 if has_date else 0)) / 2 - 4
            room = w - 2 * inset("circle", w, h, 0, top, top + th) - 28
            return top, top + th + 14, room, True
        if (k, has_date) == (1, True):
            return TIME_TOP, DATE_TOP, TEXT_MAX_W, False
        top = 65.5 - (th + (26 if has_date else 0)) / 2
        return top, top + th + 14, TEXT_MAX_W, False

    def date_image(self, date):
        if self.date_cache[0] != date:
            if not self.family and all(ord(c) < 0x250 for c in date):
                f = self.date_font
                l, t, r, b = f.getbbox(date)
                im = Image.new("RGBA", (r - l + 4, b - t + 4), (0, 0, 0, 0))
                ImageDraw.Draw(im).text((2 - l, 2 - t), date, font=f, fill=(150, 153, 163, 255))
                img = pil_to_qimage(im, S)
            else:
                img = self.qt_date(date)
            self.date_cache = (date, img)
        return self.date_cache[1]

    def qt_date(self, date):
        """Dates in other scripts (Persian, Arabic, Chinese...) go through Qt, which shapes them and
        finds a font that has the letters."""
        f = qt_font(self.family or unbounded_family(), 11.5 * S, 300)
        fm = QFontMetricsF(f)
        room = (self.dial()[5] if self.face == "analog" else self.layout()[2]) * S
        text = fm.elidedText(date, Qt.TextElideMode.ElideRight, room)
        r = fm.tightBoundingRect(text)
        wpx, hpx = int(fm.horizontalAdvance(text) + 8), int(fm.height() + 6)
        img = QImage(max(1, wpx), max(1, hpx), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(f)
        p.setPen(QColor(150, 153, 163))
        p.drawText(QPointF(2 - min(0, r.left()), 2 + fm.ascent() - (fm.ascent() + r.top())), text)
        p.end()
        img.setDevicePixelRatio(S)
        return img

    # analog face
    def dial(self):
        """Center and radius of the dial, and where the date goes, as (cx, cy, r, date_x, date_top, room)."""
        w, h = self.size
        k = self.time_size / 100
        has_date = self.date_kind != "none"
        if self.round:
            r = (54 if has_date else 70) * k
            cy = h / 2 - (14 if has_date else 0) * k
            top = cy + r + 12
            room = w - 2 * inset("circle", w, h, 0, top, top + 14) - 28
            return w / 2, cy, r, None, top, room
        r = 46 * k ** 0.5            # the dial grows slower than the digits would, so the date keeps its room
        cx = PAD + r
        x = cx + r + 22
        return cx, h / 2, r, x, h / 2 - 6, STAR_C[0] - STAR_RH - 14 - x

    def draw_dial(self, p):
        """Rim and ticks, drawn once with the rest of the card."""
        cx, cy, r, *_ = self.dial()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 36), 1.2))
        p.drawEllipse(QPointF(cx, cy), r, r)
        for i in range(60):
            hour = i % 5 == 0
            a = math.radians(i * 6)
            r0, r1 = r - (9 if hour else 4.5), r - 2.5
            p.setPen(QPen(QColor(236, 238, 244, 230 if hour else 70), 2.0 if hour else 1.0, cap=Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx + r0 * math.sin(a), cy - r0 * math.cos(a)),
                       QPointF(cx + r1 * math.sin(a), cy - r1 * math.cos(a)))
        p.restore()

    def hand(self, p, cx, cy, deg, length, width, tail=0.0, metal=True):
        p.save()
        p.translate(cx, cy)
        p.rotate(deg)
        body = QRectF(-width / 2, -length, width, length + tail)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawRoundedRect(body.translated(1.2, 1.8), width / 2, width / 2)
        if metal:
            g = QLinearGradient(-width / 2, 0, width / 2, 0)
            g.setColorAt(0, QColor("#ffffff"))
            g.setColorAt(0.5, QColor("#9a9ea8"))
            g.setColorAt(1, QColor("#e8eaef"))
            p.setBrush(g)
        else:
            p.setBrush(QColor(236, 238, 244))
        p.drawRoundedRect(body, width / 2, width / 2)
        p.restore()

    def draw_analog(self, p, now):
        cx, cy, r, date_x, date_top, room = self.dial()
        minute = now.minute + now.second / 60
        hour = now.hour % 12 + minute / 60
        self.hand(p, cx, cy, hour * 30, r * 0.5, 4.6 * r / 46)
        self.hand(p, cx, cy, minute * 6, r * 0.76, 3.2 * r / 46)
        if self.seconds:
            self.hand(p, cx, cy, now.second * 6, r * 0.84, 1.3, tail=r * 0.16, metal=False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(236, 238, 244))
        p.drawEllipse(QPointF(cx, cy), 3.4, 3.4)
        p.setBrush(QColor(13, 13, 15))
        p.drawEllipse(QPointF(cx, cy), 1.3, 1.3)
        self.drawn = {"dial": QRectF(cx - r, cy - r, 2 * r, 2 * r)}
        date = self.strings(now)[2]
        if not date:
            return
        img = self.date_image(date)
        dw, dh = img.width() / S, img.height() / S
        k = min(1.0, (room + 4 / S) / dw)
        dx = date_x if date_x is not None else (self.size[0] - dw * k) / 2
        p.drawImage(QRectF(dx - 2 / S, date_top - 2 / S, dw * k, dh * k), img)
        self.drawn["date"] = QRectF(dx, date_top, (dw - 4 / S) * k, (dh - 4 / S) * k)

    def draw_text(self, p, now):
        if self.face == "analog":
            return self.draw_analog(p, now)
        t, ampm, date = self.strings(now)
        top, date_top, room, centered = self.layout()
        track = -1.0
        gap = 3
        first = self.big.get(t[0])
        digit_top = self.big.get("0")["ink_t"]
        total = self.big.width(t, track) + (gap + self.small.width(ampm) if ampm else 0) - first["ink_l"]
        fit = min(1.0, room / total)

        w = self.size[0]
        x0 = (w - total * fit) / 2 if centered else PAD
        self.drawn = {"time": QRectF(x0, top, total * fit, -digit_top * fit)}    # for the overlap tests
        p.save()
        p.translate(x0, top)
        p.scale(fit, fit)                        # only shrinks for very long times, like with seconds
        x = -first["ink_l"]                      # so the first digit's ink starts exactly at PAD
        self.big.draw(p, t, x, -digit_top, track)
        if ampm:
            self.small.draw(p, ampm, x + self.big.width(t, track) + gap, -digit_top)
        p.restore()

        if not date:
            return
        # the date's ink also starts exactly at PAD, so both lines share one left edge
        img = self.date_image(date)
        dw, dh = img.width() / S, img.height() / S
        k = min(1.0, (room + 4 / S) / dw)            # a long date shrinks to fit, like the time does
        dx = (w - dw * k) / 2 if centered else PAD - 2 / S
        if k < 1:
            p.drawImage(QRectF(dx, date_top - 2 / S, dw * k, dh * k), img)
        else:
            p.drawImage(QPointF(dx, date_top - 2 / S), img)
        self.drawn["date"] = QRectF(dx + 2 / S * k, date_top, (dw - 4 / S) * k, (dh - 4 / S) * k)

    def paint(self, p, now=None, clock=None):
        now = now or datetime.datetime.now()
        clock = time.monotonic() if clock is None else clock
        w, h = self.size
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.show_shadow:
            p.drawImage(QRectF(0, 0, w + 2 * M, h + 2 * M), self.shadow)
        p.translate(M, M)
        if getattr(self, "bg_on", False):
            p.save()
            p.setClipPath(self.card_path())
            p.fillRect(QRectF(0, 0, w, h), self.fill())
            if self.background is not None:
                bw, bh = self.background.width() / 2, self.background.height() / 2
                p.drawImage(QRectF((w - bw) / 2, (h - bh) / 2, bw, bh), self.background)
                p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, int(255 * self.dim / 100)))
            p.restore()
        p.drawImage(QRectF(0, 0, w, h), self.base)
        for k, t0 in self.effects.items():
            if k == "main":
                v = pulse((clock - t0) / SHINE_TIME)
                if v > 0.001:
                    self.draw_shine(p, v)
            else:
                v = pulse((clock - t0) / TWINKLE_TIME)
                if v > 0.001:
                    self.draw_tiny(p, k, v)
        self.draw_text(p, now)


_unbounded = None


def unbounded_family():
    """Load the bundled font into Qt once, for dates drawn by Qt."""
    global _unbounded
    if _unbounded is None:
        _unbounded = ""
        for path in FONT_SPOTS:
            if os.path.exists(path):
                fid = QFontDatabase.addApplicationFont(path)
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                if fams:
                    _unbounded = fams[0]
                    break
    return _unbounded


# ---------------------------------------------------------------- preview for the settings window
_preview = None


def preview_image(o, settings=None, dpr=2):
    global _preview
    if _preview is None:
        _preview = ClockCard()            # building the chrome star takes a moment, so keep one around
    card = _preview
    card.apply(o)
    if o["background"]:
        card.set_background(QImageReader(o["background"]).read())
    w, h = card.size
    return render(lambda p: card.paint(p, datetime.datetime.now(), 0.0), w + 2 * M, h + 2 * M, dpr, o["opacity"])


# ---------------------------------------------------------------- open with Windows
def startup_command():
    return aura_common.startup_command(__file__)


def startup_enabled():
    return aura_common.startup_enabled(RUN_NAME)


def set_startup(on):
    aura_common.set_startup(RUN_NAME, on, __file__)


# ---------------------------------------------------------------- window
def main():
    from PyQt6.QtWidgets import QApplication, QWidget, QMenu
    import aura_ui

    aura_common.setup_logging("aura_clock")
    app = QApplication(sys.argv)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "aura_clock.lock"))
    if not lock.tryLock(100):
        return
    settings = aura_common.settings("Clock")

    class Widget(QWidget):
        def __init__(self):
            super().__init__()
            self.card = ClockCard()
            self.opts = aura_common.options(settings, "Clock")
            self.card.apply(self.opts)
            self.scale = self.opts["scale"]
            self.on_top = self.opts["on_top"]
            self.sparkle_on = self.opts["sparkle"]
            self.paused_for_game = False
            self.held = False            # paused from the tray
            self.drag = None
            # optional background GIF or picture behind the time
            self.bg = GifPlayer(self)
            self.bg.frame.connect(self.on_background)
            self.bg_path = ""
            self.extras = aura_ui.Extras(
                self, settings, "Clock", "Clock", "aura_clock", RUN_NAME, __file__,
                lambda g: QPoint(g.right() - self.width() - 20, g.top() + 20), lambda: M * self.scale,
                hold=self.set_held, held=lambda: self.held, changed=self.apply_settings, refresh=self.check_game)
            self.load_background()
            self.apply_flags()
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.resize_to_scale()
            self.extras.place()

            self.timer = QTimer(self, singleShot=True)
            self.timer.timeout.connect(self.tick)
            self.tick()

            # animation frames only run while something is shining; idle the rest of the time
            self.frames = QTimer(self, interval=33)
            self.frames.timeout.connect(self.on_frame)
            self.shine_timer = QTimer(self, singleShot=True)
            self.shine_timer.timeout.connect(self.shine)
            self.twinkle_timer = QTimer(self, singleShot=True)
            self.twinkle_timer.timeout.connect(self.twinkle)
            self.game_check = QTimer(self, interval=2000)
            self.game_check.timeout.connect(self.check_game)
            self.game_check.start()
            self.schedule()

        def tick(self):
            self.update()
            wait = ms_to_next_tick(datetime.datetime.now(), self.card.seconds)
            self.timer.start(wait)
            self.due = time.time() + wait / 1000

        def animating_allowed(self):
            return self.sparkle_on and not self.paused_for_game and not self.held

        # settings from the settings window (all optional, the defaults are the 1.0 clock)
        def apply_settings(self):
            old, self.opts = self.opts, aura_common.options(settings, "Clock")
            size = self.card.size
            self.card.apply(self.opts)
            if self.opts["background"] != self.bg_path or old["shape"] != self.opts["shape"]:
                self.load_background()
            if self.opts["scale"] != self.scale or self.card.size != size:
                self.scale = self.opts["scale"]
                self.resize_to_scale()
            if self.opts["seconds"] != old["seconds"]:
                self.timer.stop()
                self.tick()
            if self.opts["sparkle"] != self.sparkle_on:
                self.sparkle_on = self.opts["sparkle"]
                self.set_held(self.held)
            if (self.opts["on_top"], self.opts["click_through"]) != (self.on_top, old["click_through"]):
                self.on_top = self.opts["on_top"]
                self.apply_flags()
                self.extras.reshow()
            if self.opts["monitor"] != old["monitor"]:
                self.extras.place()
            self.update()

        def load_background(self):
            self.bg_path = self.opts["background"]
            if self.bg_path and self.bg.open(self.bg_path):
                self.bg.set_paused(self.paused_for_game or self.held)
            else:
                if self.bg_path:
                    logging.warning("can't show %s behind the clock", self.bg_path)
                self.bg.set_paused(True)
                self.bg.path = self.bg.reader = None
                self.card.set_background(None)

        def on_background(self, img):
            self.card.set_background(img)
            self.update()

        def set_held(self, on):
            self.held = on
            if self.bg.path:
                self.bg.set_paused(on or self.paused_for_game)
            if on or not self.animating_allowed():
                self.shine_timer.stop()
                self.twinkle_timer.stop()
            else:
                self.schedule()

        def schedule(self):
            if not self.animating_allowed():
                return
            if not self.shine_timer.isActive():
                self.shine_timer.start(random.randint(6000, 10000))
            if not self.twinkle_timer.isActive():
                self.twinkle_timer.start(random.randint(900, 2200))

        def shine(self):
            if self.animating_allowed() and "main" not in self.card.effects:
                self.card.start("main")
                self.frames.start()
            self.schedule()

        def twinkle(self):
            if self.animating_allowed():
                free = [i for i in range(len(self.card.tiny)) if i not in self.card.effects]
                if free:
                    self.card.start(random.choice(free))
                    self.frames.start()
            self.schedule()

        def on_frame(self):
            rects = self.card.active_rects()
            self.card.prune()
            s = self.scale
            for r in rects:
                self.update(int((r.x() + M) * s) - 1, int((r.y() + M) * s) - 1,
                            int(r.width() * s) + 3, int(r.height() * s) + 3)
            if not self.card.effects:
                self.frames.stop()

        def check_game(self):
            if time.time() > self.due + 2:
                # the minute timer fired late (the PC slept, or the system clock jumped), catch up now
                self.timer.stop()
                self.tick()
            busy = fullscreen_app_open() or self.extras.hidden_all
            if busy != self.paused_for_game:
                self.paused_for_game = busy
                if self.bg.path:
                    self.bg.set_paused(busy or self.held)
                if busy:
                    self.shine_timer.stop()
                    self.twinkle_timer.stop()
                else:
                    self.schedule()

        def enterEvent(self, e):
            self.shine()

        def apply_flags(self):
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            flags |= Qt.WindowType.WindowStaysOnTopHint if self.on_top else Qt.WindowType.WindowStaysOnBottomHint
            self.setWindowFlags(self.extras.flags(flags))

        def resize_to_scale(self):
            w, h = self.card.size
            self.setFixedSize(int((w + 2 * M) * self.scale), int((h + 2 * M) * self.scale))

        def paintEvent(self, e):
            self.extras.paint(self.draw)

        def draw(self, p):
            p.scale(self.scale, self.scale)
            self.card.paint(p)

        def mousePressEvent(self, e):
            if e.button() == Qt.MouseButton.LeftButton and not self.extras.locked:
                self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

        def mouseMoveEvent(self, e):
            if self.drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
                self.move(self.extras.snap(e.globalPosition().toPoint() - self.drag))

        def mouseReleaseEvent(self, e):
            if self.drag is not None:
                self.drag = None
                self.extras.remember()

        def contextMenuEvent(self, e):
            menu = QMenu(self)
            h24 = QAction("24 hour time", menu, checkable=True, checked=self.card.h24)
            secs = QAction("Show seconds", menu, checkable=True, checked=self.card.seconds)
            spark = QAction("Sparkle animation", menu, checkable=True, checked=self.sparkle_on)
            menu.addAction(h24)
            menu.addAction(secs)
            menu.addAction(spark)
            size_menu = menu.addMenu("Size")
            for label, val in (("Small", 0.8), ("Medium", 1.0), ("Large", 1.25)):
                a = QAction(label, size_menu, checkable=True, checked=abs(self.scale - val) < 0.01)
                a.triggered.connect(lambda _, v=val: self.set_scale(v))
                size_menu.addAction(a)
            self.extras.settings_action(menu)
            menu.addSeparator()
            top = QAction("Keep on top of windows", menu, checkable=True, checked=self.on_top)
            boot = QAction("Open when my PC starts", menu, checkable=True, checked=startup_enabled())
            menu.addAction(top)
            menu.addAction(boot)
            menu.addSeparator()
            quit_a = menu.addAction("Close widget")
            chosen = menu.exec(e.globalPos())
            if chosen is h24:
                self.card.h24 = not self.card.h24
                settings.setValue("h24", "true" if self.card.h24 else "false")
                self.update()
            elif chosen is secs:
                self.card.seconds = not self.card.seconds
                settings.setValue("seconds", "true" if self.card.seconds else "false")
                self.timer.stop()
                self.tick()
            elif chosen is spark:
                self.sparkle_on = not self.sparkle_on
                settings.setValue("sparkle", "true" if self.sparkle_on else "false")
                if self.sparkle_on:
                    self.schedule()
                else:
                    self.shine_timer.stop()
                    self.twinkle_timer.stop()
            elif chosen is top:
                self.on_top = not self.on_top
                settings.setValue("on_top", "true" if self.on_top else "false")
                self.apply_flags()
                self.extras.reshow()
            elif chosen is boot:
                set_startup(not startup_enabled())
            elif chosen is quit_a:
                app.quit()

        def set_scale(self, v):
            self.scale = v
            settings.setValue("scale", v)
            self.resize_to_scale()
            self.update()

    w = Widget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
