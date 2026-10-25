"""Drawing code for all three cards, run offscreen."""
import colorsys, datetime

import pytest
from PIL import Image

from conftest import cover_bytes
import aura_common
import aura_draw


class Empty:
    def value(self, key, default=None):
        return default


def render(card, w, h, scale=2):
    from PyQt6.QtGui import QImage, QPainter, QColor
    img = QImage(int(w * scale), int(h * scale), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(scale)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    card.paint(p)
    p.end()
    return img


# ---------------------------------------------------------------- now playing
def hue_of(c):
    return colorsys.rgb_to_hsv(c.red() / 255, c.green() / 255, c.blue() / 255)[0]


def test_palette_follows_the_cover(music):
    pal = music.palette_from(Image.new("RGB", (200, 200), (30, 90, 220)))
    assert set(pal) == {"bg", "text", "sub", "bar"}
    assert abs(hue_of(pal["bg"]) - colorsys.rgb_to_hsv(30 / 255, 90 / 255, 220 / 255)[0]) < 0.02
    assert pal["sub"].alpha() == 190


def test_grey_cover_gives_grey_card(music):
    pal = music.palette_from(Image.new("RGB", (200, 200), (128, 128, 128)))
    for c in pal.values():
        assert c.red() == c.green() == c.blue()


def test_black_border_does_not_win(music):
    """A mostly black cover with a colored square should still pick the color."""
    im = Image.new("RGB", (200, 200), (5, 5, 5))
    im.paste((230, 60, 40), (60, 60, 140, 140))
    pal = music.palette_from(im)
    r, g, b = pal["bar"].red(), pal["bar"].green(), pal["bar"].blue()
    assert r > g and r > b


def test_track_handles_bad_and_odd_covers(music):
    assert music.Track("a", "b", b"not an image").cover is None
    t = music.Track("a", "b", cover_bytes(size=(640, 360)))       # wide video thumbnail
    assert t.cover.width() == t.cover.height() == music.ART * 2
    assert music.Track(None, None).title == ""


def test_card_draws_every_state(music):
    card = music.Card()
    img = render(card, music.W + 2 * music.M, music.H + 2 * music.M)
    assert not img.isNull()
    card.old, card.cur, card.t = card.cur, music.Track("Song", "Artist", cover_bytes()), 0.5
    card.dur_ms, card.pos_ms, card.hover = 200_000, 50_000, 1.0
    render(card, music.W + 2 * music.M, music.H + 2 * music.M)
    assert set(card.hit) == {"prev", "toggle", "next"}
    card.hover = 0
    render(card, music.W + 2 * music.M, music.H + 2 * music.M)
    assert card.hit == {}


def test_position_never_runs_past_the_end(music):
    card = music.Card()
    card.pos_ms, card.dur_ms, card.playing = 199_000, 200_000, True
    card.anchor -= 10
    assert card.position() == 200_000
    assert music.fmt(61_999) == "1:01" and music.fmt(-5) == "0:00"


# ---------------------------------------------------------------- GIF card
def test_gif_card_fill_and_fit(gif, app):
    from PyQt6.QtGui import QImage, QColor
    card = gif.GifCard(440, 160)
    frame = QImage(400, 400, QImage.Format.Format_ARGB32)
    frame.fill(QColor(255, 0, 0))
    card.set_frame(frame)
    assert card.frame.width() / 2 >= 440 and card.frame.height() / 2 >= 160   # fills the card
    ox, oy = card.overflow()
    assert ox == 0 and oy > 0
    card.fit = True
    card.set_frame(frame)
    card.set_backdrop(frame)
    assert card.frame.height() / 2 <= 160 and card.backdrop is not None
    render(card, 492, 212)
    card.set_frame(None)
    assert card.frame is None
    render(card, 492, 212)


# ---------------------------------------------------------------- clock
def test_clock_strings(clock, app):
    card = clock.ClockCard()
    t = datetime.datetime(2026, 3, 9, 0, 5, 7)
    assert card.strings(t) == ("12:05", "am", "monday, march 9")
    card.seconds = True
    assert card.strings(t)[0] == "12:05:07"
    card.h24, card.seconds = True, False
    assert card.strings(datetime.datetime(2026, 3, 9, 17, 5))[:2] == ("17:05", "")


def test_clock_next_tick(clock):
    assert clock.ms_to_next_tick(datetime.datetime(2026, 1, 1, 9, 30, 15, 250_000), False) == 44_770
    assert clock.ms_to_next_tick(datetime.datetime(2026, 1, 1, 9, 30, 15, 250_000), True) == 770
    assert clock.ms_to_next_tick(datetime.datetime(2026, 1, 1, 9, 30, 59, 990_000), True) == 50


def test_chrome_keeps_the_shape(clock):
    mask = Image.new("L", (80, 80), 0)
    mask.paste(255, (20, 20, 60, 60))
    out = clock.chrome(mask, 10)
    assert out.mode == "RGBA" and out.size == mask.size
    assert out.getchannel("A").tobytes() == mask.tobytes()


def test_chrome_without_numpy(clock, monkeypatch):
    monkeypatch.setattr(clock, "np", None)
    mask = Image.new("L", (40, 40), 255)
    assert clock.chrome(mask, 5).size == (40, 40)


def test_glyphs_are_cached(clock, app):
    """Each character is turned into chrome once, so a day of minutes doesn't grow the cache."""
    from PyQt6.QtGui import QImage, QPainter
    card = clock.ClockCard()
    img = QImage(452, 184, QImage.Format.Format_ARGB32_Premultiplied)
    start = datetime.datetime(2026, 1, 1, 0, 0)
    for minute in range(0, 24 * 60, 7):
        p = QPainter(img)
        card.paint(p, start + datetime.timedelta(minutes=minute))
        p.end()
    assert set(card.big.cache) <= set("0123456789:")
    assert set(card.small.cache) <= set("apm")


@pytest.mark.parametrize("now", [datetime.datetime(2026, 12, 31, 23, 59, 59), datetime.datetime(2026, 7, 4, 12, 0)])
def test_clock_draws(clock, app, now):
    card = clock.ClockCard()
    from PyQt6.QtGui import QImage, QPainter
    img = QImage(452 * 2, 184 * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2)
    p = QPainter(img)
    card.paint(p, now)
    p.end()


def test_sharper_art_on_high_dpi(music, gif, app, monkeypatch):
    from PyQt6.QtGui import QImage, QColor
    monkeypatch.setattr(music, "DETAIL", 3)
    t = music.Track("a", "b", cover_bytes())
    assert t.cover.width() == music.ART * 3 and t.layer.devicePixelRatio() == 3
    card = music.Card()
    card.cur = t
    render(card, 452, 184, 3)
    monkeypatch.setattr(gif, "DETAIL", 3)
    g = gif.GifCard(440, 160)
    frame = QImage(400, 400, QImage.Format.Format_ARGB32)
    frame.fill(QColor(255, 0, 0))
    g.set_frame(frame)
    assert g.frame.devicePixelRatio() == 3 and g.frame.width() >= 440 * 3
    assert g.overflow()[0] == 0
    render(g, 492, 212, 3)


def test_text_stays_readable_on_bright_covers(music, app):
    """A pale cover lifts the card's background, so the dim artist and time lines get brighter until they
    reach 3:1 (4.5:1 with high contrast). A dark cover keeps the exact 1.0 colors."""
    dark = music.Track("a", "b", cover_bytes((20, 30, 60)))
    assert dark.colors["sub"] == dark.palette["sub"] and dark.time_alpha == 170

    pale = music.Track("a", "b", cover_bytes((250, 245, 235), patch=((0, 0, 300, 120), (255, 255, 255))))

    def band(name):
        return music.band_pixels(pale.layer, music.TEXT_BANDS[name], step=1)      # every pixel this time
    assert music.contrast(pale.colors["text"], band("title")) >= 3
    assert music.contrast(pale.colors["sub"], band("artist")) >= 3
    assert music.contrast(music.with_alpha(pale.colors["sub"], pale.time_alpha), band("times")) >= 3

    pale.relayer(music.Look({"high_contrast": True}))
    for name, color in (("title", pale.colors["text"]), ("artist", pale.colors["sub"]),
                        ("times", music.with_alpha(pale.colors["sub"], pale.time_alpha))):
        assert music.contrast(color, band(name)) >= 4.5, name


def test_blurred_cover_background(music, app):
    """The blurred cover option lets more of the cover show, and the text still gets the same contrast floor."""
    tinted = music.Track("a", "b", cover_bytes((200, 40, 60)))
    soft = music.Track("a", "b", cover_bytes((200, 40, 60)), look=music.Look({"backdrop": "blur"}))
    assert tinted.layer != soft.layer
    assert tinted.layer == music.Track("a", "b", cover_bytes((200, 40, 60)), look=music.Look({"backdrop": "tint"})).layer
    soft_pale = music.Track("a", "b", cover_bytes((250, 245, 235), patch=((0, 0, 300, 120), (255, 255, 255))),
                            look=music.Look({"backdrop": "blur"}))
    for name, color in (("title", soft_pale.colors["text"]), ("artist", soft_pale.colors["sub"])):
        assert music.contrast(color, music.band_pixels(soft_pale.layer, music.TEXT_BANDS[name], step=1)) >= 3, name
    assert music.Look({"backdrop": "blur"}).layer_key() != music.Look().layer_key()


def test_analog_hands_point_the_right_way(clock, app):
    """At 3:00 the hour hand points right and the minute hand up, and at 9:00 the hour hand points left."""
    card = clock.ClockCard()
    card.apply(dict(aura_common.options(Empty(), "Clock"), face="analog", date="none"))
    cx, cy, r, *_ = card.dial()

    def light(now, dx, dy):
        img = aura_draw.render(lambda p: card.paint(p, now, 0.0), 452, 184, 1)
        c = img.pixelColor(int(clock.M + cx + dx * r), int(clock.M + cy + dy * r))
        return c.red() > 140

    three = datetime.datetime(2026, 3, 9, 3, 0, 0)
    nine = datetime.datetime(2026, 3, 9, 9, 0, 0)
    assert light(three, 0.3, 0) and not light(three, -0.3, 0)
    assert light(three, 0, -0.5) and not light(three, 0, 0.5)
    assert light(nine, -0.3, 0) and not light(nine, 0.3, 0)


def test_music_widget_does_not_load_numpy(music):
    """NumPy costs about 13 MB, and the music widget only needs a little math."""
    import ast
    src = open(music.__file__, encoding="utf-8").read()
    names = {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))
             for a in n.names} | {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    assert "numpy" not in names
