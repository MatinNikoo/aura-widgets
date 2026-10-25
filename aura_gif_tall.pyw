"""
Aura GIF  a rounded desktop card that loops your GIF forever.

Right click     choose a GIF, change speed, pause, and more
Drag            move the widget
Drag an edge    resize it (right edge, bottom edge, or bottom right corner)
Ctrl + drag     slide the GIF inside the card to pick which part shows
"""
import sys, os, shutil, tempfile, logging

from PIL import Image, ImageFilter
from PyQt6.QtCore import Qt, QRectF, QPoint, QLockFile, QSize, QTimer
from PyQt6.QtGui import (QPainter, QColor, QImage, QPainterPath, QFont,
                         QFontDatabase, QImageReader, QAction, QActionGroup, QCursor)

import aura_common
from aura_common import fullscreen_app_open
from aura_draw import readable, frame_delay, FrameClock, GifPlayer  # noqa: F401  (still importable from here)
from aura_draw import shape_path, shadow_pil, draw_border, render

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
DETAIL = 2             # frames are scaled to this many pixels per point; raised on very high DPI screens

APP_DIR = aura_common.APP_DIR
if STEM == "aura_gif":                       # the original keeps its old settings
    GIF_DIR, RUN_NAME, SETTINGS_KEY = os.path.join(APP_DIR, "gifs"), "AuraGifWidget", "Gif"
else:
    GIF_DIR, RUN_NAME, SETTINGS_KEY = os.path.join(APP_DIR, "gifs_" + STEM), "Aura_" + STEM, "Gif_" + STEM
LOCK_NAME = "aura_gif_widget.lock" if STEM == "aura_gif" else f"aura_{STEM}.lock"     # 1.0 used this name
os.makedirs(GIF_DIR, exist_ok=True)


def pil_to_qimage(im, premul=False):
    im = im.convert("RGBA")
    q = QImage(im.tobytes("raw", "RGBA"), im.width, im.height, im.width * 4,
               QImage.Format.Format_RGBA8888).copy()
    if premul:
        q = q.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return q


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


# ---------------------------------------------------------------- drawing
class GifCard:
    def __init__(self, w=DEFAULT_W, h=DEFAULT_H):
        self.w, self.h = w, h
        self.source = None       # last frame at full size
        self.frame = None        # last frame scaled for the card
        self.backdrop = None
        self.fit = False
        self.stretch = False
        self.pan = [0.5, 0.5]    # which part of the GIF shows when it's cropped (0 to 1)
        self.shape, self.radius, self.border = "rounded", RADIUS, "thin"
        self.shadow = None
        self.show_shadow = True
        self.rebuild_shadow()

    def apply(self, o):
        """Settings from the settings file (see aura_common.SCHEMA)."""
        reshape = (o["shape"], o["radius"]) != (self.shape, self.radius)
        refit = (o["mode"] == "fit", o["mode"] == "stretch") != (self.fit, self.stretch)
        self.shape, self.radius, self.border = o["shape"], o["radius"], o["border"]
        self.fit, self.stretch = o["mode"] == "fit", o["mode"] == "stretch"
        self.show_shadow = o["shadow"]
        if reshape:
            self.rebuild_shadow()
        if refit and self.source is not None:
            self.set_frame(self.source)

    def rebuild_shadow(self, sharp=True):
        s = 2 if sharp else 1
        q = pil_to_qimage(shadow_pil(self.w, self.h, M, self.shape, self.radius, 120, s), premul=True)
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
                else Qt.AspectRatioMode.IgnoreAspectRatio if self.stretch
                else Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        scaled = img.scaled(QSize(self.w * DETAIL, self.h * DETAIL), mode, Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(DETAIL)
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
        d = self.frame.devicePixelRatio()
        return max(0.0, self.frame.width() / d - self.w), max(0.0, self.frame.height() / d - self.h)

    def paint(self, p, empty_font=None):
        w, h = self.w, self.h
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.show_shadow:
            p.drawImage(QRectF(0, 0, w + 2 * M, h + 2 * M), self.shadow)
        p.translate(M, M)
        card = QRectF(0, 0, w, h)
        p.save()
        p.setClipPath(shape_path(self.shape, card, self.radius))
        p.fillRect(card, QColor(38, 36, 40))
        if self.frame is not None:
            d = self.frame.devicePixelRatio()
            fw, fh = self.frame.width() / d, self.frame.height() / d
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
            p.drawText(card, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       "Right click to add a GIF\nor drag one here")
        p.restore()
        draw_border(p, self.border, self.shape, w, h, self.radius)


# ---------------------------------------------------------------- preview for the settings window
def preview_image(o, settings=None, dpr=2):
    w = h = None
    path = ""
    if settings is not None:
        w = aura_common.num(settings, "w", DEFAULT_W, int)
        h = aura_common.num(settings, "h", DEFAULT_H, int)
        files = aura_common.gifs_in(o["folder"]) if o["folder"] else []
        path = files[0] if files else str(settings.value("gif", "") or "")
    w = max(MIN_W, min(MAX_W, w or DEFAULT_W))
    h = max(MIN_H, min(MAX_H, h or DEFAULT_H))
    if o["shape"] == "circle":
        w = h = min(w, h)
    card = GifCard(w, h)
    card.apply(o)
    if path and os.path.exists(path):
        first = QImageReader(path).read()
        card.set_frame(first)
        card.set_backdrop(first)
    else:
        from aura_draw import sample_cover
        im = sample_cover(400, seed=8).resize((400, 240))
        q = pil_to_qimage(im)
        card.set_frame(q)
        card.set_backdrop(q)
    font = pick_font(14, QFont.Weight.Medium)
    return render(lambda p: card.paint(p, font), w + 2 * M, h + 2 * M, dpr, o["opacity"])


# ---------------------------------------------------------------- open with Windows
def startup_command():
    return aura_common.startup_command(__file__)


def startup_enabled():
    return aura_common.startup_enabled(RUN_NAME)


def set_startup(on):
    aura_common.set_startup(RUN_NAME, on, __file__)


# ---------------------------------------------------------------- window
def main():
    from PyQt6.QtWidgets import QApplication, QWidget, QMenu, QFileDialog
    import aura_ui

    aura_common.setup_logging(STEM)
    app = QApplication(sys.argv)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), LOCK_NAME))
    if not lock.tryLock(100):
        return
    settings = aura_common.settings(SETTINGS_KEY)

    def num(key, default, cast=float):
        return aura_common.num(settings, key, default, cast)

    class Widget(QWidget):
        def __init__(self):
            super().__init__()
            self.card = GifCard(max(MIN_W, min(MAX_W, num("w", DEFAULT_W, int))),
                                max(MIN_H, min(MAX_H, num("h", DEFAULT_H, int))))
            self.opts = aura_common.options(settings, SETTINGS_KEY)
            self.card.apply(self.opts)
            self.card.pan = [num("pan_x", 0.5), num("pan_y", 0.5)]
            self.on_top = self.opts["on_top"]
            self.user_paused = self.opts["paused"]
            self.folder = self.opts["folder"]
            self.paused_for_game = False
            self.action = None          # "move", "pan" or "resize"
            self.edges = ""
            self.press = None
            self.font = pick_font(14, QFont.Weight.Medium)

            self.player = GifPlayer(self)
            self.player.set_speed(self.opts["speed"])
            self.player.frame.connect(self.on_frame)

            def default_spot(g):
                x = g.right() - self.width() - 20
                if TALL:                                   # start beside the wide one, not on top of it
                    x -= 440 + 2 * M
                return QPoint(x, g.bottom() - self.height() - 20)

            self.extras = aura_ui.Extras(
                self, settings, SETTINGS_KEY, "GIF" if STEM == "aura_gif" else STEM, STEM, RUN_NAME, __file__,
                default_spot, lambda: M, hold=self.set_held, held=lambda: self.user_paused,
                changed=self.apply_settings, refresh=self.check_game)
            self.square_for_circle()
            self.update_detail()
            app.screenAdded.connect(self.update_detail)
            app.screenRemoved.connect(self.update_detail)
            self.apply_flags()
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAcceptDrops(True)
            self.setMouseTracking(True)
            self.fit_window()
            self.extras.place()

            self.game_check = QTimer(self, interval=2000)
            self.game_check.timeout.connect(self.check_game)
            self.game_check.start()

            # optional: show every GIF in a folder, switching every few minutes
            self.rotate = QTimer(self)
            self.rotate.timeout.connect(self.next_from_folder)
            self.update_rotation()

            saved = settings.value("gif", "")
            if self.folder_files():
                self.next_from_folder()
            elif saved and os.path.exists(saved):
                self.load(saved)

        # window setup
        def apply_flags(self):
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            flags |= Qt.WindowType.WindowStaysOnTopHint if self.on_top else Qt.WindowType.WindowStaysOnBottomHint
            self.setWindowFlags(self.extras.flags(flags))

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
            if not readable(source):
                logging.warning("can't read %s, keeping the current GIF", source)
                return
            ext = os.path.splitext(source)[1].lower() or ".gif"
            dest = os.path.join(GIF_DIR, "current" + ext)
            incoming = os.path.join(GIF_DIR, "incoming" + ext)
            try:
                shutil.copyfile(source, incoming)     # keep a copy so moving the original doesn't break it
            except OSError:
                logging.exception("couldn't copy %s", source)
                return
            self.player.set_paused(True)
            self.player.path = self.player.reader = None    # let go of the old file so Windows can delete it
            for f in os.listdir(GIF_DIR):
                if f != os.path.basename(incoming):
                    try:
                        os.remove(os.path.join(GIF_DIR, f))
                    except OSError:
                        pass
            try:
                os.replace(incoming, dest)
            except OSError:
                logging.exception("couldn't rename the new GIF, using it as is")
                dest = incoming
            self.card.pan = [0.5, 0.5]
            self.save_pan()
            if self.load(dest):
                settings.setValue("gif", dest)
                if self.folder:
                    self.folder = ""
                    settings.setValue("folder", "")      # picking one GIF turns the folder off
                    self.update_rotation()

        def on_frame(self, img):
            self.card.set_frame(img)
            self.update(M, M, self.card.w + 1, self.card.h + 1)   # just the card, not the shadow

        def refresh_pause(self):
            self.player.set_paused(self.user_paused or self.paused_for_game)
            self.update_rotation()

        def set_held(self, on):
            self.user_paused = on
            settings.setValue("paused", "true" if on else "false")
            self.refresh_pause()

        # settings changed in the settings window (all optional, off by default)
        def apply_settings(self):
            request = str(settings.value("choose", "") or "")
            if request:                         # the settings window asks for a GIF this way
                settings.setValue("choose", "")
                settings.sync()
                self.choose(request)
            o = aura_common.options(settings, SETTINGS_KEY)
            old, self.opts = self.opts, o
            self.card.apply(o)
            if self.square_for_circle():
                self.fit_window()
            if o["speed"] != self.player.speed:
                self.set_speed(o["speed"], save=False)
            if o["paused"] != self.user_paused:
                self.user_paused = o["paused"]
                self.refresh_pause()
            if (o["on_top"], o["click_through"]) != (self.on_top, old["click_through"]):
                self.on_top = o["on_top"]
                self.apply_flags()
                self.extras.reshow()
            if o["folder"] != self.folder:
                self.folder = o["folder"]
                settings.setValue("folder_current", "")
                if self.folder_files():
                    self.next_from_folder()
                else:
                    saved = settings.value("gif", "")
                    if saved and os.path.exists(saved):
                        self.load(saved)
            if o["monitor"] != old["monitor"]:
                self.extras.place()
            self.update_rotation()
            self.update()

        def update_detail(self, *_):
            global DETAIL
            from PyQt6.QtGui import QGuiApplication
            d = aura_common.detail_for([s.devicePixelRatio() for s in QGuiApplication.screens()])
            if d != DETAIL:
                DETAIL = d
                if self.card.source is not None:
                    self.card.set_frame(self.card.source)
                self.update()

        def square_for_circle(self):
            """A circle needs a square card."""
            if self.opts["shape"] == "circle" and self.card.w != self.card.h:
                s = max(MIN_H, min(self.card.w, self.card.h))
                self.card.set_size(s, s)
                return True
            return False

        def folder_files(self):
            return aura_common.gifs_in(self.folder) if self.folder else []

        def update_rotation(self):
            every = self.opts["every"]
            on = bool(self.folder_files()) and every > 0 and not (self.user_paused or self.paused_for_game)
            if on and (not self.rotate.isActive() or self.rotate.interval() != every * 60_000):
                self.rotate.start(every * 60_000)
            elif not on:
                self.rotate.stop()

        def next_from_folder(self):
            files = self.folder_files()
            shuffle = self.opts["shuffle"]
            path = aura_common.next_gif(files, settings.value("folder_current", ""), shuffle)
            if path and self.load(path):
                settings.setValue("folder_current", path)
                self.update()

        def check_game(self):
            busy = fullscreen_app_open() or self.extras.hidden_all
            if busy != self.paused_for_game:
                self.paused_for_game = busy
                self.refresh_pause()

        def save_pan(self):
            settings.setValue("pan_x", self.card.pan[0])
            settings.setValue("pan_y", self.card.pan[1])

        # drawing
        def paintEvent(self, e):
            self.extras.paint(lambda p: self.card.paint(p, self.font))

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
            if e.button() != Qt.MouseButton.LeftButton or self.extras.locked:
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
                self.set_cursor_for("" if self.extras.locked else self.edges_at(e.position()))
                return
            g0, win0, w0, h0, pan0 = self.press
            d = e.globalPosition().toPoint() - g0
            if self.action == "move":
                self.move(self.extras.snap(win0 + d))
            elif self.action == "resize":
                w = w0 + d.x() if "r" in self.edges else w0
                h = h0 + d.y() if "b" in self.edges else h0
                w, h = max(MIN_W, min(MAX_W, w)), max(MIN_H, min(MAX_H, h))
                if self.opts["shape"] == "circle":
                    w = h = max(MIN_W, min(MAX_H, max(w, h) if self.edges == "rb" else (w if "r" in self.edges else h)))
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
                self.extras.remember()
            elif self.action == "resize":
                self.card.set_size(self.card.w, self.card.h, sharp=True)
                self.card.set_backdrop(self.player.first_frame())
                settings.setValue("w", self.card.w)
                settings.setValue("h", self.card.h)
                self.update()
            elif self.action == "pan":
                self.save_pan()
            self.action = None
            self.set_cursor_for("" if self.extras.locked else self.edges_at(e.position()))

        # right click menu
        def contextMenuEvent(self, e):
            menu = QMenu(self)
            pick = menu.addAction("Choose GIF")
            find = menu.addAction("Find a GIF in a folder")
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
            self.extras.settings_action(menu)
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
            elif chosen is find:
                self.find_gif()
            elif chosen is pause:
                self.user_paused = not self.user_paused
                settings.setValue("paused", "true" if self.user_paused else "false")
                self.refresh_pause()
            elif chosen is fit:
                self.opts["mode"] = "fill" if self.card.fit else "fit"
                settings.setValue("mode", self.opts["mode"])
                settings.setValue("fit", "true" if self.opts["mode"] == "fit" else "false")
                self.card.apply(self.opts)
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
                self.extras.reshow()
            elif chosen is boot:
                set_startup(not startup_enabled())
            elif chosen is quit_a:
                app.quit()

        def find_gif(self):
            import aura_library
            self.library = aura_library.GifLibrary(None)
            self.library.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
            self.library.chosen.connect(self.choose)
            self.library.show()

        def set_speed(self, v, save=True):
            self.player.set_speed(v)
            if save:
                settings.setValue("speed", v)
            if self.player.timer.isActive():       # apply right away instead of after the current frame
                self.player.timer.stop()
                self.player.next_frame()

    w = Widget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
