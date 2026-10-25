"""
What each piece of drawing costs, 1.0 next to now (median and 95th percentile of many runs).
Times are CPU time used by this process, not wall time, so other programs on a busy machine don't
inflate them. Writes results/render_bench_<platform>.json. On Linux it runs offscreen, so it measures
the drawing code, not the Windows compositor.

    python bench/render_bench.py
"""
import os, sys, io, json, time, platform, statistics, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QPainter, QColor, QFont
import drive
import aura_draw


def timeit(fn, n):
    fn()
    t = []
    for _ in range(n):
        t0 = time.process_time()
        fn()
        t.append((time.process_time() - t0) * 1000)
    t.sort()
    return {"median_ms": round(statistics.median(t), 3), "p95_ms": round(t[int(0.95 * (len(t) - 1))], 3), "runs": n}


def canvas(w, h, dpr=2):
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    return img


def paint_into(img, fn):
    def go():
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        fn(p)
        p.end()
    return go


def main():
    app = QApplication.instance() or QApplication([])
    music = drive.load("aura_widget")
    clock = drive.load("aura_clock")
    gif = drive.load("aura_gif")
    orig = os.path.join(ROOT, "tests", "original")
    old_music = drive.load("aura_widget_v1", os.path.join(orig, "aura_widget_v1.py"))
    old_clock = drive.load("aura_clock_v1", os.path.join(orig, "aura_clock_v1.py"))
    old_clock.FONT_SPOTS = clock.FONT_SPOTS
    old_gif = drive.load("aura_gif_v1", os.path.join(orig, "aura_gif_v1.py"))
    out = {"machine": platform.platform(), "python": platform.python_version(),
           "qt_platform": os.environ["QT_QPA_PLATFORM"], "cpu_count": os.cpu_count(), "rows": {}}
    r = out["rows"]

    covers = []
    for seed in range(40):
        buf = io.BytesIO()
        aura_draw.sample_cover(640, seed=seed).convert("RGB").save(buf, "JPEG", quality=90)
        covers.append(buf.getvalue())
    from PIL import Image
    pil = [Image.open(io.BytesIO(c)).convert("RGB") for c in covers]
    def run(music, clock, gif, tag):
        i = iter(range(10 ** 9))
        r[f"{tag} new song (decode, palette, card layer)"] = timeit(lambda: music.Track("t", "a", covers[next(i) % 40]), 100)
        card = music.Card()
        card.cur = music.Track("Song title", "Artist", covers[0])
        card.dur_ms, card.pos_ms = 200_000, 80_000
        img = canvas(452, 184)
        r[f"{tag} music card frame"] = timeit(paint_into(img, card.paint), 300)
        card.old, card.t = music.Track("Old", "One", covers[1]), 0.5
        r[f"{tag} music card frame during crossfade"] = timeit(paint_into(img, card.paint), 300)
        card.old, card.hover = None, 1.0
        r[f"{tag} music card frame with controls"] = timeit(paint_into(img, card.paint), 300)

        t0 = time.process_time()
        ck = clock.ClockCard()
        r[f"{tag} clock startup (chrome star and card)"] = {"once_ms": round((time.process_time() - t0) * 1000, 1)}
        now = datetime.datetime(2026, 1, 1, 12, 34)
        t0 = time.process_time()
        paint_into(canvas(452, 184), lambda p: ck.paint(p, now, 0.0))()
        r[f"{tag} clock first frame (chrome digits made once)"] = {"once_ms": round((time.process_time() - t0) * 1000, 1)}
        r[f"{tag} clock frame"] = timeit(paint_into(canvas(452, 184), lambda p: ck.paint(p, now, 0.0)), 300)
        ck.effects = {"main": 0.0, 2: 0.0}
        r[f"{tag} clock frame while the star shines"] = timeit(
            paint_into(canvas(452, 184), lambda p: ck.paint(p, now, 1.0)), 300)

        q = gif.pil_to_qimage(aura_draw.sample_cover(480).resize((480, 270)))
        g = gif.GifCard(440, 160)
        r[f"{tag} gif frame scaled to the card (480x270 to 440x160)"] = timeit(lambda: g.set_frame(q), 300)
        g.set_frame(q)
        f = gif.pick_font(14, QFont.Weight.Medium)
        r[f"{tag} gif card frame"] = timeit(paint_into(canvas(492, 212), lambda p: g.paint(p, f)), 300)

    i = iter(range(10 ** 9))
    r["palette from a 640px cover"] = timeit(lambda: music.palette_from(pil[next(i) % 40]), 200)
    # run each version twice, interleaved, since this machine is shared and timings drift
    for rep in (1, 2):
        run(old_music, old_clock, old_gif, f"1.0 run{rep}")
        run(music, clock, gif, f"1.1 run{rep}")
    rc = music.Card()
    rc.set_look(music.Look({"shape": "circle"}))
    rc.cur = music.Track("Song title", "Artist", covers[0], look=rc.look)
    rc.dur_ms, rc.pos_ms = 200_000, 80_000
    r["1.1 round music card frame"] = timeit(paint_into(canvas(252, 252), rc.paint), 300)

    name = "linux" if sys.platform.startswith("linux") else sys.platform
    with open(os.path.join(ROOT, "results", f"render_bench_{name}.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    for k, v in r.items():
        print(f"{k:55s} {v}")
    del app


if __name__ == "__main__":
    main()
