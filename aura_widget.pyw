"""
Aura  a now playing widget for Windows.
Album art dissolves into a rounded card tinted with the cover's own colors.
Reads what's playing through Windows' media controls, so no Spotify login is needed.

Right click the widget for options. Drag it anywhere.
"""
import sys, os, io, time, math, asyncio, threading, colorsys, datetime, logging, tempfile

from PIL import Image, ImageFilter
from PyQt6.QtCore import (Qt, QTimer, QPointF, QRectF, QObject, pyqtSignal, QVariantAnimation,
                          QEasingCurve, QPoint, QLockFile)
from PyQt6.QtGui import (QPainter, QColor, QImage, QPainterPath, QLinearGradient, QFont,
                         QFontMetricsF, QPen, QFontDatabase, QAction)

import aura_common
from aura_common import fullscreen_app_open
from aura_draw import shape_path, shadow_pil, draw_border, inset, sample_cover, render

# ---------------------------------------------------------------- layout
W, H = 400, 132          # card size (logical px)
M = 26                   # room around the card for the shadow
RADIUS = 26
ART = H                  # album art is a square as tall as the card
PAD_R = 24
TEXT_X = ART + 8

DETAIL = 2               # cached art is drawn this many pixels per point; raised on very high DPI screens
RUN_NAME = "AuraWidget"
TIMEOUT = 5              # seconds before a Windows media call counts as stuck
IDLE_AFTER_MS = 15_000   # how long nothing has to play before "hide while nothing is playing" hides the card


# ---------------------------------------------------------------- color helpers
def hsv(h, s, v, a=255):
    r, g, b = colorsys.hsv_to_rgb(h, max(0, min(1, s)), max(0, min(1, v)))
    return QColor(int(r * 255), int(g * 255), int(b * 255), a)


def mix(a, b, t):
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t),
                  int(a.alpha() + (b.alpha() - a.alpha()) * t))


def with_alpha(c, a):
    c = QColor(c)
    c.setAlpha(max(0, min(255, int(a))))
    return c


def palette_from(im):
    """Pick the cover's main color, then derive box, text and bar shades from it."""
    small = im.convert("RGB").resize((64, 64))
    q = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    best, best_score = (0, 0, 0.5), -1
    for count, idx in q.getcolors():
        r, g, b = pal[idx * 3: idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        weight = 0.15 if (v < 0.13 or (v > 0.94 and s < 0.08)) else 1.0
        score = count * (0.35 + s) * weight
        if score > best_score:
            best_score, best = score, (h, s, v)
    h, s, v = best
    mono = s < 0.1
    sat = lambda x: 0 if mono else x
    return {
        "bg":   hsv(h, sat(min(0.62, s * 0.85 + 0.18)), 0.24),
        "text": hsv(h, sat(0.20), 0.98),
        "sub":  hsv(h, sat(0.32), 0.88, 190),
        "bar":  hsv(h, sat(max(0.42, min(0.7, s))), 0.97),
    }


NEUTRAL = {"bg": QColor(38, 36, 40), "text": QColor(245, 242, 246),
           "sub": QColor(200, 196, 204, 170), "bar": QColor(230, 226, 234)}


def pil_to_qimage(im, premul=False):
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    q = QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()
    if premul:
        q = q.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return q


def rounded(rect, r):
    p = QPainterPath()
    p.addRoundedRect(rect, r, r)
    return p


def pick_font(size, weight):
    families = set(QFontDatabase.families())
    for name in ("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI", "Inter"):
        if name in families:
            break
    else:
        name = QFont().family()
    f = QFont(name)
    f.setPixelSize(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def fmt(ms):
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


# ---------------------------------------------------------------- track + card drawing
CIRCLE = 200             # the round card is this wide


class Look:
    """How the card is shaped and what it shows. The defaults draw exactly the 1.0 card."""

    def __init__(self, o=None):
        o = o or {}
        self.shape = o.get("shape", "rounded")
        self.radius = o.get("radius", RADIUS)
        self.border = o.get("border", "thin")
        self.text = o.get("text_size", 100) / 100
        self.artist = o.get("show_artist", True)
        self.bar = o.get("show_bar", True)
        self.times = o.get("show_times", True)
        self.controls = o.get("show_controls", True)
        self.backdrop = o.get("backdrop", "tint")
        # every line of text gets at least 3:1 contrast with what's behind it, or 4.5:1 with high contrast on
        self.floor = 4.5 if o.get("high_contrast", False) else 3.0

    @property
    def round(self):
        return self.shape == "circle"

    @property
    def size(self):
        return (CIRCLE, CIRCLE) if self.round else (W, H)

    def layer_key(self):
        return self.shape, self.radius, self.border, self.backdrop


class Track:
    def __init__(self, title, artist, cover_bytes=None, theme="cover", look=None):
        self.title, self.artist = title or "", artist or ""
        self.data, self.theme = cover_bytes, theme
        self.look = look or Look()
        self.cover = self.blur = self.src = None
        self.colors = dict(NEUTRAL)
        if cover_bytes:
            try:
                im = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
                w, h = im.size
                s = min(w, h)
                im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
                self.cover = pil_to_qimage(im.resize((ART * DETAIL, ART * DETAIL), Image.Resampling.LANCZOS))
                self.blur = pil_to_qimage(im.resize((W // 5, H // 5)).filter(ImageFilter.GaussianBlur(5)))
                if theme == "cover":
                    self.colors = palette_from(im)
            except Exception:
                logging.exception("cover decode failed")
        self.palette = dict(self.colors)
        self.layer = self._build_layer()
        self.readable()

    def relayer(self, look):
        redo = look.layer_key() != self.look.layer_key()
        refix = redo or look.floor != self.look.floor
        self.look = look
        if redo:
            self.layer = self._build_layer()
        if refix:
            self.readable()

    def readable(self):
        """Make sure each line of text stands out from the actual pixels behind it. On most covers this
        changes nothing. Where a line would fall under the floor (bright art showing through), that line
        first gets less see-through and then lighter, just until it passes."""
        self.colors = dict(self.palette)
        self.time_alpha = 190 if self.look.round else 170
        if self.cover is None:
            return
        bands = TEXT_BANDS_ROUND if self.look.round else TEXT_BANDS
        try:
            title, artist, times = (band_pixels(self.layer, bands[n]) for n in ("title", "artist", "times"))
        except Exception:
            logging.exception("contrast check failed")
            return
        floor = self.look.floor * 1.02       # a little over, since only some of the pixels are looked at
        self.colors["text"] = lift(self.colors["text"], title, floor)
        self.colors["sub"] = lift(self.colors["sub"], artist, floor)
        sub = with_alpha(self.colors["sub"], self.time_alpha)
        fixed = lift(sub, times, floor)
        if fixed.alpha() != sub.alpha() or fixed.rgb() != sub.rgb():
            self.time_alpha = fixed.alpha()
            if fixed.rgb() != sub.rgb():
                self.colors["sub"] = QColor(fixed.red(), fixed.green(), fixed.blue(), self.colors["sub"].alpha())

    def _build_layer(self):
        """Everything that doesn't move: box color, blurred glow, and the fading album art."""
        look = self.look
        w, h = look.size
        img = QImage(w * DETAIL, h * DETAIL, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(DETAIL)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = QRectF(0, 0, w, h)
        p.setClipPath(shape_path(look.shape, card, look.radius))
        p.fillRect(card, self.colors["bg"])
        if look.round:
            if self.src is None and self.data:
                try:      # only the round card needs the cover this big, so it's made when needed
                    im = Image.open(io.BytesIO(self.data)).convert("RGB")
                    s = min(im.size)
                    im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width - s) // 2 + s, (im.height - s) // 2 + s))
                    self.src = im.resize((CIRCLE * DETAIL, CIRCLE * DETAIL), Image.Resampling.LANCZOS)
                except Exception:
                    logging.exception("cover decode failed")
            if self.src is not None:
                p.drawImage(card, pil_to_qimage(self.src))
            # the cover fills the circle and fades into the card color where the text goes
            g = QLinearGradient(0, h * 0.3, 0, h)
            for stop, a in ((0.0, 0), (0.3, 165), (0.5, 232), (1.0, 250)):
                g.setColorAt(stop, with_alpha(self.colors["bg"], a))
            p.fillRect(card, g)
        else:
            if self.blur is not None:
                soft = look.backdrop == "blur"
                p.setOpacity(1 if soft else 0.7)
                p.drawImage(card, self.blur)
                p.setOpacity(1)
                tint = 165
                if soft:         # the cover shows through, but a bright one gets a darker tint so the text still reads
                    c = self.blur.scaled(1, 1, Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation).pixelColor(0, 0)
                    tint = 100 + int(110 * luminance(c.red(), c.green(), c.blue()))
                p.fillRect(card, with_alpha(self.colors["bg"], tint))
            if self.cover is not None:
                art = QImage(self.cover)
                art.setDevicePixelRatio(DETAIL)
                ap = QPainter(art)
                ap.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                g = QLinearGradient(0, 0, ART, 0)
                for stop, a in ((0.0, 255), (0.30, 255), (0.45, 228), (0.60, 165), (0.75, 88), (0.88, 30), (1.0, 0)):
                    g.setColorAt(stop, QColor(0, 0, 0, a))
                ap.fillRect(QRectF(0, 0, ART, ART), g)
                ap.end()
                p.drawImage(QRectF(0, 0, ART, H), art)
        p.setClipping(False)
        draw_border(p, look.border, look.shape, w, h, look.radius)
        p.end()
        return img


# where the text sits on the default layouts, as (x0, x1, y0, y1)
TEXT_BANDS = {"title": (TEXT_X, W - PAD_R, 34, 54), "artist": (TEXT_X, W - PAD_R, 57, 73),
              "times": (TEXT_X, W - PAD_R, 102, 114)}
TEXT_BANDS_ROUND = {"title": (18, 182, 108.5, 128.5), "artist": (26, 174, 129.5, 146.5),
                    "times": (41, 159, 153.5, 166.5)}


def band_pixels(img, band, step=4):
    """Every step-th pixel (in each direction) of a band of the card layer, as (r, g, b)."""
    d = img.devicePixelRatio()
    x0, x1, y0, y1 = band
    sub = img.copy(int(x0 * d), int(y0 * d), int((x1 - x0) * d), int((y1 - y0) * d))
    sub = sub.convertToFormat(QImage.Format.Format_RGB888)
    ptr = sub.constBits()
    ptr.setsize(sub.sizeInBytes())
    b, bpl = bytes(ptr), sub.bytesPerLine()
    return [(b[i], b[i + 1], b[i + 2]) for y in range(0, sub.height(), step)
            for i in range(y * bpl, y * bpl + sub.width() * 3, 3 * step)]


def _lin(v):
    v /= 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


LIN = [_lin(v) for v in range(256)]


def luminance(r, g, b):
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(color, pixels):
    """WCAG contrast of a (maybe see-through) text color against background pixels, at the worst 5%.
    Plain Python on a sample of pixels, so the widget doesn't need NumPy (13 MB) just for this."""
    a = color.alpha() / 255
    fr, fg, fb = color.red() * a, color.green() * a, color.blue() * a
    k = 1 - a
    out = []
    for r, g, b in pixels:
        bg = 0.2126 * LIN[r] + 0.7152 * LIN[g] + 0.0722 * LIN[b]
        fl = luminance(fr + k * r, fg + k * g, fb + k * b)
        hi, lo = (fl, bg) if fl > bg else (bg, fl)
        out.append((hi + 0.05) / (lo + 0.05))
    out.sort()
    return out[int(0.05 * (len(out) - 1))] if out else 21.0


def lift(color, bg, floor):
    """The smallest change to a text color that gets it to floor: less see-through first, then lighter."""
    if not bg or contrast(color, bg) >= floor:
        return color
    c = QColor(color)
    while c.alpha() < 255:
        c.setAlpha(min(255, c.alpha() + 8))
        if contrast(c, bg) >= floor:
            return c
    white = QColor(255, 255, 255)
    for step in range(1, 11):
        m = mix(color, white, step / 10)
        m.setAlpha(255)
        if contrast(m, bg) >= floor:
            return m
    return m


class Card:
    """Draws the widget. Kept separate from the window so it can render previews too."""

    def __init__(self):
        self.look = Look()
        self.cur = Track("Nothing playing", "Play a song in Spotify")
        self.old = None
        self.t = 1.0              # crossfade progress between old and cur
        self.hover = 0.0
        self.pos_ms = self.dur_ms = 0
        self.anchor = time.monotonic()
        self.playing = False
        self.preview = None       # where a seek would land (0 to 1), while hovering or dragging the bar
        self.show_shadow = True
        self.hit = {}
        self.fonts()
        self.shadow = self._make_shadow()

    def fonts(self):
        k = self.look.text
        self.f_title = pick_font(round(16 * k), QFont.Weight.DemiBold)
        self.f_artist = pick_font(round(13 * k), QFont.Weight.Normal)
        self.f_time = pick_font(round(11 * k), QFont.Weight.Medium)

    def set_look(self, look):
        old, self.look = self.look, look
        if look.text != old.text:
            self.fonts()
        if look.layer_key() != old.layer_key():
            self.shadow = self._make_shadow()
        for tr in (self.cur, self.old):
            if tr is not None:
                tr.relayer(look)

    @property
    def size(self):
        return self.look.size

    def _make_shadow(self):
        s = 2
        w, h = self.look.size
        q = pil_to_qimage(shadow_pil(w, h, M, self.look.shape, self.look.radius, 120, s), premul=True)
        q.setDevicePixelRatio(s)
        return q

    def position(self):
        if self.playing:
            return min(self.dur_ms, self.pos_ms + (time.monotonic() - self.anchor) * 1000)
        return self.pos_ms

    def time_alpha(self):
        a = self.cur.time_alpha
        if self.old is not None:
            a = self.old.time_alpha + (a - self.old.time_alpha) * self.t
        return a

    def colors(self):
        if self.old is None:
            return self.cur.colors
        return {k: mix(self.old.colors[k], self.cur.colors[k], self.t) for k in self.cur.colors}

    # ---------------------------------------------------------------- where everything goes
    def layout(self):
        """Baselines and edges for each row. Rows stack from the title down, so a bigger text size
        or a hidden row can never make two rows overlap, and each row stops where the shape cuts in."""
        lk, k = self.look, self.look.text
        w, h = lk.size
        L = {}
        if lk.round:
            t = 0.0
            a = t + 19 * k if lk.artist else None
            last = a if a is not None else t
            tb = last + 21 * k if lk.times else None
            top, bottom = t - 15 * k, (tb if tb is not None else last) + 4 * k
            shift = h * 0.69 - (top + bottom) / 2
            L["title"], L["artist"] = t + shift, (a + shift if a is not None else None)
            L["time"] = tb + shift if tb is not None else None
            L["cx"], L["cy"] = w / 2, h * 0.42
            for row, y in (("title", L["title"]), ("artist", L["artist"]), ("time", L["time"])):
                if y is not None:
                    ins = inset("circle", w, h, 0, y - 15 * k, y + 5 * k)
                    L[row + "_span"] = (ins + 14, w - ins - 14)
            return L

        t = 0.0
        a = t + 20 * k if lk.artist else None
        last = a if a is not None else t
        b = last + 18 * k if lk.bar else None
        row = lk.times or lk.controls
        if row:
            tb = b + 24 * k if b is not None else last + 28 * k
        else:
            tb = None
        bottom = (tb if tb is not None else (b + 4 if b is not None else last)) + 4 * k
        top = t - 16 * k
        shift = 74 - (top + bottom) / 2               # 1.0 sat a little below the middle, keep that
        L["title"], L["artist"] = t + shift, (a + shift if a is not None else None)
        L["bar"] = b + shift if b is not None else None
        L["time"] = tb + shift if tb is not None else None
        L["x"] = TEXT_X

        def right(y0, y1):
            return min(W - PAD_R, w - inset(lk.shape, w, h, lk.radius, y0, y1) - 8)

        L["title_r"] = right(L["title"] - 16 * k, L["title"] + 5 * k)
        if L["artist"] is not None:
            L["artist_r"] = right(L["artist"] - 13 * k, L["artist"] + 4 * k)
        if L["bar"] is not None:
            L["bar_r"] = right(L["bar"], L["bar"] + 4)
        if L["time"] is not None:
            L["time_r"] = right(L["time"] - 10 * k, L["time"] + 3 * k)
            L["cx"] = TEXT_X + (L["time_r"] - TEXT_X) / 2
            L["cy"] = L["time"] - 4
        return L

    # ---------------------------------------------------------------- drawing
    def paint(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.look.size
        if self.show_shadow:
            p.drawImage(QRectF(0, 0, w + 2 * M, h + 2 * M), self.shadow)
        p.translate(M, M)

        if self.old is not None:
            p.drawImage(QRectF(0, 0, w, h), self.old.layer)
            p.setOpacity(self.t)
        p.drawImage(QRectF(0, 0, w, h), self.cur.layer)
        p.setOpacity(1)

        L = self.layout()
        self.drawn = {}           # what got drawn where, so tests can check nothing overlaps
        if self.look.round and self.hover > 0.01 and self.look.controls and self.dur_ms > 0:
            p.fillPath(shape_path("circle", QRectF(0, 0, w, h), 0), QColor(0, 0, 0, int(80 * self.hover)))

        if self.old is not None:
            self._text(p, self.old, 1 - self.t, L)
        self._text(p, self.cur, self.t if self.old is not None else 1, L)

        c = self.colors()
        if self.look.round:
            self._ring(p, c, L)
        else:
            self._bar(p, c, L)
        self._controls(p, c, L)

    def _bar(self, p, c, L):
        x = L["x"]
        if self.dur_ms <= 0:
            return
        shown = self.position() if self.preview is None else self.preview * self.dur_ms
        if L["bar"] is not None:
            frac = max(0.0, min(1.0, self.position() / self.dur_ms))
            bar = QRectF(x, L["bar"], L["bar_r"] - x, 4)
            self.bar_rect = bar
            self.drawn["bar"] = bar
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(with_alpha(c["bar"], 60))
            p.drawRoundedRect(bar, 2, 2)
            if frac > 0:
                p.setBrush(c["bar"])
                p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(4, bar.width() * frac), 4), 2, 2)
            if self.preview is not None:
                px = bar.x() + bar.width() * self.preview
                p.setBrush(with_alpha(c["text"], 245))
                p.drawEllipse(QPointF(px, bar.center().y()), 5, 5)
        else:
            self.bar_rect = None
        if L["time"] is None or not self.look.times:
            return
        fm = QFontMetricsF(self.f_time)
        start, end = fmt(shown), fmt(self.dur_ms)
        right = L["time_r"]
        alpha = self.time_alpha()
        if self.hover > 0.01 and self.look.controls:
            # if the play buttons would run into the times, fade the times out while they show
            if x + fm.horizontalAdvance(start) + 6 > L["cx"] - 43 or right - fm.horizontalAdvance(end) - 6 < L["cx"] + 43:
                alpha = alpha * (1 - self.hover)
        p.setFont(self.f_time)
        p.setPen(with_alpha(c["text"] if self.preview is not None else c["sub"], 230 if self.preview is not None else alpha))
        p.drawText(QPointF(x, L["time"]), start)
        p.setPen(with_alpha(c["sub"], alpha))
        p.drawText(QPointF(right - fm.horizontalAdvance(end), L["time"]), end)
        if alpha > 2:
            self.note("start", fm, start, x, L["time"])
            self.note("end", fm, end, right - fm.horizontalAdvance(end), L["time"])

    def _ring(self, p, c, L):
        w, h = self.look.size
        self.bar_rect = None
        if self.dur_ms <= 0:
            return
        if self.look.bar:
            frac = max(0.0, min(1.0, self.position() / self.dur_ms))
            ring = QRectF(5, 5, w - 10, h - 10)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(with_alpha(c["bar"], 60), 3))
            p.drawEllipse(ring)
            if frac > 0:
                pen = QPen(c["bar"], 3)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(ring, 90 * 16, -int(frac * 5760))
            if self.preview is not None:
                ang = math.radians(90 - 360 * self.preview)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(with_alpha(c["text"], 245))
                p.drawEllipse(QPointF(w / 2 + (w / 2 - 5) * math.cos(ang), h / 2 - (h / 2 - 5) * math.sin(ang)), 5, 5)
        if L.get("time") is not None:
            shown = self.position() if self.preview is None else self.preview * self.dur_ms
            text = f"{fmt(shown)} / {fmt(self.dur_ms)}"
            fm = QFontMetricsF(self.f_time)
            a, b = L["time_span"]
            text = fm.elidedText(text, Qt.TextElideMode.ElideRight, b - a)
            p.setFont(self.f_time)
            p.setPen(with_alpha(c["sub"], self.time_alpha()))
            p.drawText(QPointF(w / 2 - fm.horizontalAdvance(text) / 2, L["time"]), text)
            self.note("times", fm, text, w / 2 - fm.horizontalAdvance(text) / 2, L["time"])

    def note(self, name, fm, text, x, baseline):
        self.drawn[name] = QRectF(x, baseline - fm.ascent(), fm.horizontalAdvance(text), fm.ascent() + fm.descent())

    def seek_target(self, pt):
        """0 to 1 for where on the bar (or the ring) a point is, or None if it isn't on it."""
        if self.dur_ms <= 0 or not self.look.bar:
            return None
        if self.look.round:
            w, h = self.look.size
            dx, dy = pt.x() - w / 2, pt.y() - h / 2
            if not (w / 2 - 18 <= math.hypot(dx, dy) <= w / 2 + 4):
                return None
            return (math.degrees(math.atan2(dx, -dy)) % 360) / 360
        bar = getattr(self, "bar_rect", None)
        if bar is None or not QRectF(bar.x() - 6, bar.y() - 8, bar.width() + 12, 20).contains(pt):
            return None
        return max(0.0, min(1.0, (pt.x() - bar.x()) / bar.width()))

    def drag_target(self, pt):
        """Like seek_target, but once a drag started anywhere is fine."""
        if self.look.round:
            w, h = self.look.size
            return (math.degrees(math.atan2(pt.x() - w / 2, -(pt.y() - h / 2))) % 360) / 360
        bar = self.bar_rect
        return max(0.0, min(1.0, (pt.x() - bar.x()) / bar.width())) if bar is not None else None

    def _text(self, p, tr, alpha, L):
        if alpha <= 0.01:
            return
        fm_t, fm_a = QFontMetricsF(self.f_title), QFontMetricsF(self.f_artist)
        rows = [(self.f_title, fm_t, tr.title, L["title"], with_alpha(tr.colors["text"], 255 * alpha), "title")]
        if L["artist"] is not None:
            rows.append((self.f_artist, fm_a, tr.artist, L["artist"],
                         with_alpha(tr.colors["sub"], tr.colors["sub"].alpha() * alpha), "artist"))
        for font, fm, text, y, color, name in rows:
            p.setFont(font)
            p.setPen(color)
            if self.look.round:
                a, b = L[name + "_span"]
                s = fm.elidedText(text, Qt.TextElideMode.ElideRight, b - a)
                x = self.look.size[0] / 2 - fm.horizontalAdvance(s) / 2
            else:
                x = L["x"]
                s = fm.elidedText(text, Qt.TextElideMode.ElideRight, L[name + "_r"] - x)
            p.drawText(QPointF(x, y), s)
            if hasattr(self, "drawn") and s:
                self.note(name, fm, s, x, y)

    def _controls(self, p, c, L):
        self.hit = {}
        if self.hover <= 0.01 or self.dur_ms <= 0 or not self.look.controls or "cx" not in L:
            return
        col = with_alpha(c["text"], 235 * self.hover)
        cx, cy = L["cx"], L["cy"]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        for name, dx in (("prev", -30), ("toggle", 0), ("next", 30)):
            ox = cx + dx
            self.hit[name] = QRectF(ox - 13, cy - 13, 26, 26)
            self.drawn[name] = QRectF(ox - 7, cy - 7, 14, 14)
            path = QPainterPath()
            if name == "toggle":
                if self.playing:
                    p.drawRoundedRect(QRectF(ox - 5, cy - 6.5, 3.4, 13), 1.4, 1.4)
                    p.drawRoundedRect(QRectF(ox + 1.6, cy - 6.5, 3.4, 13), 1.4, 1.4)
                    continue
                path.moveTo(ox - 4.5, cy - 7); path.lineTo(ox + 7, cy); path.lineTo(ox - 4.5, cy + 7)
            else:
                d = 1 if name == "next" else -1
                path.moveTo(ox - 5 * d, cy - 5.5); path.lineTo(ox + 3 * d, cy); path.lineTo(ox - 5 * d, cy + 5.5)
                p.drawRoundedRect(QRectF(ox + 3.2 * d - (2.2 if d > 0 else 0), cy - 5.5, 2.2, 11), 1, 1)
            path.closeSubpath()
            p.drawPath(path)


# ---------------------------------------------------------------- reading Windows media
class Bridge(QObject):
    track = pyqtSignal(object)      # (title, artist, cover_bytes) or None
    timeline = pyqtSignal(object)   # (pos_ms, dur_ms, playing, can_seek)
    error = pyqtSignal(str)


def to_ms(v):
    if v is None:
        return 0
    if hasattr(v, "total_seconds"):
        return v.total_seconds() * 1000
    return float(v) / 10_000      # 100 ns ticks


def caught_up(pos, dur, updated, now):
    """Windows only reports the position now and then, so add the time since its last report."""
    try:
        ago = (now - updated).total_seconds() * 1000
    except Exception:
        return pos
    return pos + ago if 0 < ago < dur else pos


def can_seek(info):
    """Whether the player lets other apps move its position. Not every player does."""
    try:
        return bool(info.controls.is_playback_position_enabled)
    except Exception:
        return False


async def within(op):
    # a media call that never answers would freeze the card on the last song forever
    return await asyncio.wait_for(op, TIMEOUT)


class MediaWorker(threading.Thread):
    def __init__(self, bridge):
        super().__init__(daemon=True)
        self.bridge = bridge
        self.loop = None
        self.mgr = None
        self.resting = False   # set while a fullscreen game is open

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.main())
        except Exception as e:
            logging.exception("media worker crashed")
            self.bridge.error.emit(str(e))

    def command(self, name, arg=None):
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(self._command(name, arg), self.loop)

    async def _command(self, name, arg=None):
        try:
            s = self.session()
            if s is None:
                return
            if name == "seek":
                # Windows counts in 100 ns ticks
                ok = await within(s.try_change_playback_position_async(int(max(0, arg) * 10_000)))
                if not ok:
                    logging.info("the player didn't take the seek")
            elif name == "toggle":
                await within(s.try_toggle_play_pause_async())
            elif name == "next":
                await within(s.try_skip_next_async())
            elif name == "prev":
                await within(s.try_skip_previous_async())
        except Exception:
            logging.exception("command failed")

    def session(self):
        try:
            for s in self.mgr.get_sessions():
                if "spotify" in (s.source_app_user_model_id or "").lower():
                    return s
        except Exception:
            pass
        return self.mgr.get_current_session()

    async def read_cover(self, ref):
        from winrt.windows.storage.streams import Buffer, InputStreamOptions, DataReader
        stream = await within(ref.open_read_async())
        size = int(stream.size)
        if size <= 0:
            return None
        buf = await within(stream.read_async(Buffer(size), size, InputStreamOptions.READ_AHEAD))
        try:
            return bytes(buf)
        except TypeError:
            reader = DataReader.from_buffer(buf)
            out = bytearray(buf.length)
            reader.read_bytes(out)
            return bytes(out)

    async def connect(self, Manager):
        # right after login the media service can take a while to come up, so keep trying
        wait = 2
        while True:
            try:
                return await within(Manager.request_async())
            except Exception:
                logging.exception("couldn't reach windows media, trying again in %ss", wait)
                await asyncio.sleep(wait)
                wait = min(60, wait * 2)

    async def main(self):
        # imported here so Windows media stays on this thread and doesn't clash with the window
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status)
        self.mgr = await self.connect(Manager)
        last_key, have_cover = "none", True
        fails = 0
        while True:
            try:
                s = self.session()
                if self.resting:
                    await asyncio.sleep(3)
                    continue
                if s is None:
                    if last_key is not None:
                        self.bridge.track.emit(None)
                        self.bridge.timeline.emit((0, 0, False, False))
                    last_key = None
                else:
                    props = await within(s.try_get_media_properties_async())
                    key = (props.title, props.artist)
                    if key != last_key or not have_cover:
                        cover = None
                        for attempt in range(4):
                            if key != last_key and attempt == 0:
                                await asyncio.sleep(0.35)   # cover art lags a moment behind the title
                                props = await within(s.try_get_media_properties_async())
                                key = (props.title, props.artist)
                            if props.thumbnail is not None:
                                try:
                                    cover = await self.read_cover(props.thumbnail)
                                except Exception:
                                    logging.exception("cover read failed")
                            if cover or key == last_key:
                                break
                            await asyncio.sleep(0.4)
                            props = await within(s.try_get_media_properties_async())
                        if key != last_key or cover:
                            self.bridge.track.emit((props.title, props.artist, cover))
                        last_key, have_cover = key, cover is not None

                    tl = s.get_timeline_properties()
                    info = s.get_playback_info()
                    playing = info.playback_status == Status.PLAYING
                    pos, dur = to_ms(tl.position), to_ms(tl.end_time)
                    if playing:
                        pos = caught_up(pos, dur, tl.last_updated_time,
                                        datetime.datetime.now(datetime.timezone.utc))
                    self.bridge.timeline.emit((pos, dur, playing, can_seek(info)))
                fails = 0
            except Exception:
                logging.exception("poll failed")
                fails += 1
                if fails >= 5:
                    # five misses in a row (after sleep, or explorer restarting), so get a fresh manager
                    fails = 0
                    try:
                        self.mgr = await within(Manager.request_async())
                        logging.info("reconnected to windows media")
                    except Exception:
                        logging.exception("reconnect failed")
            await asyncio.sleep(0.8 if last_key is not None else 2.0)


# ---------------------------------------------------------------- the window
def startup_command():
    return aura_common.startup_command(__file__)


def set_startup(on):
    aura_common.set_startup(RUN_NAME, on, __file__)


def startup_enabled():
    return aura_common.startup_enabled(RUN_NAME)


def main():
    from PyQt6.QtWidgets import QApplication, QWidget, QMenu
    from PyQt6.QtGui import QCursor, QGuiApplication
    import aura_ui

    aura_common.setup_logging("aura_widget")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "aura_widget.lock"))
    if not lock.tryLock(100):
        return   # already running

    settings = aura_common.settings("Widget")

    class Widget(QWidget):
        def __init__(self):
            super().__init__()
            self.card = Card()
            self.opts = aura_common.options(settings, "Widget")
            self.scale = self.opts["scale"]
            self.on_top = self.opts["on_top"]
            self.drag = None
            self.held = False            # paused from the tray
            self.seeking = False         # dragging on the progress bar
            self.seek_hold = 0.0         # until then, ignore positions from Windows that predate the seek
            self.can_seek = False
            self.extras = aura_ui.Extras(
                self, settings, "Widget", "Now playing", "aura_widget", RUN_NAME, __file__,
                lambda g: QPoint(g.left() + 20, g.bottom() - self.height() - 20), lambda: M * self.scale,
                hold=self.set_held, held=lambda: self.held, changed=self.apply_settings, refresh=self.check_game)
            self.nothing = False             # no player is open
            self.idle_timer = QTimer(self, singleShot=True, interval=IDLE_AFTER_MS)
            self.idle_timer.timeout.connect(lambda: self.extras.set_idle(self.opts["hide_idle"]))
            self.apply_look()
            self.update_detail()
            app.screenAdded.connect(self.update_detail)
            app.screenRemoved.connect(self.update_detail)
            self.apply_flags()
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setMouseTracking(True)
            self.resize_to_scale()
            self.extras.place()

            self.fade = QVariantAnimation(self, duration=1400, startValue=0.0, endValue=1.0)
            self.fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self.fade.valueChanged.connect(self.on_fade)
            self.hover_anim = QVariantAnimation(self, duration=220)
            self.hover_anim.valueChanged.connect(lambda v: (setattr(self.card, "hover", v), self.update()))

            # redraw only while music plays; 4 times a second keeps the bar and clock smooth
            self.tick = QTimer(self, interval=250)
            self.tick.timeout.connect(self.update)
            self.paused_for_game = False
            self.game_check = QTimer(self, interval=2000)
            self.game_check.timeout.connect(self.check_game)
            self.game_check.start()

            self.bridge = Bridge()
            self.bridge.track.connect(self.on_track)
            self.bridge.timeline.connect(self.on_timeline)
            self.bridge.error.connect(self.on_error)
            self.worker = MediaWorker(self.bridge)
            self.worker.start()

        # window setup
        def apply_flags(self):
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            flags |= Qt.WindowType.WindowStaysOnTopHint if self.on_top else Qt.WindowType.WindowStaysOnBottomHint
            self.setWindowFlags(self.extras.flags(flags))

        def resize_to_scale(self):
            w, h = self.card.size
            self.setFixedSize(int((w + 2 * M) * self.scale), int((h + 2 * M) * self.scale))

        # settings from the settings window (all optional, the defaults are the 1.0 card)
        def theme(self):
            return self.opts["colors"]

        def update_detail(self, *_):
            """Cached art gets sharper only when a screen's scaling times the card size goes past 2."""
            global DETAIL
            d = aura_common.detail_for([s.devicePixelRatio() for s in QGuiApplication.screens()], self.scale)
            if d != DETAIL:
                DETAIL = d
                cur = self.card.cur
                self.card.cur = Track(cur.title, cur.artist, cur.data, cur.theme, self.card.look)
                self.card.old = None
                self.update()

        def apply_look(self):
            self.card.set_look(Look(self.opts))
            self.card.show_shadow = self.opts["shadow"]
            cur = self.card.cur
            if cur.data and cur.theme != self.theme():
                self.card.cur = Track(cur.title, cur.artist, cur.data, self.theme(), self.card.look)

        def apply_settings(self):
            old, self.opts = self.opts, aura_common.options(settings, "Widget")
            size = self.card.size
            self.apply_look()
            if self.opts["scale"] != self.scale or self.card.size != size:
                self.scale = self.opts["scale"]
                self.resize_to_scale()
                self.update_detail()
            if (self.opts["on_top"], self.opts["click_through"]) != (self.on_top, old["click_through"]):
                self.on_top = self.opts["on_top"]
                self.apply_flags()
                self.extras.reshow()
            if self.opts["monitor"] != old["monitor"]:
                self.extras.place()
            self.update_idle()
            self.update()

        def set_held(self, on):
            self.held = on
            self.worker.resting = self.paused_for_game or self.held
            self.update_ticking()

        # data coming in
        def update_idle(self):
            """With "hide while nothing is playing" on, the card goes away 15 seconds after the player does."""
            if self.nothing and self.opts["hide_idle"]:
                if not self.idle_timer.isActive() and not self.extras.idle:
                    self.idle_timer.start()
            else:
                self.idle_timer.stop()
                self.extras.set_idle(False)

        def on_track(self, data):
            self.nothing = not data
            self.update_idle()
            new = (Track(*data, self.theme(), self.card.look) if data
                   else Track("Nothing playing", "Play a song in Spotify", look=self.card.look))
            self.card.old = self.card.cur
            self.card.cur = new
            self.card.t = 0.0
            self.fade.stop()
            self.fade.start()

        def on_fade(self, v):
            self.card.t = v
            if v >= 1:
                self.card.old = None
            self.update()

        def on_timeline(self, data):
            pos, dur, playing = data[:3]
            self.can_seek = len(data) > 3 and data[3]
            # while dragging the bar, and for a moment after a seek, Windows still reports the old
            # position, so don't let that pull the bar back
            busy = self.seeking or time.monotonic() < self.seek_hold
            # ignore tiny jitter so the bar never jumps backwards
            if not busy and not (playing and self.card.playing and abs(self.card.position() - pos) < 1500):
                self.card.pos_ms, self.card.anchor = pos, time.monotonic()
            self.card.dur_ms, self.card.playing = dur, playing
            self.update_ticking()
            self.update()

        def update_ticking(self):
            if self.card.playing and not self.paused_for_game and not self.held:
                if not self.tick.isActive():
                    self.tick.start()
            else:
                self.tick.stop()

        def check_game(self):
            busy = fullscreen_app_open() or self.extras.hidden_all
            if busy != self.paused_for_game:
                self.paused_for_game = busy
                self.worker.resting = busy or self.held
                self.update_ticking()

        def on_error(self, msg):
            self.card.old, self.card.cur = self.card.cur, Track("Setup needed", "Run install.bat, then open me again",
                                                                 look=self.card.look)
            self.card.t = 0
            self.fade.start()

        # drawing
        def paintEvent(self, e):
            self.extras.paint(self.draw)

        def draw(self, p):
            p.scale(self.scale, self.scale)
            self.card.paint(p)

        def to_card(self, pos):
            return QPointF(pos.x() / self.scale - M, pos.y() / self.scale - M)

        # mouse
        def enterEvent(self, e):
            self.hover_anim.stop(); self.hover_anim.setStartValue(self.card.hover)
            self.hover_anim.setEndValue(1.0); self.hover_anim.start()

        def leaveEvent(self, e):
            self.hover_anim.stop(); self.hover_anim.setStartValue(self.card.hover)
            self.hover_anim.setEndValue(0.0); self.hover_anim.start()
            if not self.seeking and self.card.preview is not None:
                self.card.preview = None
                self.update()

        def seekable(self):
            return self.opts["seek"] and self.can_seek and not self.held

        def mousePressEvent(self, e):
            if e.button() != Qt.MouseButton.LeftButton:
                return
            pt = self.to_card(e.position())
            if self.seekable() and self.card.seek_target(pt) is not None:
                self.seeking = True
                self.card.preview = self.card.seek_target(pt)
                self.update()
                return
            for name, r in self.card.hit.items():
                if r.contains(pt):
                    self.worker.command(name)
                    if name == "toggle":
                        self.card.pos_ms, self.card.anchor = self.card.position(), time.monotonic()
                        self.card.playing = not self.card.playing
                        self.update_ticking()
                    return
            if not self.extras.locked:
                self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

        def mouseMoveEvent(self, e):
            pt = self.to_card(e.position())
            if self.seeking:
                self.card.preview = self.card.drag_target(pt)
                self.update()
                return
            if self.drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
                self.move(self.extras.snap(e.globalPosition().toPoint() - self.drag))
                return
            if self.seekable():
                f = self.card.seek_target(pt)
                if f != self.card.preview:
                    self.card.preview = f
                    self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if f is not None
                                           else Qt.CursorShape.ArrowCursor))
                    self.update()

        def mouseReleaseEvent(self, e):
            if self.seeking:
                self.seeking = False
                if self.card.preview is not None and self.card.dur_ms > 0:
                    target = self.card.preview * self.card.dur_ms
                    self.worker.command("seek", target)
                    self.card.pos_ms, self.card.anchor = target, time.monotonic()
                    self.seek_hold = time.monotonic() + 2.5
                self.card.preview = self.card.seek_target(self.to_card(e.position()))
                self.update()
                return
            if self.drag is not None:
                self.drag = None
                self.extras.remember()

        def contextMenuEvent(self, e):
            menu = QMenu(self)
            top = QAction("Keep on top of windows", menu, checkable=True, checked=self.on_top)
            boot = QAction("Open when my PC starts", menu, checkable=True, checked=startup_enabled())
            menu.addAction(top); menu.addAction(boot)
            size_menu = menu.addMenu("Size")
            for label, val in (("Small", 0.8), ("Medium", 1.0), ("Large", 1.25)):
                a = QAction(label, size_menu, checkable=True, checked=abs(self.scale - val) < 0.01)
                a.triggered.connect(lambda _, v=val: self.set_scale(v))
                size_menu.addAction(a)
            self.extras.settings_action(menu)
            menu.addSeparator()
            quit_a = menu.addAction("Close widget")
            chosen = menu.exec(e.globalPos())
            if chosen is top:
                self.on_top = not self.on_top
                settings.setValue("on_top", "true" if self.on_top else "false")
                self.apply_flags(); self.extras.reshow()
            elif chosen is boot:
                set_startup(not startup_enabled())
            elif chosen is quit_a:
                app.quit()

        def set_scale(self, v):
            self.scale = v
            settings.setValue("scale", v)
            self.resize_to_scale()
            self.update_detail()
            self.update()

    w = Widget()
    w.show()
    sys.exit(app.exec())


# ---------------------------------------------------------------- preview for the settings window
_sample = None


def preview_image(o, settings=None, dpr=2):
    global _sample
    if _sample is None:
        buf = io.BytesIO()
        sample_cover().save(buf, "PNG")
        _sample = buf.getvalue()
    card = Card()
    card.set_look(Look(o))
    card.show_shadow = o["shadow"]
    card.cur = Track("Song title", "Artist name", _sample, o["colors"], card.look)
    card.dur_ms, card.pos_ms = 214_000, 81_000
    w, h = card.size
    return render(card.paint, w + 2 * M, h + 2 * M, dpr, o["opacity"])


# ---------------------------------------------------------------- preview (for testing the look without Windows)
def render_preview(out_path, covers):
    from PyQt6.QtGui import QGuiApplication as GA
    _ = GA.instance() or GA(sys.argv)
    rows = len(covers)
    img = QImage((W + 2 * M) * 2, (H + 2 * M) * 2 * rows, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2)
    img.fill(QColor(222, 220, 226))
    p = QPainter(img)
    for i, (path, title, artist, frac, hover) in enumerate(covers):
        card = Card()
        data = open(path, "rb").read() if path else None
        card.cur = Track(title, artist, data)
        card.dur_ms, card.pos_ms, card.playing, card.hover = 200_000, 200_000 * frac, False, hover
        p.save(); p.translate(0, (H + 2 * M) * i); card.paint(p); p.restore()
    p.end()
    img.save(out_path)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        import json
        render_preview(sys.argv[2], json.loads(sys.argv[3]))
    else:
        main()
