"""
Makes the README pictures: docs/media/hero.png, docs/media/demo.gif and docs/media/shapes.png.
Everything is drawn by the widgets' own drawing code, offscreen. The songs are from my playlist and the album
covers are read from data/demo/covers, which isn't in the repo. On Linux the text font is Inter, since Segoe UI
is a Windows font.

    python bench/demo.py
"""
import os, sys, io, math, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw, ImageFilter
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QPainter, QColor, QImageReader, QFont
from PyQt6.QtCore import QRectF, QPointF, QEasingCurve
import drive
from aura_draw import render

ART = {  # cover file in data/demo/covers: (song title shown on the card, artist line)
    "innerbloom": ("Innerbloom", "RÜFÜS DU SOL"),
    "if-your-girl-only-knew": ("If Your Girl Only Knew", "Fahlberg x Arodes"),
    "neverender": ("Neverender", "Justice & Tame Impala"),
    "inner-light": ("Inner Light", "Elderbrook & Bob Moses"),
    "daylight": ("Daylight (Matin Remix)", "TCTS & Hayley May"),
}
DUR = {"innerbloom": 579_000, "if-your-girl-only-knew": 199_000, "neverender": 267_000, "inner-light": 258_000, "daylight": 137_000}  # real lengths, ms
DATA = os.path.join(ROOT, "data", "demo")
OUT = os.path.join(ROOT, "docs", "media")


def fetch():
    """The album covers, read from data/demo/covers/<name>.jpg. They aren't in the repo (data/ is ignored),
    so drop your own covers there with these names before running this."""
    covers = {}
    for name in ART:
        path = os.path.join(DATA, "covers", f"{name}.jpg")
        if not os.path.exists(path):
            raise SystemExit(f"missing {path}, put the album cover there first")
        with open(path, "rb") as f:
            covers[name] = f.read()
    return covers


def wallpaper(w, h):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(58 + 40 * t), int(64 + 20 * t), int(92 - 10 * t)))
    for x, y, r, c in ((0.2, 0.3, 0.35, (120, 90, 160)), (0.8, 0.75, 0.4, (60, 120, 140)), (0.55, 0.1, 0.25, (170, 110, 120))):
        d.ellipse([(x - r) * w, (y - r) * w, (x + r) * w, (y + r) * w], fill=c)
    return im.filter(ImageFilter.GaussianBlur(w / 12))


def box_gif_frames(path, size=(440, 160), step=80, focus_y=0.8):
    """Your own GIF for the box (data/demo/box.gif or box.webp), cropped to fill it the way the widget's fill mode does,
    and resampled to one frame every 80 ms so it plays at its real speed in the demo. focus_y picks which part
    stays in view when the height is cropped, like dragging the GIF inside the box."""
    src = Image.open(path)
    shots, times, t = [], [], 0
    for i in range(getattr(src, "n_frames", 1)):
        src.seek(i)
        shots.append(src.convert("RGB"))
        times.append(t)
        d = src.info.get("duration") or 0
        t += d if d > 10 else 100      # like browsers, a frame with no real duration shows for 100 ms
    total = max(t, step)
    frames = []
    for k in range(int(total // step)):
        j = max(i for i, s in enumerate(times) if s <= k * step)
        im = shots[j]
        s = max(size[0] / im.width, size[1] / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.Resampling.LANCZOS)
        x, y = (im.width - size[0]) // 2, int((im.height - size[1]) * focus_y)
        frames.append(im.crop((x, y, x + size[0], y + size[1])))
    return frames


def gif_frames(data, n=24, size=(440, 160)):
    """A slow pan across a painting, saved as a real GIF and read back frame by frame with Qt.
    If data/demo/box.gif (or box.webp) exists, that animation goes in the box instead."""
    own = next((os.path.join(DATA, f) for f in ("box.gif", "box.webp") if os.path.exists(os.path.join(DATA, f))), None)
    if own:
        out = []
        for im in box_gif_frames(own, size):   # straight to Qt, a GIF round trip would merge repeated frames
            buf = io.BytesIO()
            im.save(buf, "PNG")
            out.append(QImage.fromData(buf.getvalue(), "PNG"))
        return out
    im = Image.open(io.BytesIO(data)).convert("RGB")
    k = max(size[0] * 1.35 / im.width, size[1] * 1.35 / im.height)
    im = im.resize((int(im.width * k), int(im.height * k)), Image.Resampling.LANCZOS)
    frames = []
    for i in range(n):
        t = (1 - math.cos(2 * math.pi * i / n)) / 2
        x = int(t * (im.width - size[0]))
        y = int(t * (im.height - size[1]))
        frames.append(im.crop((x, y, x + size[0], y + size[1])))
    path = os.path.join(DATA, "pan.gif")
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    r = QImageReader(path)
    out = []
    while r.canRead():
        img = r.read()
        if img.isNull():
            break
        out.append(img)
    return out


def put(p, x, y, paint, size, m, dpr):
    """Draws a card into its own transparent image first and then lays that on the picture, which is how a
    translucent window reaches the desktop. Painting straight onto the wallpaper leaves dark edges."""
    p.drawImage(QPointF(x, y), render(paint, size[0] + 2 * m, size[1] + 2 * m, dpr))


def blend(a, b, k):
    """a fading into b, k from 0 to 1."""
    out = QImage(a)
    p = QPainter(out)
    p.setOpacity(k)
    p.drawImage(0, 0, b)
    p.end()
    return out


def save_gif(frames, path, fps):
    """One shared palette for the whole clip, so colors don't flicker between frames."""
    import subprocess, tempfile, imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as d:
        for i, im in enumerate(frames):
            im.save(os.path.join(d, f"f{i:04d}.png"))
        src = ["-framerate", str(fps), "-i", os.path.join(d, "f%04d.png")]
        pal = os.path.join(d, "pal.png")
        subprocess.run([ff, "-y", *src, "-vf", "scale=960:-1:flags=lanczos,palettegen=max_colors=256:stats_mode=full:reserve_transparent=0", pal], check=True,
                       capture_output=True)
        subprocess.run([ff, "-y", *src, "-i", pal, "-lavfi", "scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
                        "-loop", "0", path], check=True, capture_output=True)


def ease(t):
    c = QEasingCurve(QEasingCurve.Type.InOutCubic)
    return c.valueForProgress(max(0.0, min(1.0, t)))


def main():
    app = QApplication.instance() or QApplication([])
    covers = fetch()
    music = drive.load("aura_widget")
    clock = drive.load("aura_clock")
    gif = drive.load("aura_gif")
    os.makedirs(OUT, exist_ok=True)

    ids = list(ART)
    tracks = [music.Track(*ART[i], covers[i]) for i in ids]
    card = music.Card()
    round_card = music.Card()
    round_card.set_look(music.Look({"shape": "circle"}))
    round_track = music.Track(*ART[ids[2]], covers[ids[2]], look=round_card.look)
    round_card.cur = round_track
    round_card.dur_ms, round_card.pos_ms = DUR[ids[2]], 74_000
    ck = clock.ClockCard()
    gcard = gif.GifCard(440, 160)
    frames = gif_frames(covers[ids[4]])
    font = gif.pick_font(14, QFont.Weight.Medium)
    ck2 = clock.ClockCard()
    ck2.apply(dict(zip(("face", "shape", "seconds", "date"), ("analog", "pill", True, "weekday")),
                    h24=False, radius=26, border="thin", style="chrome", font="", time_size=100, background="",
                    locale="", lowercase=True, background_dim=45, shadow=True))
    gcard2 = gif.GifCard(440, 160)
    gcard2.apply({"shape": "squircle", "radius": 26, "border": "thin", "mode": "fill", "shadow": True})
    W, H = 1000, 520
    wall = gif.pil_to_qimage(wallpaper(W, H))

    def frame(t, dpr=1, scene=False):
        img = QImage(int(W * dpr), int(H * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, W, H), wall)

        # now playing: song A, crossfade to B at 1.4 s, hover, then drag the bar to seek
        card.cur, card.old, card.t = tracks[0], None, 1.0
        if t >= 1.4:
            card.old, card.cur, card.t = tracks[0], tracks[1], ease((t - 1.4) / 1.4)
            if card.t >= 1:
                card.old = None
        card.dur_ms = DUR[ids[1]] if t >= 1.4 else DUR[ids[0]]
        card.pos_ms = (60_000 + t * 1000) if t < 1.4 else (2_000 + (t - 1.4) * 1000)
        card.playing = False
        card.hover = max(0.0, min(1.0, (t - 3.0) / 0.25)) * (1 - max(0.0, min(1.0, (t - 5.4) / 0.25)))
        card.preview = None
        if 3.6 <= t < 4.8:
            card.preview = 0.25 + 0.5 * ease((t - 3.6) / 0.9)
        elif t >= 4.8:
            card.pos_ms = 0.75 * DUR[ids[1]] + (t - 4.8) * 1000
        if scene and t >= 6.0:
            # back to the first song so the loop closes
            card.old, card.cur, card.t = tracks[1], tracks[0], ease((t - 6.0) / 1.4)
            if card.t >= 1:
                card.old = None
            card.dur_ms = DUR[ids[0]]
            card.pos_ms = 60_000 + (t - 8.0) * 1000
        elif scene and t < 1.4:
            card.pos_ms = 60_000 + t * 1000
        put(p, 28, 40, card.paint, card.size, music.M, dpr)

        # clock with its star shining and a few twinkles
        ck_, gc_ = (ck2, gcard2) if scene else (ck, gcard)
        ck_.effects = {k: v for k, v in {"main": 0.6, 2: 0.2, 5: 1.5, 7: 3.2, 1: 4.1}.items() if v <= t}
        # the analog clock ticks once a second like the real one
        now = datetime.datetime(2026, 10, 22, 21, 47, 20) + datetime.timedelta(seconds=math.floor(t))
        put(p, 28, 290, lambda q: ck_.paint(q, now if scene else datetime.datetime(2026, 10, 22, 21, 47), t), ck_.size, clock.M, dpr)

        # GIF box, playing at the GIF's own 80 ms per frame
        g = frames[int(t * 1000 / 80) % len(frames)]
        gc_.set_frame(g)
        put(p, 506, 30, lambda q: gc_.paint(q, font), (gc_.w, gc_.h), gif.M, dpr)

        # the round music card
        round_card.pos_ms = 74_000 + t * 1000
        put(p, 616, 252, round_card.paint, round_card.size, music.M, dpr)
        p.end()
        return img

    frame(1.0, 2).save(os.path.join(OUT, "hero.png"))
    fps, length, fade = 20, 8.0, 0.5       # the last half second blends into the start so the loop closes
    pil = []
    for i in range(int(length * fps)):
        t = i / fps
        q = frame(t, scene=True)
        if t >= length - fade:
            a = (t - (length - fade)) / fade
            q = blend(q, frame(t - length, scene=True), a)
        q = q.convertToFormat(QImage.Format.Format_RGB888)
        ptr = q.constBits()
        ptr.setsize(q.sizeInBytes())
        pil.append(Image.frombuffer("RGB", (q.width(), q.height()), bytes(ptr), "raw", "RGB", q.bytesPerLine(), 1))
    save_gif(pil, os.path.join(OUT, "demo.gif"), fps)

    shapes(music, clock, gif, covers, tracks, frames, font)
    for f in ("hero.png", "demo.gif", "shapes.png"):
        print(os.path.join(OUT, f), os.path.getsize(os.path.join(OUT, f)) // 1024, "KB")
    del app


def shapes(music, clock, gif, covers, tracks, frames, font):
    """One picture of the shape settings: each widget in a few shapes."""
    ids = list(ART)
    cells = []
    for n, (shape, extra) in enumerate((("pill", {}), ("squircle", {"text_size": 115}), ("square", {"border": "bold"}),
                                        ("circle", {}))):
        song = ids[1 + n]          # a different song in each shape
        c = music.Card()
        c.set_look(music.Look(dict(shape=shape, **extra)))
        c.cur = music.Track(*ART[song], covers[song], look=c.look)
        c.dur_ms, c.pos_ms = DUR[song], min(121_000, DUR[song] // 2)
        cells.append((c.size, music.M, c.paint))
    for shape, o in (("pill", {}), ("circle", {"locale": "fa_IR", "h24": True}), ("squircle", {"style": "flat"})):
        k = clock.ClockCard()
        base = {"face": "digital", "h24": False, "seconds": False, "shape": shape, "radius": 26, "border": "thin", "style": "chrome",
                "font": "", "time_size": 100, "background": "", "date": "weekday", "locale": "", "lowercase": True,
                "background_dim": 45, "shadow": True}
        base.update(o)
        k.apply(base)
        cells.append((k.size, clock.M, (lambda kk: lambda p: kk.paint(p, datetime.datetime(2026, 10, 22, 9, 5), 0.0))(k)))
    # a square GIF suits the round box, so data/demo/box_square.gif (or .webp) goes there when it exists
    square = next((os.path.join(DATA, f) for f in ("box_square.gif", "box_square.webp")
                   if os.path.exists(os.path.join(DATA, f))), None)
    round_frame = frames[6 % len(frames)]
    if square:
        im = box_gif_frames(square, (200, 200), focus_y=0.5)
        im = im[len(im) * 3 // 5]
        buf = io.BytesIO()
        im.save(buf, "PNG")
        round_frame = QImage.fromData(buf.getvalue(), "PNG")
    for shape, size, fr in (("circle", (200, 200), round_frame), ("pill", (440, 160), frames[6 % len(frames)])):
        g = gif.GifCard(*size)
        g.apply({"shape": shape, "radius": 26, "border": "thin", "mode": "fill", "shadow": True})
        g.set_frame(fr)
        cells.append(((size[0], size[1]), gif.M, (lambda gg: lambda p: gg.paint(p, font))(g)))
    cols, cw, chh = 3, 520, 300
    rows = (len(cells) + cols - 1) // cols
    wall = gif.pil_to_qimage(wallpaper(cols * cw, rows * chh))
    img = QImage(cols * cw * 2, rows * chh * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, cols * cw, rows * chh), wall)
    for i, ((w, h), m, paint) in enumerate(cells):
        x, y = (i % cols) * cw + (cw - w - 2 * m) / 2, (i // cols) * chh + (chh - h - 2 * m) / 2
        put(p, x, y, paint, (w, h), m, 2)
    p.end()
    img.save(os.path.join(OUT, "shapes.png"))


if __name__ == "__main__":
    main()
