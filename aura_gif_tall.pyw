"""
Aura GIF  a rounded desktop card that loops your GIF forever.

Right click     choose a GIF, change speed, pause, and more
Drag            move the widget
Drag an edge    resize it (right edge, bottom edge, or bottom right corner)
Ctrl + drag     slide the GIF inside the card to pick which part shows
"""
import sys, os, shutil, tempfile

from PIL import Image, ImageFilter, ImageDraw
from PyQt6.QtCore import Qt, QRectF, QPointF, QSettings, QPoint, QLockFile, QSize, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import (QPainter, QColor, QImage, QPainterPath, QPen, QFont, QImageReader,
                         QGuiApplication, QFontDatabase, QAction, QActionGroup, QCursor)

# Each copy of this file is its own widget with its own GIF and settings, named after the file.
# aura_gif.pyw is the wide one; any copy with "tall" in its name starts out tall and narrow.
STEM = os.path.splitext(os.path.basename(__file__))[0]
TALL = "tall" in STEM.lower()
DEFAULT_W, DEFAULT_H = (270, 340) if TALL else (440, 160)
MIN_W, MIN_H = 180, 90
MAX_W, MAX_H = 1400, 900
M = 26                 # room around the card for the shadow
RADIUS = 26
EDGE = 10              # how close to an edge counts as grabbing it
SPEEDS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)

APP_DIR = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "Aura")
if STEM == "aura_gif":                       # the original keeps its old settings
    GIF_DIR, RUN_NAME, SETTINGS_KEY = os.path.join(APP_DIR, "gifs"), "AuraGifWidget", "Gif"
else:
    GIF_DIR, RUN_NAME, SETTINGS_KEY = os.path.join(APP_DIR, "gifs_" + STEM), "Aura_" + STEM, "Gif_" + STEM
os.makedirs(GIF_DIR, exist_ok=True)


def pil_to_qimage(im):
    im = im.convert("RGBA")
    return QImage(im.tobytes("raw", "RGBA"), im.width, im.height, im.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


def qimage_to_pil(img):
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(ptr), "raw", "RGBA",
                            img.bytesPerLine(), 1)


def rounded(rect, r):
    p = QPainterPath()
    p.addRoundedRect(rect, r, r)
    return p


def pick_font(size, weight):
    fams = set(QFontDatabase.families())
    name = next((n for n in ("Segoe UI Variable Display", "Segoe UI", "Inter") if n in fams), QFont().family())
    f = QFont(name)
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def fmt_speed(v):
    return f"{v:g}x"


# ---------------------------------------------------------------- GIF playback
class GifPlayer(QObject):
    """Plays a GIF frame by frame with its real timing, times a speed you choose."""
    frame = pyqtSignal(QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.reader = None
        self.speed = 1.0
        self.paused = False
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self.next_frame)

    def open(self, path):
        test = QImageReader(path)
        if not test.canRead():
            return False
        self.path = path
        self.reader = None
        self.timer.stop()
        self.next_frame()
        return True

    def first_frame(self):
        return QImageReader(self.path).read() if self.path else QImage()

    def next_frame(self):
        if self.path is None:
            return
        if self.reader is None or not self.reader.canRead():
            self.reader = QImageReader(self.path)       # back to the start, so it loops forever
        img = self.reader.read()
        if img.isNull():
            self.reader = QImageReader(self.path)
            img = self.reader.read()
            if img.isNull():
                return
        self.frame.emit(img)
        if self.reader.imageCount() == 1:
            return                                        # a still image, nothing to animate
        delay = self.reader.nextImageDelay()
        if delay <= 10:
            delay = 100       # same rule browsers use: GIFs that ask for 0 to 10 ms run at 100 ms
        if not self.paused:
            self.timer.start(max(10, int(delay / self.speed)))

    def set_speed(self, v):
        self.speed = v

    def set_paused(self, paused):
        self.paused = paused
        if paused:
            self.timer.stop()
        elif self.path and not self.timer.isActive():
            self.next_frame()


# ---------------------------------------------------------------- drawing
class GifCard:
    def __init__(self, w=DEFAULT_W, h=DEFAULT_H):
        self.w, self.h = w, h
        self.source = None       # last frame at full size
        self.frame = None        # last frame scaled for the card
        self.backdrop = None
        self.fit = False
        self.pan = [0.5, 0.5]    # which part of the GIF shows when it's cropped (0 to 1)
        self.shadow = None
        self.rebuild_shadow()

    def rebuild_shadow(self, sharp=True):
        s = 2 if sharp else 1
        w, h = self.w, self.h
        im = Image.new("RGBA", ((w + 2 * M) * s, (h + 2 * M) * s), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle(
            [M * s + 6, (M + 6) * s, (M + w) * s - 6, (M + h + 2) * s], radius=RADIUS * s, fill=(0, 0, 0, 120))
        q = pil_to_qimage(im.filter(ImageFilter.GaussianBlur(13 * s)))
        q.setDevicePixelRatio(s)
        self.shadow = q

    def set_size(self, w, h, sharp=True):
        self.w, self.h = w, h
        self.rebuild_shadow(sharp)
        if self.source is not None:
            self.set_frame(self.source)

    def set_frame(self, img):
        if img is None or img.isNull():
            self.source = self.frame = None
            return
        self.source = img
        mode = (Qt.AspectRatioMode.KeepAspectRatio if self.fit
                else Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        scaled = img.scaled(QSize(self.w * 2, self.h * 2), mode, Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(2)
        self.frame = scaled

    def set_backdrop(self, img):
        if img is None or img.isNull():
            self.backdrop = None
            return
        small = img.scaled(QSize(max(1, self.w // 5), max(1, self.h // 5)),
                           Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.backdrop = pil_to_qimage(qimage_to_pil(small).filter(ImageFilter.GaussianBlur(4)))

    def overflow(self):
        if self.frame is None:
            return 0.0, 0.0
        return max(0.0, self.frame.width() / 2 - self.w), max(0.0, self.frame.height() / 2 - self.h)

    def paint(self, p, empty_font=None):
        w, h = self.w, self.h
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, w + 2 * M, h + 2 * M), self.shadow)
        p.translate(M, M)
        card = QRectF(0, 0, w, h)
        p.save()
        p.setClipPath(rounded(card, RADIUS))
        p.fillRect(card, QColor(38, 36, 40))
        if self.frame is not None:
            fw, fh = self.frame.width() / 2, self.frame.height() / 2
            if self.fit:
                if self.backdrop is not None:
                    p.drawImage(card, self.backdrop)
                    p.fillRect(card, QColor(0, 0, 0, 70))
                x, y = (w - fw) / 2, (h - fh) / 2
            else:
                ox, oy = self.overflow()
                x, y = -ox * self.pan[0], -oy * self.pan[1]
            p.drawImage(QRectF(x, y, fw, fh), self.frame)
        elif empty_font is not None:
            p.setFont(empty_font)
            p.setPen(QColor(235, 232, 238, 200))
            p.drawText(card, Qt.AlignmentFlag.AlignCenter, "Right click to add a GIF\nor drag one here")
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(rounded(QRectF(0.5, 0.5, w - 1, h - 1), RADIUS - 0.5))


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
    from PyQt6.QtWidgets import QApplication, QWidget, QMenu, QFileDialog

    app = QApplication(sys.argv)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), f"aura_{STEM}.lock"))
    if not lock.tryLock(100):
        return
    settings = QSettings("Aura", SETTINGS_KEY)

    def num(key, default, cast=float):
        try:
            return cast(settings.value(key, default))
        except (TypeError, ValueError):
            return default

    class Widget(QWidget):
        def __init__(self):
            super().__init__()
            self.card = GifCard(num("w", DEFAULT_W, int), num("h", DEFAULT_H, int))
            self.card.fit = settings.value("fit", "false") == "true"
            self.card.pan = [num("pan_x", 0.5), num("pan_y", 0.5)]
            self.on_top = settings.value("on_top", "false") == "true"
            self.user_paused = settings.value("paused", "false") == "true"
            self.paused_for_game = False
            self.action = None          # "move", "pan" or "resize"
            self.edges = ""
            self.press = None
            self.font = pick_font(14, QFont.Weight.Medium)

            self.player = GifPlayer(self)
            self.player.set_speed(num("speed", 1.0))
            self.player.frame.connect(self.on_frame)

            self.apply_flags()
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAcceptDrops(True)
            self.setMouseTracking(True)
            self.fit_window()
            pos = settings.value("pos")
            if isinstance(pos, QPoint):
                self.move(pos)
            else:
                g = QGuiApplication.primaryScreen().availableGeometry()
                x = g.right() - self.width() - 20
                if TALL:                                   # start beside the wide one, not on top of it
                    x -= 440 + 2 * M
                self.move(x, g.bottom() - self.height() - 20)

            self.game_check = QTimer(self, interval=2000)
            self.game_check.timeout.connect(self.check_game)
            self.game_check.start()

            saved = settings.value("gif", "")
            if saved and os.path.exists(saved):
                self.load(saved)

        # window setup
        def apply_flags(self):
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            flags |= Qt.WindowType.WindowStaysOnTopHint if self.on_top else Qt.WindowType.WindowStaysOnBottomHint
            self.setWindowFlags(flags)

        def fit_window(self):
            self.setFixedSize(self.card.w + 2 * M, self.card.h + 2 * M)

        # GIF handling
        def load(self, path):
            if not self.player.open(path):
                return False
            self.card.set_backdrop(self.player.first_frame())
            self.player.set_paused(self.user_paused or self.paused_for_game)
            return True

        def choose(self, source):
            ext = os.path.splitext(source)[1].lower() or ".gif"
            dest = os.path.join(GIF_DIR, "current" + ext)
            self.player.set_paused(True)
            self.player.path = None
            for f in os.listdir(GIF_DIR):
                try:
                    os.remove(os.path.join(GIF_DIR, f))
                except OSError:
                    pass
            shutil.copyfile(source, dest)     # keep a copy so moving the original doesn't break it
            self.card.pan = [0.5, 0.5]
            self.save_pan()
            if self.load(dest):
                settings.setValue("gif", dest)

        def on_frame(self, img):
            self.card.set_frame(img)
            self.update(M, M, self.card.w + 1, self.card.h + 1)   # just the card, not the shadow

        def refresh_pause(self):
            self.player.set_paused(self.user_paused or self.paused_for_game)

        def check_game(self):
            busy = fullscreen_app_open()
            if busy != self.paused_for_game:
                self.paused_for_game = busy
                self.refresh_pause()

        def save_pan(self):
            settings.setValue("pan_x", self.card.pan[0])
            settings.setValue("pan_y", self.card.pan[1])

        # drawing
        def paintEvent(self, e):
            p = QPainter(self)
            self.card.paint(p, self.font)
            p.end()

        # drag and drop a GIF onto the card
        def dragEnterEvent(self, e):
            if e.mimeData().hasUrls():
                e.acceptProposedAction()

        def dropEvent(self, e):
            for url in e.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith((".gif", ".webp")):
                    self.choose(path)
                    break

        # mouse: move, resize, slide the GIF
        def edges_at(self, pos):
            x, y = pos.x() - M, pos.y() - M
            w, h = self.card.w, self.card.h
            if not (-EDGE <= x <= w + EDGE and -EDGE <= y <= h + EDGE):
                return ""
            e = ""
            if abs(x - w) <= EDGE:
                e += "r"
            if abs(y - h) <= EDGE:
                e += "b"
            return e

        def set_cursor_for(self, edges):
            shapes = {"r": Qt.CursorShape.SizeHorCursor, "b": Qt.CursorShape.SizeVerCursor,
                      "rb": Qt.CursorShape.SizeFDiagCursor}
            self.setCursor(QCursor(shapes.get(edges, Qt.CursorShape.ArrowCursor)))

        def mousePressEvent(self, e):
            if e.button() != Qt.MouseButton.LeftButton:
                return
            pos = e.position()
            self.edges = self.edges_at(pos)
            self.press = (e.globalPosition().toPoint(), self.pos(), self.card.w, self.card.h, list(self.card.pan))
            if self.edges:
                self.action = "resize"
            elif e.modifiers() & Qt.KeyboardModifier.ControlModifier and not self.card.fit:
                self.action = "pan"
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            else:
                self.action = "move"

        def mouseMoveEvent(self, e):
            if self.action is None:
                self.set_cursor_for(self.edges_at(e.position()))
                return
            g0, win0, w0, h0, pan0 = self.press
            d = e.globalPosition().toPoint() - g0
            if self.action == "move":
                self.move(win0 + d)
            elif self.action == "resize":
                w = w0 + d.x() if "r" in self.edges else w0
                h = h0 + d.y() if "b" in self.edges else h0
                w, h = max(MIN_W, min(MAX_W, w)), max(MIN_H, min(MAX_H, h))
                if (w, h) != (self.card.w, self.card.h):
                    self.card.set_size(w, h, sharp=False)
                    self.fit_window()
                    self.update()
            elif self.action == "pan":
                ox, oy = self.card.overflow()
                self.card.pan = [min(1, max(0, pan0[0] - d.x() / ox)) if ox else 0.5,
                                 min(1, max(0, pan0[1] - d.y() / oy)) if oy else 0.5]
                self.update()

        def mouseReleaseEvent(self, e):
            if self.action == "move":
                settings.setValue("pos", self.pos())
            elif self.action == "resize":
                self.card.set_size(self.card.w, self.card.h, sharp=True)
                self.card.set_backdrop(self.player.first_frame())
                settings.setValue("w", self.card.w)
                settings.setValue("h", self.card.h)
                self.update()
            elif self.action == "pan":
                self.save_pan()
            self.action = None
            self.set_cursor_for(self.edges_at(e.position()))

        # right click menu
        def contextMenuEvent(self, e):
            menu = QMenu(self)
            pick = menu.addAction("Choose GIF")
            pause = menu.addAction("Play GIF" if self.user_paused else "Pause GIF")
            speed_menu = menu.addMenu(f"Speed  ({fmt_speed(self.player.speed)})")
            group = QActionGroup(speed_menu)
            for v in SPEEDS:
                a = QAction(fmt_speed(v) + ("  normal" if v == 1.0 else ""), speed_menu, checkable=True,
                            checked=abs(self.player.speed - v) < 0.001)
                a.triggered.connect(lambda _, v=v: self.set_speed(v))
                group.addAction(a)
                speed_menu.addAction(a)
            menu.addSeparator()
            fit = QAction("Show whole GIF", menu, checkable=True, checked=self.card.fit)
            menu.addAction(fit)
            center = menu.addAction("Center the GIF")
            center.setEnabled(not self.card.fit and self.card.pan != [0.5, 0.5])
            reset = menu.addAction("Reset size")
            menu.addSeparator()
            top = QAction("Keep on top of windows", menu, checkable=True, checked=self.on_top)
            boot = QAction("Open when my PC starts", menu, checkable=True, checked=startup_enabled())
            menu.addAction(top)
            menu.addAction(boot)
            menu.addSeparator()
            quit_a = menu.addAction("Close widget")

            chosen = menu.exec(e.globalPos())
            if chosen is pick:
                path, _ = QFileDialog.getOpenFileName(self, "Choose a GIF", os.path.expanduser("~"),
                                                      "GIFs (*.gif *.webp)")
                if path:
                    self.choose(path)
            elif chosen is pause:
                self.user_paused = not self.user_paused
                settings.setValue("paused", "true" if self.user_paused else "false")
                self.refresh_pause()
            elif chosen is fit:
                self.card.fit = not self.card.fit
                settings.setValue("fit", "true" if self.card.fit else "false")
                if self.card.source is not None:
                    self.card.set_frame(self.card.source)
                self.update()
            elif chosen is center:
                self.card.pan = [0.5, 0.5]
                self.save_pan()
                self.update()
            elif chosen is reset:
                self.card.set_size(DEFAULT_W, DEFAULT_H)
                self.card.set_backdrop(self.player.first_frame())
                self.fit_window()
                settings.setValue("w", DEFAULT_W)
                settings.setValue("h", DEFAULT_H)
                self.update()
            elif chosen is top:
                self.on_top = not self.on_top
                settings.setValue("on_top", "true" if self.on_top else "false")
                self.apply_flags()
                self.show()
            elif chosen is boot:
                set_startup(not startup_enabled())
            elif chosen is quit_a:
                app.quit()

        def set_speed(self, v):
            self.player.set_speed(v)
            settings.setValue("speed", v)
            if self.player.timer.isActive():       # apply right away instead of after the current frame
                self.player.timer.stop()
                self.player.next_frame()

    w = Widget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
