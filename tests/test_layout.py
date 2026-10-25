"""
Nothing a card draws may overlap anything else it draws, or stick out of its shape, in any shape,
text size or show combination. The cards note the rectangle of each piece they draw.
"""
import itertools, datetime

import pytest
from PyQt6.QtCore import QRectF, QPointF

from conftest import cover_bytes
import aura_common
import aura_draw

SHAPES = [s for s, _ in aura_common.SHAPES]


class Empty:
    def value(self, key, default=None):
        return default


def opts(name, **k):
    o = aura_common.options(Empty(), name)
    o.update(k)
    return o


def check(drawn, shape, w, h, radius, ignore=()):
    names = [n for n in drawn if n not in ignore]
    for a, b in itertools.combinations(names, 2):
        ra, rb = drawn[a], drawn[b]
        # glyph boxes include the font's line gap, so allow a hair of vertical touching
        assert not ra.adjusted(0, 1, 0, -1).intersects(rb.adjusted(0, 1, 0, -1)), f"{a} {ra} overlaps {b} {rb}"
    path = aura_draw.shape_path(shape, QRectF(0, 0, w, h), radius)
    for n in names:
        r = drawn[n].adjusted(0, 2, 0, -2)       # same line gap allowance
        for pt in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
            assert path.contains(QPointF(pt)), f"{n} {drawn[n]} sticks out of the {shape} card"


TITLES = [("A really long song title that has to be cut short somewhere",
           "Someone with a very long artist name, feat. Another One"), ("Hi", "X"), ("Song", "")]
SHOWS = [{}, {"show_artist": False}, {"show_bar": False}, {"show_times": False},
         {"show_artist": False, "show_bar": False}, {"show_controls": False, "show_times": False}]


STATES = [(0.0, None), (0.0, 0.5), (1.0, None)]      # resting, hovering the bar to seek, hovering the card


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("size", [80, 100, 115, 130])
@pytest.mark.parametrize("radius", [0, 26, 60])
def test_music_card_never_overlaps(music, shape, size, radius):
    cover = cover_bytes((90, 30, 160))
    card = music.Card()
    tracks = [music.Track(t, a, cover, "cover", card.look) for t, a in TITLES]
    for show in SHOWS:
        card.set_look(music.Look(opts("Widget", shape=shape, text_size=size, radius=radius, **show)))
        for tr, (hover, preview), dur in itertools.product(tracks, STATES, (200_000, 3_725_000)):
            tr.relayer(card.look)
            card.cur = tr
            card.dur_ms, card.pos_ms, card.hover, card.preview = dur, dur * 0.4, hover, preview
            w, h = card.size
            aura_draw.render(card.paint, w + 2 * music.M, h + 2 * music.M, 1)
            check(card.drawn, shape, w, h, radius)


NOW = datetime.datetime(2026, 9, 30, 23, 58, 47)
LOCALES = ["", "en_US", "fa_IR", "ar_SA", "he_IL", "zh_CN", "ja_JP", "ko_KR", "ru_RU", "de_DE", "hi_IN"]


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("size", [80, 100, 120])
def test_clock_never_overlaps(clock, shape, size):
    card = clock.ClockCard()
    for secs, h24, date, loc in itertools.product((False, True), (False, True), ("weekday", "full", "none"),
                                                  LOCALES[::3]):
        card.apply(opts("Clock", shape=shape, time_size=size, seconds=secs, h24=h24, date=date, locale=loc))
        w, h = card.size
        aura_draw.render(lambda p: card.paint(p, NOW, 0.0), w + 2 * clock.M, h + 2 * clock.M, 1)
        drawn = dict(card.drawn)
        if not card.round:
            drawn["star"] = card.star_rect_img().adjusted(10, 10, -10, -10)   # the star image has padding
        check(drawn, shape, w, h, card.radius)


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("size", [80, 100, 120])
def test_analog_clock_never_overlaps(clock, shape, size):
    card = clock.ClockCard()
    for secs, date, loc in itertools.product((False, True), ("weekday", "full", "numeric", "none"), LOCALES[::2]):
        card.apply(opts("Clock", face="analog", shape=shape, time_size=size, seconds=secs, date=date, locale=loc))
        w, h = card.size
        aura_draw.render(lambda p: card.paint(p, NOW, 0.0), w + 2 * clock.M, h + 2 * clock.M, 1)
        drawn = dict(card.drawn)
        assert "dial" in drawn and ("date" in drawn) == (date != "none")
        if card.round:       # a round dial in a round card only has to fit as a circle, not as a box
            k = drawn["dial"].width() * (1 - 2 ** -0.5) / 2
            drawn["dial"] = drawn["dial"].adjusted(k, k, -k, -k)
        if not card.round:
            drawn["star"] = card.star_rect_img().adjusted(10, 10, -10, -10)
        check(drawn, shape, w, h, card.radius)


@pytest.mark.parametrize("loc", LOCALES)
def test_every_language_fits(clock, loc):
    card = clock.ClockCard()
    for shape, date in itertools.product(("rounded", "circle"), ("weekday", "full", "short", "numeric", "iso")):
        card.apply(opts("Clock", shape=shape, date=date, locale=loc))
        w, h = card.size
        aura_draw.render(lambda p: card.paint(p, NOW, 0.0), w + 2 * clock.M, h + 2 * clock.M, 1)
        drawn = dict(card.drawn)
        if not card.round:
            drawn["star"] = card.star_rect_img().adjusted(10, 10, -10, -10)
        check(drawn, shape, w, h, card.radius)
        assert card.drawn["date"].width() > 5, "the date came out empty"


def test_the_checker_catches_problems():
    with pytest.raises(AssertionError, match="overlaps"):
        check({"a": QRectF(10, 10, 50, 20), "b": QRectF(40, 15, 50, 20)}, "rounded", 400, 132, 26)
    with pytest.raises(AssertionError, match="sticks out"):
        check({"a": QRectF(2, 2, 50, 20)}, "circle", 200, 200, 0)
