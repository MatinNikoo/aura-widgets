"""
The settings window. One tab per widget, settings grouped like aura_common.SCHEMA, and a live preview
drawn by the widget's own drawing code. Every change is written to that widget's settings file right
away, and a running widget picks it up from there.

    python aura.py settings
"""
import os, sys, glob, time, logging, importlib.machinery, importlib.util

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QDesktopServices, QFontDatabase, QGuiApplication, QKeySequence, QPainter
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QInputDialog, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
                             QSlider, QTabWidget, QVBoxLayout, QWidget)

import aura_common
import aura_profiles
from aura_common import options, schema, store

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

# settings file name -> (tab title, widget file, Run key name)
WIDGETS = [("Widget", "Music", "aura_widget", "AuraWidget"), ("Clock", "Clock", "aura_clock", "AuraClockWidget")]


BOX_TITLES = {"aura_gif": "Wide box", "aura_gif_tall": "Tall box"}


def gif_boxes():
    """Every GIF box: the two that ship, plus copies that have a settings file or sit next to this file."""
    boxes = {"aura_gif": "Gif", "aura_gif_tall": "Gif_aura_gif_tall"}
    for path in glob.glob(os.path.join(HERE, "aura_gif*.pyw")):
        stem = os.path.splitext(os.path.basename(path))[0]
        boxes.setdefault(stem, "Gif_" + stem)
    for path in glob.glob(os.path.join(aura_common.SETTINGS_DIR, "Gif_*.ini")):
        name = os.path.splitext(os.path.basename(path))[0]
        boxes.setdefault(name[4:], name)
    return sorted(boxes.items())


def run_name(name):
    if name == "Gif":
        return "AuraGifWidget"
    if name.startswith("Gif_"):
        return "Aura_" + name[4:]
    return {"Widget": "AuraWidget", "Clock": "AuraClockWidget"}[name]


_modules = {}


def module(stem):
    """The widget's own code, for drawing previews."""
    if stem not in _modules:
        path = os.path.join(HERE, stem + ".pyw")
        if not os.path.exists(path):
            path = os.path.join(HERE, "aura_gif.pyw")
        loader = importlib.machinery.SourceFileLoader("preview_" + stem, path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        _modules[stem] = mod
    return _modules[stem]


class PreviewBox(QWidget):
    """Shows the preview image scaled down to fit, centered."""

    def __init__(self):
        super().__init__()
        self.img = None
        self.setMinimumSize(300, 220)

    def set_image(self, img):
        self.img = img
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(216, 214, 220))
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        if self.img is None:
            return
        dpr = self.img.devicePixelRatio()
        w, h = self.img.width() / dpr, self.img.height() / dpr
        k = min(1.0, (self.width() - 16) / w, (self.height() - 16) / h)
        r = QRectF((self.width() - w * k) / 2, (self.height() - h * k) / 2, w * k, h * k)
        p.drawImage(r, self.img)
        p.end()


class Tab(QWidget):
    def __init__(self, name, stem, picker=None):
        super().__init__()
        self.name, self.stem = name, stem
        self.s = aura_common.settings(name)
        self.editors = {}
        self.loading = False
        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        if picker is not None:
            left.addWidget(picker)
        self.header_boxes(left)
        for section, rows in schema(name):
            box = QGroupBox(section)
            form = QFormLayout(box)
            for key, kind, default, label, extra in rows:
                self.add(form, key, kind, label, extra)
            if section == "Behavior":
                self.boot = QCheckBox("Open when my PC starts")
                self.boot.setChecked(aura_common.startup_enabled(run_name(name)))
                self.boot.toggled.connect(self.set_boot)
                form.addRow(self.boot)
            left.addWidget(box)
        self.extra_boxes(left)
        left.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        holder.setLayout(left)
        scroll.setWidget(holder)
        scroll.setMinimumWidth(380)
        outer.addWidget(scroll, 3)

        self.preview = PreviewBox()
        if stem:
            right = QVBoxLayout()
            right.addWidget(QLabel("Preview"))
            right.addWidget(self.preview, 1)
            reset = QPushButton("Reset to defaults")
            reset.clicked.connect(self.reset)
            right.addWidget(reset)
            home = QPushButton("Reset position")
            home.setToolTip("Send the widget back to its default spot")
            home.clicked.connect(self.reset_position)
            right.addWidget(home)
            outer.addLayout(right, 2)
        self.load()

    def extra_boxes(self, left):
        """Anything after the settings sections. The General tab fills this in."""

    def header_boxes(self, left):
        if not self.name.startswith("Gif"):
            return
        box = QGroupBox("Choose a GIF")
        row = QHBoxLayout(box)
        find = QPushButton("Find in a folder")
        find.clicked.connect(self.find_gif)
        pick = QPushButton("Pick a file")
        pick.clicked.connect(self.pick_gif)
        row.addWidget(find)
        row.addWidget(pick)
        left.addWidget(box)

    def find_gif(self):
        import aura_library
        self.library = aura_library.GifLibrary(self.window())
        self.library.chosen.connect(self.choose_gif)
        self.library.show()

    def pick_gif(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a GIF", os.path.expanduser("~"), "GIFs (*.gif *.webp)")
        if path:
            self.choose_gif(path)

    def choose_gif(self, path):
        """The running box picks this up from the settings file and loads it."""
        self.s.setValue("choose", path)
        self.s.sync()

    def reset_position(self):
        self.s.remove("pos")
        self.s.remove("spots")
        self.s.setValue("move_token", str(time.time()))
        self.s.sync()

    # editors for each kind of setting
    def add(self, form, key, kind, label, extra):
        if kind == "bool":
            e = QCheckBox(label)
            e.toggled.connect(lambda v, k=key: self.write(k, v))
            form.addRow(e)
        elif kind in ("int", "float"):
            e = QSlider(Qt.Orientation.Horizontal)
            lo, hi = extra
            pct = kind == "float"
            e.setRange(int(lo * 100) if pct else lo, int(hi * 100) if pct else hi)
            shown = QLabel()
            shown.setMinimumWidth(42)
            e.valueChanged.connect(lambda v, k=key, p=pct, sh=shown: (
                sh.setText(f"{v}%" if p or k.endswith(("size", "dim")) else str(v)),
                self.write(k, v / 100 if p else v)))
            row = QHBoxLayout()
            row.addWidget(e)
            row.addWidget(shown)
            form.addRow(label, row)
        elif kind == "hotkey":
            e = QKeySequenceEdit()
            e.setMaximumSequenceLength(1)
            e.setClearButtonEnabled(True)
            e.editingFinished.connect(
                lambda k=key, box=e: self.write(k, box.keySequence().toString(QKeySequence.SequenceFormat.PortableText)))
            form.addRow(label, e)
        elif kind in ("choice", "monitor", "font"):
            e = QComboBox()
            if kind == "choice":
                for v, text in extra:
                    e.addItem(text, v)
            elif kind == "monitor":
                e.addItem("Wherever I drag it", "")
                for s in QGuiApplication.screens():
                    g = s.geometry()
                    e.addItem(f"{s.name()}  ({g.width()} x {g.height()})", s.name())
            else:
                e.addItem("Unbounded (built in)", "")
                for fam in QFontDatabase.families():
                    e.addItem(fam, fam)
            e.currentIndexChanged.connect(lambda i, k=key, box=e: self.write(k, box.itemData(i)))
            form.addRow(label, e)
        else:                                          # file or folder
            e = QLineEdit()
            e.setReadOnly(True)
            e.setPlaceholderText("Off")
            pick, clear = QPushButton("Pick"), QPushButton("Clear")
            pick.clicked.connect(lambda _, k=key, kd=kind, box=e: self.pick(k, kd, box))
            clear.clicked.connect(lambda _, k=key, box=e: (box.setText(""), self.write(k, "")))
            row = QHBoxLayout()
            row.addWidget(e, 1)
            row.addWidget(pick)
            row.addWidget(clear)
            form.addRow(label, row)
        self.editors[key] = (kind, e)

    def pick(self, key, kind, box):
        start = box.text() or os.path.expanduser("~")
        if kind == "folder":
            path = QFileDialog.getExistingDirectory(self, "Pick a folder", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Pick a file", start,
                                                  "GIFs and images (*.gif *.webp *.png *.jpg *.jpeg)")
        if path:
            box.setText(path)
            self.write(key, path)

    def load(self):
        self.s.sync()
        self.loading = True
        o = options(self.s, self.name)
        for key, (kind, e) in self.editors.items():
            v = o[key]
            if kind == "bool":
                e.setChecked(v)
            elif kind == "int":
                e.setValue(v)
                e.valueChanged.emit(v)
            elif kind == "float":
                e.setValue(round(v * 100))
                e.valueChanged.emit(round(v * 100))
            elif kind == "hotkey":
                e.setKeySequence(QKeySequence(v))
            elif isinstance(e, QComboBox):
                i = e.findData(v)
                e.setCurrentIndex(i if i >= 0 else 0)
            else:
                e.setText(v)
        self.loading = False
        self.enable()
        self.refresh()

    def enable(self):
        """Grey out settings that don't do anything with the current choices."""
        o = options(self.s, self.name)
        digital = o.get("face", "digital") == "digital"
        rules = {"radius": o.get("shape") == "rounded", "background_dim": bool(o.get("background")),
                 "every": bool(o.get("folder")), "shuffle": bool(o.get("folder")),
                 "h24": digital, "style": digital, "hotkey": bool(o.get("hotkey_on"))}
        for key, on in rules.items():
            if key in self.editors:
                self.editors[key][1].setEnabled(on)

    def write(self, key, value):
        if getattr(self, "loading", False):
            return
        self.s.setValue(key, store(value))
        if key == "mode" and self.name.startswith("Gif"):
            self.s.setValue("fit", "true" if value == "fit" else "false")     # 1.0 reads this one
        self.s.sync()
        self.enable()
        self.refresh()

    def reset(self):
        aura_common.reset(self.s, self.name)
        self.load()

    def set_boot(self, on):
        try:
            aura_common.set_startup(run_name(self.name), on, os.path.join(HERE, self.stem + ".pyw"))
        except Exception:
            logging.exception("couldn't change open with windows")

    def refresh(self):
        if self.stem:
            QTimer.singleShot(0, self.draw_preview)

    def draw_preview(self):
        try:
            mod = module(self.stem)
            self.preview.set_image(mod.preview_image(options(self.s, self.name), self.s,
                                                     max(2.0, self.preview.devicePixelRatioF())))
        except Exception:
            logging.exception("preview failed")
            self.preview.set_image(None)


class GeneralTab(Tab):
    """Things that belong to every widget at once, like the hotkey, profiles and backups."""

    def __init__(self):
        super().__init__("General", None)

    def extra_boxes(self, left):
        every = QGroupBox("All widgets")
        column = QVBoxLayout(every)
        row = QHBoxLayout()
        column.addLayout(row)
        for text, slot in (("Hide all", lambda: aura_common.set_hidden(True)),
                           ("Show all", lambda: aura_common.set_hidden(False)),
                           ("Reset all positions", self.reset_all_positions)):
            b = QPushButton(text)
            b.clicked.connect(lambda _, f=slot: f())
            row.addWidget(b)
        note = QLabel("A hidden widget comes back with Show all, with the shortcut, or when you open it again.")
        note.setWordWrap(True)
        column.addWidget(note)
        left.addWidget(every)

        box = QGroupBox("Profiles")
        form = QFormLayout(box)
        self.profiles = QComboBox()
        self.profiles.setMinimumWidth(180)
        row = QHBoxLayout()
        for text, slot in (("Switch to it", self.switch_profile), ("Save current setup", self.save_profile),
                           ("Delete", self.delete_profile)):
            b = QPushButton(text)
            b.clicked.connect(lambda _, f=slot: f())
            row.addWidget(b)
        form.addRow("Saved setups", self.profiles)
        form.addRow(row)
        note = QLabel("A profile keeps every setting and where each widget sits.")
        note.setWordWrap(True)
        form.addRow(note)
        left.addWidget(box)
        self.fill_profiles()

        backup = QGroupBox("Backup")
        row = QHBoxLayout(backup)
        for text, slot in (("Export settings", self.export_settings), ("Import settings", self.import_settings)):
            b = QPushButton(text)
            b.clicked.connect(lambda _, f=slot: f())
            row.addWidget(b)
        left.addWidget(backup)

    def say(self, text):
        QMessageBox.information(self.window(), "Aura", text)

    def reload_all(self):
        win = self.window()
        if isinstance(win, SettingsWindow):
            win.reload_tabs()

    def reset_all_positions(self):
        aura_profiles.reset_positions()

    # profiles
    def fill_profiles(self, pick=None):
        self.profiles.clear()
        self.profiles.addItems(aura_profiles.profile_names())
        if pick:
            self.profiles.setCurrentText(pick)

    def save_profile(self):
        name, ok = QInputDialog.getText(self, "Save current setup", "Name",
                                        text=self.profiles.currentText() or "My setup")
        if ok and name.strip():
            self.save_profile_as(name)

    def save_profile_as(self, name):
        try:
            self.fill_profiles(aura_profiles.save_profile(name))
        except (OSError, ValueError) as e:
            self.say(f"Couldn't save it. {e}")

    def switch_profile(self):
        if self.profiles.currentText():
            self.switch_profile_to(self.profiles.currentText())

    def switch_profile_to(self, name):
        try:
            aura_profiles.load_profile(name)
        except (OSError, ValueError) as e:
            self.say(f"Couldn't open that profile. {e}")
            return
        self.reload_all()

    def delete_profile(self):
        name = self.profiles.currentText()
        if name and QMessageBox.question(self, "Delete", f"Delete the profile {name}?") == QMessageBox.StandardButton.Yes:
            aura_profiles.delete_profile(name)
            self.fill_profiles()

    # backup
    def export_settings(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", os.path.join(os.path.expanduser("~"), "aura-settings.json"),
                                              "Aura settings (*.json)")
        if path:
            aura_profiles.export_file(path)

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", os.path.expanduser("~"), "Aura settings (*.json)")
        if path:
            self.import_from(path)

    def import_from(self, path):
        try:
            done, skipped = aura_profiles.import_file(path)
        except ValueError as e:
            self.say(str(e))
            return None
        self.reload_all()
        return done, skipped


class SettingsWindow(QWidget):
    def __init__(self, start=None):
        super().__init__()
        self.setWindowTitle("Aura settings")
        self.resize(860, 640)
        box = QVBoxLayout(self)
        self.tabs = QTabWidget()
        for name, title, stem, _ in WIDGETS:
            self.tabs.addTab(Tab(name, stem), title)

        # GIF boxes share one tab, with a picker for which box
        self.gif_holder = QWidget()
        self.gif_layout = QVBoxLayout(self.gif_holder)
        self.gif_layout.setContentsMargins(0, 0, 0, 0)
        self.gif_pick = QComboBox()
        for stem, name in gif_boxes():
            self.gif_pick.addItem(BOX_TITLES.get(stem) or "Copy " + stem.replace("aura_", "").replace("_", " "), (stem, name))
        self.gif_pick.currentIndexChanged.connect(self.show_gif)
        self.gif_tab = None
        self.tabs.addTab(self.gif_holder, "GIF")
        self.show_gif()
        self.general_tab = GeneralTab()
        self.tabs.addTab(self.general_tab, "General")
        box.addWidget(self.tabs)

        bottom = QHBoxLayout()
        b = QPushButton("Open settings folder")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(aura_common.SETTINGS_DIR)))
        bottom.addWidget(b)
        b = QPushButton("Open logs")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(aura_common.LOG_DIR)))
        bottom.addWidget(b)
        b = QPushButton("Make a problem report")
        b.clicked.connect(self.report)
        bottom.addWidget(b)
        bottom.addStretch()
        b = QPushButton("Done")
        b.clicked.connect(self.close)
        bottom.addWidget(b)
        box.addLayout(bottom)
        if start:
            self.select(start)

    def reload_tabs(self):
        """After a profile or an import changed the files, show what's in them now."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w is self.gif_holder:
                self.show_gif()
            elif isinstance(w, Tab):
                w.load()

    def report(self):
        from PyQt6.QtWidgets import QMessageBox
        ok = QMessageBox.question(
            self, "Problem report",
            "This puts Aura's log files, your Aura settings and your Windows and Python versions into one zip "
            "file on your Desktop. Nothing is sent anywhere. If you want help, you can attach it to a GitHub issue.\n\n"
            "Make the file?")
        if ok != QMessageBox.StandardButton.Yes:
            return
        desk = os.path.join(os.path.expanduser("~"), "Desktop")
        screens = [f"screen {s.name()} {s.geometry().width()}x{s.geometry().height()} scale {s.devicePixelRatio()}"
                   for s in QGuiApplication.screens()]
        path = aura_common.problem_report(desk if os.path.isdir(desk) else os.path.expanduser("~"), screens)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def show_gif(self, *_):
        stem, name = self.gif_pick.currentData()
        if self.gif_tab is not None:
            self.gif_layout.removeWidget(self.gif_tab)
            self.gif_tab.deleteLater()
        picker_row = QWidget()
        row = QHBoxLayout(picker_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("GIF box"))
        self.gif_pick.setParent(None)
        row.addWidget(self.gif_pick, 1)
        self.gif_tab = Tab(name, stem, picker_row)
        self.gif_layout.addWidget(self.gif_tab)

    def select(self, name):
        if name.startswith("Gif"):
            for i in range(self.gif_pick.count()):
                if self.gif_pick.itemData(i)[1] == name:
                    self.gif_pick.setCurrentIndex(i)
            self.tabs.setCurrentWidget(self.gif_holder)
        else:
            titles = {n: t for n, t, _, _ in WIDGETS}
            titles["General"] = "General"
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == titles.get(name):
                    self.tabs.setCurrentIndex(i)


_window = None


def open_window(start=None, standalone=False):
    global _window
    if _window is None:
        _window = SettingsWindow(start)
        if not standalone:
            # opened from a widget: closing this window must not count as the app's last window closing
            _window.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
    elif start:
        _window.select(start)
    _window.show()
    _window.raise_()
    _window.activateWindow()
    return _window


def main():
    aura_common.setup_logging("aura_settings")
    app = QApplication.instance() or QApplication(sys.argv)
    open_window(standalone=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
