"""
Makes docs/media/features.png (the analog clock and the blurred cover card) and docs/media/settings.png
(the settings window). Drawn by the widgets' own code, offscreen. Covers are the public domain Met
paintings that demo.py downloads.

    python bench/features.py
"""
import os, sys, datetime, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="aura_features_")      # the settings window starts from defaults
os.environ["AURA_NO_WELCOME"] = "1"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtCore import QRectF, QTimer, QEventLoop

import drive
import demo

OUT = demo.OUT


def options(name, **k):
    class Empty:
        def value(self, key, default=None):
            return default
    import aura_common
    o = aura_common.options(Empty(), name)
    o.update(k)
    return o


def main():
    app = QApplication.instance() or QApplication([])
    covers = demo.fetch()
    music = drive.load("aura_widget")
    clock = drive.load("aura_clock")
    ids = list(demo.ART)
    now = datetime.datetime(2026, 10, 22, 10, 9, 37)

    cells = []
    for kw in ({"seconds": True}, {"shape": "pill", "date": "full"}, {"shape": "circle", "seconds": True},
               {"shape": "squircle", "time_size": 120, "date": "none"}):
        k = clock.ClockCard()
        k.apply(options("Clock", face="analog", **kw))
        cells.append((k.size, clock.M, (lambda kk: lambda p: kk.paint(p, now, 0.0))(k)))
    for i, kw in enumerate(({}, {"shape": "pill"})):
        c = music.Card()
        c.set_look(music.Look(options("Widget", backdrop="blur", **kw)))
        c.cur = music.Track(*demo.ART[ids[i]], covers[ids[i]], look=c.look)
        c.dur_ms, c.pos_ms = 201_000, 74_000 + i * 50_000
        cells.append((c.size, music.M, c.paint))

    cols, cw, chh = 2, 520, 230
    rows = (len(cells) + cols - 1) // cols
    wall = music.pil_to_qimage(demo.wallpaper(cols * cw, rows * chh))
    img = QImage(cols * cw * 2, rows * chh * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, cols * cw, rows * chh), wall)
    for i, ((w, h), m, paint) in enumerate(cells):
        demo.put(p, (i % cols) * cw + (cw - w - 2 * m) / 2, (i // cols) * chh + (chh - h - 2 * m) / 2, paint, (w, h), m, 2)
    p.end()
    img.save(os.path.join(OUT, "features.png"))

    import aura_settings
    win = aura_settings.SettingsWindow()
    win.resize(860, 560)
    win.show()
    win.tabs.setCurrentIndex(0)
    loop = QEventLoop()
    QTimer.singleShot(600, loop.quit)
    loop.exec()
    win.grab().save(os.path.join(OUT, "settings.png"))
    for f in ("features.png", "settings.png"):
        print(os.path.join(OUT, f), os.path.getsize(os.path.join(OUT, f)) // 1024, "KB")
    del app


if __name__ == "__main__":
    main()
