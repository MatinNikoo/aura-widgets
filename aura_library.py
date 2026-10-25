"""
Find a GIF in a folder on your PC. Pick a folder, type part of a name, and double click a thumbnail.
It's used by the GIF box's right click menu and by the settings window.
"""
import os, time

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QImageReader, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QVBoxLayout)

import aura_common

THUMB = QSize(132, 88)
LIMIT = 600           # more than this many matches and the list says so instead of loading them all


def find_gifs(folder, text="", deep=True, limit=LIMIT + 1):
    """GIF and WebP files in folder whose name contains every word of text, best matches first.
    Searches the subfolders too unless deep is false."""
    words = text.lower().split()
    found = []
    if not folder or not os.path.isdir(folder):
        return found
    end = time.monotonic() + 4              # a huge folder tree gives what it found so far
    for root, dirs, files in os.walk(folder):
        if time.monotonic() > end:
            break
        dirs[:] = sorted((d for d in dirs if not d.startswith(".")), key=str.lower) if deep else []
        for name in sorted(files, key=str.lower):
            low = name.lower()
            if low.endswith(aura_common.GIF_TYPES) and all(w in low for w in words):
                found.append(os.path.join(root, name))
                if len(found) >= limit:
                    return found
    found.sort(key=lambda p: (not os.path.basename(p).lower().startswith(words[0]) if words else False,
                              os.path.basename(p).lower()))
    return found


class GifLibrary(QDialog):
    chosen = pyqtSignal(str)

    def __init__(self, parent=None, folder=""):
        super().__init__(parent)
        self.setWindowTitle("Find a GIF")
        self.resize(720, 520)
        self.general = aura_common.settings("General")
        self.folder = folder or str(self.general.value("library", "") or "")
        self.files = []
        self.queue = []
        box = QVBoxLayout(self)
        top = QHBoxLayout()
        self.where = QLineEdit(self.folder, readOnly=True, placeholderText="Pick a folder to search")
        pick = QPushButton("Folder")
        pick.clicked.connect(self.pick_folder)
        top.addWidget(self.where, 1)
        top.addWidget(pick)
        box.addLayout(top)
        row = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Part of a file name")
        self.search.setClearButtonEnabled(True)
        self.deep = QCheckBox("Include subfolders", checked=True)
        row.addWidget(self.search, 1)
        row.addWidget(self.deep)
        box.addLayout(row)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(THUMB)
        self.list.setGridSize(QSize(THUMB.width() + 24, THUMB.height() + 44))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.itemDoubleClicked.connect(self.use)
        box.addWidget(self.list, 1)
        self.note = QLabel()
        bottom = QHBoxLayout()
        self.use_button = QPushButton("Use this GIF")
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(lambda: self.use(self.list.currentItem()))
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(self.note, 1)
        bottom.addWidget(self.use_button)
        bottom.addWidget(close)
        box.addLayout(bottom)

        self.list.currentItemChanged.connect(lambda cur, _: self.use_button.setEnabled(cur is not None))
        self.typing = QTimer(self, singleShot=True, interval=250)
        self.typing.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _: self.typing.start())
        self.deep.toggled.connect(lambda _: self.refresh())
        self.loader = QTimer(self, interval=0)
        self.loader.timeout.connect(self.load_some)
        self.refresh()

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Folder to search", self.folder or os.path.expanduser("~"))
        if path:
            self.folder = path
            self.where.setText(path)
            self.general.setValue("library", path)
            self.general.sync()
            self.refresh()

    def refresh(self):
        self.loader.stop()
        self.list.clear()
        self.files = find_gifs(self.folder, self.search.text(), self.deep.isChecked())
        over = len(self.files) > LIMIT
        self.files = self.files[:LIMIT]
        for path in self.files:
            item = QListWidgetItem(os.path.splitext(os.path.basename(path))[0])
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            item.setSizeHint(self.list.gridSize())
            self.list.addItem(item)
        self.queue = list(range(len(self.files)))
        if not self.folder:
            self.note.setText("Pick a folder to start.")
        elif not self.files:
            self.note.setText("No GIFs found.")
        else:
            self.note.setText(f"Showing the first {LIMIT}. Type to narrow it down." if over
                              else f"{len(self.files)} found")
        self.loader.start()

    def load_some(self):
        """Thumbnails come in a few at a time, so a big folder doesn't freeze the window."""
        for _ in range(3):
            if not self.queue:
                self.loader.stop()
                return
            i = self.queue.pop(0)
            item = self.list.item(i)
            if item is None:
                continue
            reader = QImageReader(self.files[i])
            img = reader.read()
            if not img.isNull():
                item.setIcon(QIcon(QPixmap.fromImage(img.scaled(
                    THUMB, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))))

    def use(self, item):
        if item is not None:
            self.chosen.emit(item.data(Qt.ItemDataRole.UserRole))
            self.close()
