"""
Aura Clock  a rounded desktop card with 3D liquid chrome time, the date,
a 3D chrome star that shines now and then, and a few tiny twinkling stars.
Right click for options. Drag it anywhere.

Needs the fonts folder next to this file (Unbounded, SIL Open Font License).
"""
import sys, os, tempfile, datetime, math, random, time

from PIL import Image, ImageFilter, ImageDraw, ImageFont
from PyQt6.QtCore import Qt, QRectF, QPointF, QSettings, QPoint, QLockFile, QTimer
from PyQt6.QtGui import (QPainter, QColor, QImage, QPainterPath, QPen, QLinearGradient,
                         QRadialGradient, QGuiApplication, QAction)

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


# ---------------------------------------------------------------- text as chrome glyphs
class Glyphs:
    """Each character is turned into chrome once and reused, so updating the time is instant."""

    def __init__(self, px_size, weight, thick, stretch):
        self.font = load_font(int(px_size * S), weight)
        self.thick, self.stretch = thick, stretch
        self.cache = {}

    def get(self, ch):
        if ch not in self.cache:
            f = self.font
            asc, desc = f.getmetrics()
            adv = f.getlength(ch)
            pad = int(self.thick * 2 + 4)
            wpx, hpx = int(adv + 2 * pad), int(asc + desc + 2 * pad)
            m = Image.new("L", (wpx, hpx), 0)
            ImageDraw.Draw(m).text((pad, pad + asc), ch, font=f, fill=255, anchor="ls")
            m = m.resize((wpx, int(hpx * self.stretch)), Image.Resampling.LANCZOS)
            img = chrome(m, self.thick) if ch.strip() else m.convert("RGBA")
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
class ClockCard:
    def __init__(self):
        self.h24 = False
        self.seconds = False
        digit_px = TIME_H / (0.77 * STRETCH)         # font size that makes the digits TIME_H tall
        self.big = Glyphs(digit_px, 700, thick=11 * S * digit_px / 48, stretch=STRETCH)
        self.small = Glyphs(digit_px * 0.36, 700, thick=4.5 * S * digit_px / 48, stretch=STRETCH)
        self.date_font = load_font(int(11.5 * S), 300)
        self.date_cache = (None, None)
        self.shadow = self._shadow()
        self.star_img, self.star_glow = self._star()
        self.base = self._base()
        self.effects = {}

    # drawn once
    def _shadow(self):
        s = 2
        im = Image.new("RGBA", ((W + 2 * M) * s, (H + 2 * M) * s), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle(
            [M * s + 6, (M + 6) * s, (M + W) * s - 6, (M + H + 2) * s], radius=RADIUS * s, fill=(0, 0, 0, 130))
        return pil_to_qimage(im.filter(ImageFilter.GaussianBlur(13 * s)), s)

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

    def _base(self):
        img = QImage(W * S, H * S, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(S)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor(13, 13, 15))
        g.setColorAt(1, QColor(4, 4, 5))
        p.fillPath(rounded(QRectF(0, 0, W, H), RADIUS), g)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawPath(rounded(QRectF(0.5, 0.5, W - 1, H - 1), RADIUS - 0.5))
        for i in range(len(TINY)):
            self.draw_tiny(p, i, 0.0)
        self.draw_halo(p, 0.0)
        p.drawImage(self.star_rect_img(), self.star_img)
        p.end()
        return img

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
        x, y, size, kind = TINY[i]
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
        x, y, size, _ = TINY[i]
        r = size * 4 + 2
        return QRectF(x - r, y - r, 2 * r, 2 * r)

    # animation bookkeeping
    def start(self, key):
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
        date = f"{now.strftime('%A').lower()}, {now.strftime('%B').lower()} {now.day}"
        return t, ampm, date

    def date_image(self, date):
        if self.date_cache[0] != date:
            f = self.date_font
            l, t, r, b = f.getbbox(date)
            im = Image.new("RGBA", (r - l + 4, b - t + 4), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((2 - l, 2 - t), date, font=f, fill=(150, 153, 163, 255))
            self.date_cache = (date, pil_to_qimage(im, S))
        return self.date_cache[1]

    def draw_text(self, p, now):
        t, ampm, date = self.strings(now)
        track = -1.0
        gap = 3
        first = self.big.get(t[0])
        digit_top = self.big.get("0")["ink_t"]
        total = self.big.width(t, track) + (gap + self.small.width(ampm) if ampm else 0) - first["ink_l"]
        fit = min(1.0, TEXT_MAX_W / total)

        p.save()
        p.translate(PAD, TIME_TOP)
        p.scale(fit, fit)                        # only shrinks for very long times, like with seconds
        x = -first["ink_l"]                      # so the first digit's ink starts exactly at PAD
        self.big.draw(p, t, x, -digit_top, track)
        if ampm:
            self.small.draw(p, ampm, x + self.big.width(t, track) + gap, -digit_top)
        p.restore()

        # the date's ink also starts exactly at PAD, so both lines share one left edge
        p.drawImage(QPointF(PAD - 2 / S, DATE_TOP - 2 / S), self.date_image(date))

    def paint(self, p, now=None, clock=None):
        now = now or datetime.datetime.now()
        clock = time.monotonic() if clock is None else clock
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, W + 2 * M, H + 2 * M), self.shadow)
        p.translate(M, M)
        p.drawImage(QRectF(0, 0, W, H), self.base)
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


# ---------------------------------------------------------------- pause while a game is fullscreen
def fullscreen_app_open():
    """True when the app in front covers the whole monitor (a game, a fullscreen video)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.MonitorFromWindow.restype = wintypes.HANDLE
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]

        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return False
        name = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, name, 64)
        if name.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return False
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    except Exception:
        return False


# ---------------------------------------------------------------- open with Windows
def startup_command():
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else exe}" "{os.path.abspath(__file__)}"'


def run_key(write=False):
    import winreg
    access = winreg.KEY_ALL_ACCESS if write else winreg.KEY_READ
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, access)


def startup_enabled():
    try:
        import winreg
        with run_key() as k:
            winreg.QueryValueEx(k, RUN_NAME)
        return True
    except Exception:
        return False


def set_startup(on):
    import winreg
    with run_key(True) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------- window
def main():
    from PyQt6.QtWidgets import QApplication, QWidget, QMenu

    app = QApplication(sys.argv)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "aura_clock.lock"))
    if not lock.tryLock(100):
        return
    settings = QSettings("Aura", "Clock")

    class Widget(QWidget):
        def __init__(self):
            super().__init__()
            self.card = ClockCard()
            self.card.h24 = settings.value("h24", "false") == "true"
            self.card.seconds = settings.value("seconds", "false") == "true"
            self.scale = float(settings.value("scale", 1.0))
            self.on_top = settings.value("on_top", "false") == "true"
            self.sparkle_on = settings.value("sparkle", "true") == "true"
            self.paused_for_game = False
            self.drag = None
            self.apply_flags()
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.resize_to_scale()
            pos = settings.value("pos")
            if isinstance(pos, QPoint):
                self.move(pos)
            else:
                g = QGuiApplication.primaryScreen().availableGeometry()
                self.move(g.right() - self.width() - 20, g.top() + 20)

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
            now = datetime.datetime.now()
            if self.card.seconds:
                wait = 1000 - now.microsecond // 1000
            else:
                wait = (60 - now.second) * 1000 - now.microsecond // 1000
            self.timer.start(max(50, wait + 20))

        def animating_allowed(self):
            return self.sparkle_on and not self.paused_for_game

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
                free = [i for i in range(len(TINY)) if i not in self.card.effects]
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
            busy = fullscreen_app_open()
            if busy != self.paused_for_game:
                self.paused_for_game = busy
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
            self.setWindowFlags(flags)

        def resize_to_scale(self):
            self.setFixedSize(int((W + 2 * M) * self.scale), int((H + 2 * M) * self.scale))

        def paintEvent(self, e):
            p = QPainter(self)
            p.scale(self.scale, self.scale)
            self.card.paint(p)
            p.end()

        def mousePressEvent(self, e):
            if e.button() == Qt.MouseButton.LeftButton:
                self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

        def mouseMoveEvent(self, e):
            if self.drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
                self.move(e.globalPosition().toPoint() - self.drag)

        def mouseReleaseEvent(self, e):
            if self.drag is not None:
                self.drag = None
                settings.setValue("pos", self.pos())

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
                self.show()
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
