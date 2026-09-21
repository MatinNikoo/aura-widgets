"""
Aura  a now playing widget for Windows.
Album art dissolves into a rounded card tinted with the cover's own colors.
Reads what's playing through Windows' media controls, so no Spotify login is needed.

Right click the widget for options. Drag it anywhere.
"""
import sys, os, io, time, asyncio, threading, colorsys, datetime, logging, tempfile

from PIL import Image, ImageFilter, ImageDraw
from PyQt6.QtCore import (Qt, QTimer, QPointF, QRectF, QObject, pyqtSignal, QVariantAnimation,
                          QEasingCurve, QSettings, QPoint, QLockFile)
from PyQt6.QtGui import (QPainter, QColor, QImage, QPainterPath, QLinearGradient, QFont,
                         QFontMetricsF, QPen, QGuiApplication, QFontDatabase, QAction)

# ---------------------------------------------------------------- layout
W, H = 400, 132          # card size (logical px)
M = 26                   # room around the card for the shadow
RADIUS = 26
ART = H                  # album art is a square as tall as the card
PAD_R = 24
TEXT_X = ART + 8

LOG_DIR = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "Aura")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(filename=os.path.join(LOG_DIR, "log.txt"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")


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


def pil_to_qimage(im):
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    return QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()


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
class Track:
    def __init__(self, title, artist, cover_bytes=None):
        self.title, self.artist = title or "", artist or ""
        self.cover = self.blur = None
        self.colors = dict(NEUTRAL)
        if cover_bytes:
            try:
                im = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
                w, h = im.size
                s = min(w, h)
                im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
                self.cover = pil_to_qimage(im.resize((ART * 2, ART * 2), Image.Resampling.LANCZOS))
                self.blur = pil_to_qimage(im.resize((W // 5, H // 5)).filter(ImageFilter.GaussianBlur(5)))
                self.colors = palette_from(im)
            except Exception:
                logging.exception("cover decode failed")
        self.layer = self._build_layer()

    def _build_layer(self):
        """Everything that doesn't move: box color, blurred glow, and the fading album art."""
        img = QImage(W * 2, H * 2, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(2)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = QRectF(0, 0, W, H)
        p.setClipPath(rounded(card, RADIUS))
        p.fillRect(card, self.colors["bg"])
        if self.blur is not None:
            p.setOpacity(0.7)
            p.drawImage(card, self.blur)
            p.setOpacity(1)
            p.fillRect(card, with_alpha(self.colors["bg"], 165))
        if self.cover is not None:
            art = QImage(self.cover)
            art.setDevicePixelRatio(2)
            ap = QPainter(art)
            ap.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            g = QLinearGradient(0, 0, ART, 0)
            for stop, a in ((0.0, 255), (0.30, 255), (0.45, 228), (0.60, 165), (0.75, 88), (0.88, 30), (1.0, 0)):
                g.setColorAt(stop, QColor(0, 0, 0, a))
            ap.fillRect(QRectF(0, 0, ART, ART), g)
            ap.end()
            p.drawImage(QRectF(0, 0, ART, H), art)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(rounded(QRectF(0.5, 0.5, W - 1, H - 1), RADIUS - 0.5))
        p.end()
        return img


class Card:
    """Draws the widget. Kept separate from the window so it can render previews too."""

    def __init__(self):
        self.cur = Track("Nothing playing", "Play a song in Spotify")
        self.old = None
        self.t = 1.0              # crossfade progress between old and cur
        self.hover = 0.0
        self.pos_ms = self.dur_ms = 0
        self.anchor = time.monotonic()
        self.playing = False
        self.hit = {}
        self.f_title = pick_font(16, QFont.Weight.DemiBold)
        self.f_artist = pick_font(13, QFont.Weight.Normal)
        self.f_time = pick_font(11, QFont.Weight.Medium)
        self.shadow = self._make_shadow()

    def _make_shadow(self):
        s = 2
        im = Image.new("RGBA", ((W + 2 * M) * s, (H + 2 * M) * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([M * s + 6, (M + 6) * s, (M + W) * s - 6, (M + H + 2) * s],
                            radius=RADIUS * s, fill=(0, 0, 0, 120))
        q = pil_to_qimage(im.filter(ImageFilter.GaussianBlur(13 * s)))
        q.setDevicePixelRatio(s)
        return q

    def position(self):
        if self.playing:
            return min(self.dur_ms, self.pos_ms + (time.monotonic() - self.anchor) * 1000)
        return self.pos_ms

    def colors(self):
        if self.old is None:
            return self.cur.colors
        return {k: mix(self.old.colors[k], self.cur.colors[k], self.t) for k in self.cur.colors}

    def paint(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.drawImage(QRectF(0, 0, W + 2 * M, H + 2 * M), self.shadow)
        p.translate(M, M)

        if self.old is not None:
            p.drawImage(QRectF(0, 0, W, H), self.old.layer)
            p.setOpacity(self.t)
        p.drawImage(QRectF(0, 0, W, H), self.cur.layer)
        p.setOpacity(1)

        if self.old is not None:
            self._text(p, self.old, 1 - self.t)
        self._text(p, self.cur, self.t if self.old is not None else 1)

        c = self.colors()
        x, right = TEXT_X, W - PAD_R
        if self.dur_ms > 0:
            frac = max(0.0, min(1.0, self.position() / self.dur_ms))
            bar = QRectF(x, 87, right - x, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(with_alpha(c["bar"], 60))
            p.drawRoundedRect(bar, 2, 2)
            if frac > 0:
                p.setBrush(c["bar"])
                p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(4, bar.width() * frac), 4), 2, 2)
            p.setFont(self.f_time)
            p.setPen(with_alpha(c["sub"], 170))
            p.drawText(QPointF(x, 111), fmt(self.position()))
            end = fmt(self.dur_ms)
            p.drawText(QPointF(right - QFontMetricsF(self.f_time).horizontalAdvance(end), 111), end)

        self._controls(p, c)

    def _text(self, p, tr, alpha):
        if alpha <= 0.01:
            return
        x, avail = TEXT_X, W - PAD_R - TEXT_X
        fm_t, fm_a = QFontMetricsF(self.f_title), QFontMetricsF(self.f_artist)
        p.setFont(self.f_title)
        p.setPen(with_alpha(tr.colors["text"], 255 * alpha))
        p.drawText(QPointF(x, 49), fm_t.elidedText(tr.title, Qt.TextElideMode.ElideRight, avail))
        p.setFont(self.f_artist)
        p.setPen(with_alpha(tr.colors["sub"], tr.colors["sub"].alpha() * alpha))
        p.drawText(QPointF(x, 69), fm_a.elidedText(tr.artist, Qt.TextElideMode.ElideRight, avail))

    def _controls(self, p, c):
        self.hit = {}
        if self.hover <= 0.01 or self.dur_ms <= 0:
            return
        col = with_alpha(c["text"], 235 * self.hover)
        cx = TEXT_X + (W - PAD_R - TEXT_X) / 2
        cy = 107
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        for name, dx in (("prev", -30), ("toggle", 0), ("next", 30)):
            ox = cx + dx
            self.hit[name] = QRectF(ox - 13, cy - 13, 26, 26)
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
    timeline = pyqtSignal(object)   # (pos_ms, dur_ms, playing)
    error = pyqtSignal(str)


def to_ms(v):
    if v is None:
        return 0
    if hasattr(v, "total_seconds"):
        return v.total_seconds() * 1000
    return float(v) / 10_000      # 100 ns ticks


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

    def command(self, name):
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(self._command(name), self.loop)

    async def _command(self, name):
        try:
            s = self.session()
            if s is None:
                return
            if name == "toggle":
                await s.try_toggle_play_pause_async()
            elif name == "next":
                await s.try_skip_next_async()
            elif name == "prev":
                await s.try_skip_previous_async()
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
        stream = await ref.open_read_async()
        size = int(stream.size)
        if size <= 0:
            return None
        buf = await stream.read_async(Buffer(size), size, InputStreamOptions.READ_AHEAD)
        try:
            return bytes(buf)
        except TypeError:
            reader = DataReader.from_buffer(buf)
            out = bytearray(buf.length)
            reader.read_bytes(out)
            return bytes(out)

    async def main(self):
        # imported here so Windows media stays on this thread and doesn't clash with the window
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status)
        self.mgr = await Manager.request_async()
        last_key, have_cover = "none", True
        while True:
            try:
                s = self.session()
                if self.resting:
                    await asyncio.sleep(3)
                    continue
                if s is None:
                    if last_key is not None:
                        self.bridge.track.emit(None)
                        self.bridge.timeline.emit((0, 0, False))
                    last_key = None
                else:
                    props = await s.try_get_media_properties_async()
                    key = (props.title, props.artist)
                    if key != last_key or not have_cover:
                        cover = None
                        for attempt in range(4):
                            if key != last_key and attempt == 0:
                                await asyncio.sleep(0.35)   # cover art lags a moment behind the title
                                props = await s.try_get_media_properties_async()
                                key = (props.title, props.artist)
                            if props.thumbnail is not None:
                                try:
                                    cover = await self.read_cover(props.thumbnail)
                                except Exception:
                                    logging.exception("cover read failed")
                            if cover or key == last_key:
                                break
                            await asyncio.sleep(0.4)
                            props = await s.try_get_media_properties_async()
                        if key != last_key or cover:
                            self.bridge.track.emit((props.title, props.artist, cover))
                        last_key, have_cover = key, cover is not None

                    tl = s.get_timeline_properties()
                    playing = s.get_playback_info().playback_status == Status.PLAYING
                    pos, dur = to_ms(tl.position), to_ms(tl.end_time)
                    if playing:
                        try:
                            ago = (datetime.datetime.now(datetime.timezone.utc)
                                   - tl.last_updated_time).total_seconds() * 1000
                            if 0 < ago < dur:
                                pos += ago
                        except Exception:
                            pass
                    self.bridge.timeline.emit((pos, dur, playing))
            except Exception:
                logging.exception("poll failed")
            await asyncio.sleep(0.8 if last_key is not None else 2.0)


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
            return False          # that's the desktop or taskbar, not an app
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


# ---------------------------------------------------------------- the window
def startup_command():
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else exe}" "{os.path.abspath(__file__)}"'


def set_startup(on):
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
    try:
        if on:
            winreg.SetValueEx(key, "AuraWidget", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, "AuraWidget")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def startup_enabled():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, "AuraWidget")
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def main():
    from PyQt6.QtWidgets import QApplication, QWidget, QMenu

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "aura_widget.lock"))
    if not lock.tryLock(100):
        return   # already running

    settings = QSettings("Aura", "Widget")

    class Widget(QWidget):
        def __init__(self):
            super().__init__()
            self.card = Card()
            self.scale = float(settings.value("scale", 1.0))
            self.on_top = settings.value("on_top", "false") == "true"
            self.drag = None
            self.apply_flags()
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setMouseTracking(True)
            self.resize_to_scale()
            pos = settings.value("pos")
            if isinstance(pos, QPoint):
                self.move(pos)
            else:
                g = QGuiApplication.primaryScreen().availableGeometry()
                self.move(g.left() + 20, g.bottom() - self.height() - 20)

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
            self.setWindowFlags(flags)

        def resize_to_scale(self):
            self.setFixedSize(int((W + 2 * M) * self.scale), int((H + 2 * M) * self.scale))

        # data coming in
        def on_track(self, data):
            new = Track(*data) if data else Track("Nothing playing", "Play a song in Spotify")
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
            pos, dur, playing = data
            # ignore tiny jitter so the bar never jumps backwards
            if not (playing and self.card.playing and abs(self.card.position() - pos) < 1500):
                self.card.pos_ms, self.card.anchor = pos, time.monotonic()
            self.card.dur_ms, self.card.playing = dur, playing
            self.update_ticking()
            self.update()

        def update_ticking(self):
            if self.card.playing and not self.paused_for_game:
                if not self.tick.isActive():
                    self.tick.start()
            else:
                self.tick.stop()

        def check_game(self):
            busy = fullscreen_app_open()
            if busy != self.paused_for_game:
                self.paused_for_game = busy
                self.worker.resting = busy
                self.update_ticking()

        def on_error(self, msg):
            self.card.old, self.card.cur = self.card.cur, Track("Setup needed", "Run install.bat, then open me again")
            self.card.t = 0
            self.fade.start()

        # drawing
        def paintEvent(self, e):
            p = QPainter(self)
            p.scale(self.scale, self.scale)
            self.card.paint(p)
            p.end()

        def to_card(self, pos):
            return QPointF(pos.x() / self.scale - M, pos.y() / self.scale - M)

        # mouse
        def enterEvent(self, e):
            self.hover_anim.stop(); self.hover_anim.setStartValue(self.card.hover)
            self.hover_anim.setEndValue(1.0); self.hover_anim.start()

        def leaveEvent(self, e):
            self.hover_anim.stop(); self.hover_anim.setStartValue(self.card.hover)
            self.hover_anim.setEndValue(0.0); self.hover_anim.start()

        def mousePressEvent(self, e):
            if e.button() != Qt.MouseButton.LeftButton:
                return
            pt = self.to_card(e.position())
            for name, r in self.card.hit.items():
                if r.contains(pt):
                    self.worker.command(name)
                    if name == "toggle":
                        self.card.pos_ms, self.card.anchor = self.card.position(), time.monotonic()
                        self.card.playing = not self.card.playing
                        self.update_ticking()
                    return
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
            top = QAction("Keep on top of windows", menu, checkable=True, checked=self.on_top)
            boot = QAction("Open when my PC starts", menu, checkable=True, checked=startup_enabled())
            menu.addAction(top); menu.addAction(boot)
            size_menu = menu.addMenu("Size")
            for label, val in (("Small", 0.8), ("Medium", 1.0), ("Large", 1.25)):
                a = QAction(label, size_menu, checkable=True, checked=abs(self.scale - val) < 0.01)
                a.triggered.connect(lambda _, v=val: self.set_scale(v))
                size_menu.addAction(a)
            menu.addSeparator()
            quit_a = menu.addAction("Close widget")
            chosen = menu.exec(e.globalPos())
            if chosen is top:
                self.on_top = not self.on_top
                settings.setValue("on_top", "true" if self.on_top else "false")
                self.apply_flags(); self.show()
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
