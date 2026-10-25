"""
With default settings every card has to draw exactly what version 1.0 drew, pixel for pixel.
tests/original/ holds the 1.0 files untouched.
"""
import os, datetime

import pytest

from conftest import ROOT, cover_bytes
import drive


@pytest.fixture(scope="module")
def v1(app):
    d = os.path.join(ROOT, "tests", "original")
    mods = {k: drive.load(k + "_v1", os.path.join(d, k + "_v1.py")) for k in ("aura_widget", "aura_clock", "aura_gif")}
    mods["aura_clock"].FONT_SPOTS = [os.path.join(ROOT, "Unbounded.ttf")]     # 1.0 looks next to its own file
    return mods


def render(paint, w, h, dpr=2):
    from PyQt6.QtGui import QImage, QPainter, QColor
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    paint(p)
    p.end()
    return img


def same(a, b):
    assert a.size() == b.size()
    if a != b:
        diff = sum(1 for y in range(a.height()) for x in range(a.width()) if a.pixel(x, y) != b.pixel(x, y))
        pytest.fail(f"{diff} pixels differ from version 1.0")


MUSIC_STATES = [
    dict(cover=None, dur=0, frac=0, hover=0.0, playing=False),
    dict(cover=(200, 40, 60), dur=200_000, frac=0.37, hover=0.0, playing=False),
    dict(cover=(30, 90, 220), dur=200_000, frac=0.8, hover=1.0, playing=True),
    dict(cover=(128, 128, 128), dur=245_000, frac=0.05, hover=0.5, playing=False),
]


@pytest.mark.parametrize("st", MUSIC_STATES)
@pytest.mark.parametrize("dpr", [1, 1.5, 2])
def test_music_card(music, v1, st, dpr):
    old, new = v1["aura_widget"], music
    imgs = []
    for mod in (old, new):
        card = mod.Card()
        if st["cover"]:
            data = cover_bytes(st["cover"], patch=((40, 40, 160, 160), (240, 220, 30)))
            card.old = mod.Track("Previous song", "Someone", cover_bytes((10, 10, 10)))
            card.cur = mod.Track("A song with a fairly long title that won't fit", "The Artist", data)
            card.t = 0.6
        card.dur_ms, card.pos_ms, card.hover = st["dur"], st["dur"] * st["frac"], st["hover"]
        card.playing = False                    # keep position() fixed
        imgs.append(render(card.paint, mod.W + 2 * mod.M, mod.H + 2 * mod.M, dpr))
    same(*imgs)


@pytest.mark.parametrize("h24,seconds", [(False, False), (True, True), (False, True)])
@pytest.mark.parametrize("effects", [{}, {"main": 0.0, 3: 0.3, 7: 0.9}])
def test_clock_card(clock, v1, h24, seconds, effects):
    imgs = []
    for mod in (v1["aura_clock"], clock):
        card = mod.ClockCard()
        card.h24, card.seconds = h24, seconds
        card.effects = dict(effects)
        now = datetime.datetime(2026, 11, 3, 21, 47, 9)
        imgs.append(render(lambda p: card.paint(p, now, 1.0), mod.W + 2 * mod.M, mod.H + 2 * mod.M))
    same(*imgs)


@pytest.mark.parametrize("fit", [False, True])
@pytest.mark.parametrize("size", [(440, 160), (270, 340), (180, 90)])
def test_gif_card(gif, v1, fit, size):
    from PyQt6.QtGui import QImage, QColor, QPainter
    frame = QImage(320, 180, QImage.Format.Format_ARGB32)
    frame.fill(QColor(20, 120, 200))
    p = QPainter(frame)
    p.fillRect(40, 30, 100, 90, QColor(250, 200, 40))
    p.end()
    imgs = []
    for mod in (v1["aura_gif"], gif):
        card = mod.GifCard(*size)
        card.fit = fit
        card.pan = [0.2, 0.7]
        card.set_frame(frame)
        card.set_backdrop(frame)
        imgs.append(render(card.paint, size[0] + 2 * mod.M, size[1] + 2 * mod.M))
    same(*imgs)


def test_empty_gif_card(gif, v1):
    from PyQt6.QtGui import QFont
    imgs = []
    for mod in (v1["aura_gif"], gif):
        card = mod.GifCard()
        f = mod.pick_font(14, QFont.Weight.Medium)
        imgs.append(render(lambda p: card.paint(p, f), 492, 212))
    same(*imgs)
