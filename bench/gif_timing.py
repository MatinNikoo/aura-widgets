"""
How fast GIFs really play, 1.0 player vs the new one. Each player feeds a real GifCard, so every frame
pays the same decode and scale cost as in the widget. Speed 1.00 means the GIF plays at its own timing.
Linux offscreen numbers; Windows timer rounding is on top of this. Writes results/gif_timing.json.

    python bench/gif_timing.py
"""
import os, sys, json, time, tempfile, platform

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtWidgets import QApplication
import drive
from conftest import spin

SECONDS = 6
CASES = [(20, 1.0), (40, 1.0), (70, 1.0), (40, 2.0), (100, 0.5)]


def make_gif(path, delay, n=24, size=(480, 270)):
    frames = []
    for i in range(n):
        im = Image.new("RGB", size, (i * 10 % 255, 90, 200 - i * 7 % 200))
        im.paste((250, 220, 40), (i * 15 % size[0], 60, i * 15 % size[0] + 80, 200))
        frames.append(im)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=delay, loop=0)
    return path


def play(mod, card_mod, path, speed):
    app = QApplication.instance()
    card = card_mod.GifCard(440, 160)
    p = mod.GifPlayer()
    shown = []
    p.frame.connect(lambda img: (card.set_frame(img), shown.append(time.monotonic())))
    p.set_speed(speed)
    p.open(path)
    spin(app, SECONDS * 1000)
    p.set_paused(True)
    return shown


def main():
    app = QApplication.instance() or QApplication([])
    old = drive.load("aura_gif_v1", os.path.join(ROOT, "tests", "original", "aura_gif_v1.py"))
    new = drive.load("aura_gif")
    tmp = tempfile.mkdtemp()
    rows = []
    for delay, speed in CASES:
        path = make_gif(os.path.join(tmp, f"d{delay}.gif"), delay)
        step = max(10, int(delay / speed))
        for name, mod in (("v1_0", old), ("v1_1", new)):
            shown = play(mod, mod, path, speed)
            gaps = [b - a for a, b in zip(shown[1:], shown[2:])]       # skip the first frame
            mean = sum(gaps) / len(gaps)
            rows.append({"version": name, "delay_ms": delay, "speed": speed, "frames": len(shown),
                         "wanted_ms": step, "mean_gap_ms": round(mean * 1000, 2),
                         "playback_speed": round(step / (mean * 1000), 3)})
            print(rows[-1])
    out = {"python": platform.python_version(), "qt_platform": os.environ["QT_QPA_PLATFORM"],
           "seconds_each": SECONDS, "frame_size": [480, 270], "card": [440, 160], "rows": rows}
    with open(os.path.join(ROOT, "results", "gif_timing.json"), "w") as f:
        json.dump(out, f, indent=2)
    del app


if __name__ == "__main__":
    main()
