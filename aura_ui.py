"""
Optional extras every widget can use: a tray icon, lock and click through, opacity, pinning to a
monitor, remembering a spot on each monitor, snapping, a hotkey that hides every widget, and picking
up changes from the settings window. Everything here is off by default, so a widget looks and acts
the same until you turn something on.
"""
import os, json, time, logging

from PyQt6.QtCore import Qt, QObject, QPoint, QRectF, QUrl, QFileSystemWatcher, QTimer
from PyQt6.QtGui import (QAction, QColor, QDesktopServices, QGuiApplication, QIcon, QImage, QPainter,
                         QPixmap, QPainterPath)
from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QMenu, QPushButton, QSystemTrayIcon, QVBoxLayout

import aura_common
import aura_hotkey
from aura_common import pick_spot, screen_at, visible


def flag(settings, key, default=False):
    return str(settings.value(key, "true" if default else "false")).lower() == "true"


def screens():
    """[(name, geometry, available geometry)] with the primary monitor first."""
    primary = QGuiApplication.primaryScreen()
    out = []
    for s in QGuiApplication.screens():
        item = (s.name(), s.geometry(), s.availableGeometry())
        out.insert(0, item) if s is primary else out.append(item)
    return out


def tray_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(4, 4, 56, 56), 16, 16)
    p.fillPath(path, QColor(38, 36, 40))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(236, 238, 244))
    p.drawEllipse(QRectF(22, 22, 20, 20))
    p.end()
    return QIcon(pm)


class Extras(QObject):
    """
    widget        the QWidget it belongs to
    settings      its QSettings, and key, the settings file name ("Widget", "Clock", "Gif", ...)
    title         shown in the tray ("Now playing", "Clock", ...)
    name          log file name
    run_name      the Run key name used for opening with Windows
    script        path of the widget's .pyw
    default_spot  function(available QRect) -> QPoint, where the widget goes by default on a monitor
    margin        function() -> px of shadow around the card, so only the card has to be on screen
    hold          function(bool), pauses or resumes the widget (for the tray), optional
    held          function() -> bool, optional
    changed       function() called when the settings file changes, optional
    refresh       function() called when the widget gets hidden or shown, so it can pause itself, optional
    """

    def __init__(self, widget, settings, key, title, name, run_name, script, default_spot, margin,
                 hold=None, held=None, changed=None, refresh=None):
        super().__init__(widget)
        self.w, self.s, self.key = widget, settings, key
        self.title, self.name, self.run_name, self.script = title, name, run_name, script
        self.default_spot, self.margin = default_spot, margin
        self.hold, self.held, self.changed, self.refresh = hold, held, changed, refresh
        self.tray = None
        self.auto = False           # true while the widget sits in a fallback spot it picked by itself
        self.buffer = None
        self.general = aura_common.settings("General")
        if not self.general.contains("version"):
            self.general.setValue("version", aura_common.__version__)      # so the file exists to be watched
            self.general.sync()
        self.hidden_all = False     # hidden with the hotkey or the tray, shared by every widget
        self.hidden_seen = str(self.general.value("hidden_at", ""))     # a flag left over from last time is ignored
        self.idle = False           # the widget has nothing to show right now (set by the widget itself)
        self.moved_seen = str(self.s.value("move_token", ""))
        self.cards = (0.0, [])      # when the other widgets' rectangles were last read, and what they were
        app = QGuiApplication.instance()
        app.screenAdded.connect(self.screens_changed)
        app.screenRemoved.connect(self.screens_changed)
        self.update_tray()

        # the settings window writes the file, so watch it and apply changes live
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self.file_changed)
        self.watcher.directoryChanged.connect(self.file_changed)
        self.watch()
        self.debounce = QTimer(self, singleShot=True, interval=150)
        self.debounce.timeout.connect(self.reload)

        self.hotkey = aura_hotkey.Hotkey(self)
        self.hotkey.pressed.connect(self.toggle_all)
        self.apply_general()
        QGuiApplication.instance().aboutToQuit.connect(self.goodbye)
        self.fresh = not self.s.contains("pos") and not os.environ.get("AURA_NO_WELCOME")
        if self.fresh:
            QTimer.singleShot(1500, self.welcome)

    def welcome(self):
        """On the very first run, a small note on where everything is. It shows once, for the first widget."""
        self.general.sync()
        if str(self.general.value("welcomed", "")) or not self.w.isVisible():
            return
        self.general.setValue("welcomed", "true")
        self.general.sync()
        self.welcome_window = Welcome(self)
        self.welcome_window.show()

    def watch(self):
        """Only this widget's own file and the shared General file are watched, so another widget
        saving doesn't wake this one. The folder is watched just until the files exist."""
        folder = os.path.dirname(self.s.fileName())
        missing = False
        for path in (self.s.fileName(), self.general.fileName()):
            if os.path.exists(path):
                if path not in self.watcher.files():
                    self.watcher.addPath(path)
            else:
                missing = True
        if missing and os.path.isdir(folder) and folder not in self.watcher.directories():
            self.watcher.addPath(folder)
        elif not missing and folder in self.watcher.directories():
            self.watcher.removePath(folder)

    def file_changed(self, *_):
        self.debounce.start()

    def reload(self):
        self.watch()                # some editors replace the file, which drops the watch
        self.s.sync()
        self.general.sync()
        self.update_tray()
        self.apply_general()
        token = str(self.s.value("move_token", ""))
        if token != self.moved_seen:
            self.moved_seen = token
            self.place()
        if self.changed:
            self.changed()
        self.w.update()

    # ---------------------------------------------------------------- hide every widget, hotkey
    def apply_general(self):
        """The shared settings, mostly the hotkey, and whether the widgets are hidden right now."""
        self.hotkey.set(str(self.general.value("hotkey", "Ctrl+Alt+A")) if flag(self.general, "hotkey_on") else "")
        stamp = str(self.general.value("hidden_at", ""))
        if stamp != self.hidden_seen:
            self.hidden_seen = stamp
            hidden = str(self.general.value("hidden", "false")).lower() == "true"
            if hidden != self.hidden_all:
                self.hidden_all = hidden
                self.show_or_hide()

    def toggle_all(self):
        self.set_hidden_all(not self.hidden_all)

    def set_hidden_all(self, hidden):
        """Hides or shows every widget. This one answers to its own state, so the key always does
        something, even if the last session ended with the widgets hidden."""
        aura_common.set_hidden(hidden)
        self.general.sync()
        self.hidden_seen = str(self.general.value("hidden_at", ""))
        self.hidden_all = hidden
        self.show_or_hide()

    def wanted(self):
        return not self.hidden_all and not self.idle

    def show_or_hide(self):
        if self.wanted() != self.w.isVisible():
            self.w.setVisible(self.wanted())
        if self.refresh:
            self.refresh()          # the widget pauses itself while hidden, like it does for a fullscreen game

    def reshow(self):
        """Show again after the window flags changed, without bringing back a hidden widget."""
        if self.wanted():
            self.w.show()

    def set_idle(self, idle):
        if idle != self.idle:
            self.idle = idle
            self.show_or_hide()

    def goodbye(self):
        """A closed widget stops being something others snap to."""
        self.s.remove("rect")
        self.s.sync()
    # ---------------------------------------------------------------- settings
    @property
    def opacity(self):
        return max(0.2, min(1.0, aura_common.num(self.s, "opacity", 1.0)))

    @property
    def locked(self):
        return flag(self.s, "locked")

    @property
    def click_through(self):
        return flag(self.s, "click_through")

    @property
    def shadow(self):
        return flag(self.s, "shadow", True)

    @property
    def snaps(self):
        return flag(self.s, "snap")

    @property
    def pinned(self):
        return str(self.s.value("monitor", "") or "")

    def spots(self):
        try:
            d = json.loads(self.s.value("spots", "{}") or "{}")
            return {k: (int(v[0]), int(v[1])) for k, v in d.items()}
        except (TypeError, ValueError, IndexError, AttributeError):
            return {}

    def set(self, key, value):
        self.s.setValue(key, value)
        self.s.sync()
        if self.changed:
            self.changed()

    # ---------------------------------------------------------------- window flags and drawing
    def flags(self, base):
        if self.click_through:
            base |= Qt.WindowType.WindowTransparentForInput
        return base

    def paint(self, draw):
        """draw(painter) paints the widget. With opacity below 100% it goes through a buffer first,
        since the cards change the painter's opacity themselves for their fades."""
        op = self.opacity
        if op >= 0.999:
            p = QPainter(self.w)
            draw(p)
            p.end()
            return
        dpr = self.w.devicePixelRatioF()
        size = self.w.size() * dpr
        if self.buffer is None or self.buffer.size() != size:
            self.buffer = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        self.buffer.setDevicePixelRatio(dpr)
        self.buffer.fill(Qt.GlobalColor.transparent)
        bp = QPainter(self.buffer)
        draw(bp)
        bp.end()
        p = QPainter(self.w)
        p.setOpacity(op)
        p.drawImage(0, 0, self.buffer)
        p.end()

    # ---------------------------------------------------------------- position
    def place(self):
        """Put the widget where it belongs: its pinned monitor, its last spot, or its spot on
        another monitor if the last one is unplugged."""
        sc = screens()
        if not sc:
            return
        saved = self.s.value("pos")
        saved = (saved.x(), saved.y()) if isinstance(saved, QPoint) else None
        defaults = [(lambda q: (q.x(), q.y()))(self.default_spot(avail)) for _, _, avail in sc]
        (x, y), why = pick_spot(saved, self.pinned, self.spots(), [(n, g.getRect()) for n, g, _ in sc],
                                defaults, (self.w.width(), self.w.height()), self.margin())
        self.w.move(x, y)
        self.auto = why in ("remembered", "default") and saved is not None
        if self.auto:
            logging.info("last position is off screen, moved to the %s spot", why)
        self.publish_rect()

    def card_rect(self, pos=None):
        pos = pos or self.w.pos()
        m = int(self.margin())
        return pos.x() + m, pos.y() + m, self.w.width() - 2 * m, self.w.height() - 2 * m

    def publish_rect(self):
        """Other widgets read this to snap to this one."""
        self.s.setValue("rect", ",".join(str(v) for v in self.card_rect()))

    def snap(self, pos):
        """Where a dragged widget should really go, given where the mouse puts it."""
        if not self.snaps or QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
            return pos
        now = time.monotonic()
        if now - self.cards[0] > 2:
            self.cards = (now, aura_common.other_cards(self.key))
        x, y, w, h = self.card_rect(pos)
        dx, dy = aura_common.snap_offset((x, y, w, h), [a.getRect() for _, _, a in screens()], self.cards[1])
        return QPoint(pos.x() + dx, pos.y() + dy)

    def reset_position(self):
        """Back to the default spot on the monitor the widget is pinned to, or the main one."""
        self.s.remove("pos")
        self.s.remove("spots")
        self.s.sync()
        self.place()

    def remember(self):
        """Call after the user drags the widget."""
        pos = self.w.pos()
        self.s.setValue("pos", pos)
        sc = screens()
        center = self.w.frameGeometry().center()
        name = screen_at((center.x(), center.y()), [(n, g.getRect()) for n, g, _ in sc])
        if name:
            g = next(g for n, g, _ in sc if n == name)
            spots = self.spots()
            spots[name] = (pos.x() - g.x(), pos.y() - g.y())
            self.s.setValue("spots", json.dumps(spots))
            if self.pinned and self.pinned != name:
                self.s.setValue("monitor", name)       # dragged to another monitor, so it's pinned there now
        self.auto = False
        self.publish_rect()

    def screens_changed(self, *_):
        rects = [g.getRect() for _, g, _ in screens()]
        m = self.margin()
        r = (self.w.x() + m, self.w.y() + m, self.w.width() - 2 * m, self.w.height() - 2 * m)
        if self.auto or not visible(r, rects):
            self.place()

    # ---------------------------------------------------------------- tray
    def update_tray(self):
        want = flag(self.s, "tray") or self.click_through        # click through needs a way back
        if want and self.tray is None:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                logging.info("no system tray here")
            self.tray = QSystemTrayIcon(tray_icon(), self)
            self.tray.setToolTip("Aura " + self.title)
            self.tray.setContextMenu(self.tray_menu())
            self.tray.activated.connect(self.tray_clicked)
            self.tray.show()
        elif not want and self.tray is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None

    def tray_menu(self):
        menu = QMenu()
        self.menu_ref = menu
        if self.hold:
            pause = menu.addAction("Pause")
            pause.triggered.connect(lambda: self.hold(not self.held()))
            menu.aboutToShow.connect(lambda: pause.setText("Resume" if self.held() else "Pause"))
        hide = menu.addAction("Hide all widgets")
        hide.triggered.connect(self.toggle_all)
        menu.aboutToShow.connect(lambda: hide.setText("Show all widgets" if self.hidden_all else "Hide all widgets"))
        menu.addAction("Settings").triggered.connect(self.open_settings)
        menu.addAction("Reset position").triggered.connect(self.reset_position)
        boot = QAction("Open when my PC starts", menu, checkable=True)
        menu.aboutToShow.connect(lambda: boot.setChecked(aura_common.startup_enabled(self.run_name)))
        boot.triggered.connect(lambda on: self.set_startup(on))
        menu.addAction(boot)
        menu.addAction("Open log").triggered.connect(self.open_log)
        menu.addSeparator()
        menu.addAction("Close widget").triggered.connect(QGuiApplication.instance().quit)
        return menu

    def tray_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings()

    def set_startup(self, on):
        try:
            aura_common.set_startup(self.run_name, on, self.script)
        except Exception:
            logging.exception("couldn't change open with windows")

    def open_log(self):
        path = os.path.join(aura_common.LOG_DIR, self.name + ".log")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.exists(path) else aura_common.LOG_DIR))

    def settings_action(self, menu):
        """Settings and Reset position, for the widget's right click menu."""
        a = menu.addAction("Settings")
        a.triggered.connect(self.open_settings)
        menu.addAction("Reset position").triggered.connect(self.reset_position)
        return a

    def open_settings(self):
        import aura_settings
        aura_settings.open_window(self.key)


class Welcome(QDialog):
    def __init__(self, extras):
        super().__init__(None)
        self.extras = extras
        self.setWindowTitle("Welcome to Aura")
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        box = QVBoxLayout(self)
        title = QLabel("Welcome to Aura")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        text = QLabel("Drag a widget to put it where you want it. Right click it for quick options, or open "
                      "Settings to change its shape, size, colors and more.\n\n"
                      "Settings can also snap widgets to the screen edges, hide them all with one shortcut, "
                      "and save your whole layout as a profile.")
        text.setWordWrap(True)
        text.setMinimumWidth(380)
        self.boot = QCheckBox("Open this widget when my PC starts")
        self.boot.toggled.connect(self.set_boot)
        row = QHBoxLayout()
        row.addStretch()
        settings = QPushButton("Open settings")
        settings.clicked.connect(lambda: (extras.open_settings(), self.close()))
        done = QPushButton("Got it")
        done.setDefault(True)
        done.clicked.connect(self.close)
        row.addWidget(settings)
        row.addWidget(done)
        for item in (title, text, self.boot):
            box.addWidget(item)
        box.addLayout(row)

    def set_boot(self, on):
        self.extras.set_startup(on)
