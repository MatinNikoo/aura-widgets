"""
Renders every card in every shape, text size and option combination with the real drawing code,
and lays them out on contact sheets so they can be checked by eye for overlap and clipping.

    python bench/gallery.py            writes docs/gallery/*.png
"""
import os, sys, io, datetime, itertools

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QPainter, QColor, QFont
from PyQt6.QtCore import Qt, QRectF, QPointF

import aura_common
import aura_draw
import drive

OUT = os.path.join(ROOT, "docs", "gallery")
SHAPES = [s for s, _ in aura_common.SHAPES]


def defaults(name, **k):
    class Empty:
        def value(self, key, default=None):
            return default
    o = aura_common.options(Empty(), name)
    o.update(k)
    return o


def sheet(cells, cols, title, path, cell_w, cell_h, bg=(222, 220, 226)):
    rows = (len(cells) + cols - 1) // cols
    img = QImage(cols * cell_w * 2, (rows * cell_h + 34) * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2)
    img.fill(QColor(*bg))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont("Inter")
    f.setPixelSize(15)
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    p.setPen(QColor(40, 38, 44))
    p.drawText(QPointF(16, 24), title)
    f.setPixelSize(11)
    f.setWeight(QFont.Weight.Normal)
    for i, (label, card) in enumerate(cells):
        x, y = (i % cols) * cell_w, 34 + (i // cols) * cell_h
        dpr = card.devicePixelRatio()
        w, h = card.width() / dpr, card.height() / dpr
        k = min(1.0, (cell_w - 8) / w, (cell_h - 22) / h)
        p.drawImage(QRectF(x + (cell_w - w * k) / 2, y, w * k, h * k), card)
        p.setFont(f)
        p.setPen(QColor(70, 68, 76))
        p.drawText(QRectF(x, y + cell_h - 20, cell_w, 18), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    img.save(path)
    return path


def music_cells(mod):
    buf = io.BytesIO()
    aura_draw.sample_cover(seed=5).save(buf, "PNG")
    cover = buf.getvalue()
    cells = []
    combos = [
        ("all", {}),
        ("no artist", {"show_artist": False}),
        ("no bar", {"show_bar": False}),
        ("no times", {"show_times": False}),
        ("title only", {"show_artist": False, "show_bar": False, "show_times": False, "show_controls": False}),
    ]
    for shape, backdrop in itertools.product(SHAPES, ("blur",)):
        card = mod.Card()
        card.set_look(mod.Look(defaults("Widget", shape=shape, backdrop=backdrop)))
        card.cur = mod.Track("A really long song title that has to be cut short somewhere", "Someone with a long name",
                             cover, "cover", card.look)
        card.dur_ms, card.pos_ms, card.playing = 3_725_000, 1_201_000, False
        w, h = card.size
        cells.append((f"{shape} blurred cover", aura_draw.render(card.paint, w + 2 * mod.M, h + 2 * mod.M, 2)))
    for shape, size, (cname, extra), hover in itertools.product(SHAPES, (80, 100, 130), combos, (0.0, 1.0)):
        if shape in ("square", "squircle") and cname not in ("all", "no bar"):
            continue
        o = defaults("Widget", shape=shape, text_size=size, **extra)
        card = mod.Card()
        card.set_look(mod.Look(o))
        card.cur = mod.Track("A really long song title that has to be cut short somewhere",
                             "Someone with a very long artist name, feat. Another One", cover, "cover", card.look)
        card.dur_ms, card.pos_ms, card.hover, card.playing = 3_725_000, 1_201_000, hover, False
        w, h = card.size
        img = aura_draw.render(card.paint, w + 2 * mod.M, h + 2 * mod.M, 2)
        cells.append((f"{shape} {size}% {cname}{' hover' if hover else ''}", img))
    return cells


def clock_cells(mod):
    now = datetime.datetime(2026, 9, 30, 23, 58, 47)
    cells = []
    locales = ["", "fa_IR", "ar_SA", "he_IL", "zh_CN", "ja_JP", "ko_KR", "ru_RU", "de_DE"]
    for shape, size, secs in itertools.product(SHAPES, (80, 100, 120), (False, True)):
        o = defaults("Clock", shape=shape, time_size=size, seconds=secs)
        card = mod.ClockCard()
        card.apply(o)
        card.effects = {"main": 0.0, 2: 0.4}
        w, h = card.size
        cells.append((f"{shape} {size}%{' seconds' if secs else ''}",
                      aura_draw.render(lambda p: card.paint(p, now, 1.1), w + 2 * mod.M, h + 2 * mod.M, 2)))
    for shape, loc, date in itertools.product(("rounded", "circle"), locales, ("weekday", "full")):
        o = defaults("Clock", shape=shape, locale=loc, date=date, h24=loc not in ("", "en_US"))
        card = mod.ClockCard()
        card.apply(o)
        w, h = card.size
        cells.append((f"{shape} {loc or 'default'} {date}",
                      aura_draw.render(lambda p: card.paint(p, now, 0.0), w + 2 * mod.M, h + 2 * mod.M, 2)))
    for shape, size, secs, date in itertools.product(SHAPES, (80, 120), (False, True), ("weekday", "none")):
        o = defaults("Clock", face="analog", shape=shape, time_size=size, seconds=secs, date=date)
        card = mod.ClockCard()
        card.apply(o)
        w, h = card.size
        cells.append((f"analog {shape} {size}%{' seconds' if secs else ''}{' no date' if date == 'none' else ''}",
                      aura_draw.render(lambda p: card.paint(p, now, 0.0), w + 2 * mod.M, h + 2 * mod.M, 2)))
    for shape, loc in itertools.product(("rounded", "circle"), locales[1:6]):
        card = mod.ClockCard()
        card.apply(defaults("Clock", face="analog", shape=shape, locale=loc, date="full"))
        w, h = card.size
        cells.append((f"analog {shape} {loc}",
                      aura_draw.render(lambda p: card.paint(p, now, 0.0), w + 2 * mod.M, h + 2 * mod.M, 2)))
    for style, font in (("flat", ""), ("chrome", "DejaVu Serif"), ("flat", "Inter")):
        o = defaults("Clock", style=style, font=font)
        card = mod.ClockCard()
        card.apply(o)
        cells.append((f"{style} {font or 'Unbounded'}",
                      aura_draw.render(lambda p: card.paint(p, now, 0.0), 452, 184, 2)))
    return cells


def gif_cells(mod):
    frame = aura_draw.sample_cover(400, seed=8).resize((400, 240))
    q = mod.pil_to_qimage(frame)
    cells = []
    f = mod.pick_font(14, QFont.Weight.Medium)
    for shape, mode, size in itertools.product(SHAPES, ("fill", "fit", "stretch"), ((440, 160), (270, 340))):
        if shape == "circle":
            size = (min(size), min(size))
        o = defaults("Gif", shape=shape, mode=mode)
        card = mod.GifCard(*size)
        card.apply(o)
        card.set_frame(q)
        card.set_backdrop(q)
        cells.append((f"{shape} {mode} {size[0]}x{size[1]}",
                      aura_draw.render(lambda p: card.paint(p, f), size[0] + 2 * mod.M, size[1] + 2 * mod.M, 2)))
    for shape in SHAPES:
        card = mod.GifCard(220, 220 if shape == "circle" else 120)
        card.apply(defaults("Gif", shape=shape, border="bold"))
        cells.append((f"{shape} empty, bold border",
                      aura_draw.render(lambda p: card.paint(p, f), card.w + 2 * mod.M, card.h + 2 * mod.M, 2)))
    return cells


def main():
    app = QApplication.instance() or QApplication([])
    os.makedirs(OUT, exist_ok=True)
    music = drive.load("aura_widget")
    clock = drive.load("aura_clock")
    gif = drive.load("aura_gif")
    m = music_cells(music)
    half = len(m) // 2
    print(sheet(m[:half], 4, "Now playing, shapes, text sizes and what shows (1 of 2)",
                os.path.join(OUT, "music_1.png"), 300, 170))
    print(sheet(m[half:], 4, "Now playing, shapes, text sizes and what shows (2 of 2)",
                os.path.join(OUT, "music_2.png"), 300, 170))
    c = clock_cells(clock)
    print(sheet(c, 4, "Clock, shapes, sizes, faces, languages and fonts", os.path.join(OUT, "clock.png"), 300, 170))
    g = gif_cells(gif)
    print(sheet(g, 6, "GIF box, shapes, fit modes and sizes", os.path.join(OUT, "gif.png"), 220, 200))
    del app


if __name__ == "__main__":
    main()
