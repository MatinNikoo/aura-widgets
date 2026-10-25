"""
Is the text on the now playing card readable for every cover? For each picture this builds the real card,
takes the actual background pixels under each line of text, blends the real text color (with its
transparency) on top, and computes the WCAG contrast ratio pixel by pixel. A row's score is its 5th
percentile, so a bright patch behind a few letters still counts. WCAG asks 4.5:1 for text this size.
Writes results/contrast.json and docs/figures/contrast.png.

    python bench/fetch_covers.py      (once, downloads the pictures)
    python bench/contrast.py
"""
import os, sys, json, glob

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage
import drive

NEED = 4.5


def to_array(img):
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return np.frombuffer(bytes(ptr), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()]


def lin(c):
    c = c / 255.0
    return np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def luminance(rgb):
    l = lin(rgb)
    return 0.2126 * l[..., 0] + 0.7152 * l[..., 1] + 0.0722 * l[..., 2]


def row_contrast(bg, color):
    """bg: HxWx3 pixels behind the text, color: QColor of the text (its alpha blends it with bg)."""
    a = color.alpha() / 255
    fg = np.array([color.red(), color.green(), color.blue()], float)
    shown = a * fg + (1 - a) * bg
    l1, l2 = luminance(shown), luminance(bg)
    hi, lo = np.maximum(l1, l2), np.minimum(l1, l2)
    return float(np.percentile((hi + 0.05) / (lo + 0.05), 5))


def score(mod, data, look=None):
    """Worst 5% contrast of title, artist and times on the real card for one cover."""
    card = mod.Card()
    if look is not None:
        card.set_look(look)
    if hasattr(card, "look"):
        tr = mod.Track("x", "y", data, "cover", card.look)
        card.cur = tr
        card.dur_ms = 200_000
        L, round_card = card.layout(), card.look.round
    else:                                                  # 1.0 had fixed positions
        tr = mod.Track("x", "y", data)
        L = {"x": mod.TEXT_X, "title_r": mod.W - mod.PAD_R, "title": 49, "artist": 69, "time": 111}
        round_card = False
    px = to_array(tr.layer)[..., :3].astype(float)          # the layer is drawn at 2x
    rows = {}
    if round_card:
        spans = {"title": (L["title"], 15, 5), "artist": (L["artist"], 13, 4), "times": (L["time"], 10, 3)}
        for name, (y, up, down) in spans.items():
            a, b = L[(name if name != "times" else "time") + "_span"]
            region = px[int((y - up) * 2):int((y + down) * 2), int(a * 2):int(b * 2)]
            rows[name] = region
    else:
        x0, x1 = L["x"], L["title_r"]
        rows["title"] = px[int((L["title"] - 15) * 2):int((L["title"] + 5) * 2), int(x0 * 2):int(x1 * 2)]
        rows["artist"] = px[int((L["artist"] - 12) * 2):int((L["artist"] + 4) * 2), int(x0 * 2):int(x1 * 2)]
        rows["times"] = px[int((L["time"] - 9) * 2):int((L["time"] + 3) * 2), int(x0 * 2):int(x1 * 2)]
    c = tr.colors
    times_color = mod.with_alpha(c["sub"], getattr(tr, "time_alpha", 170))
    return {"title": row_contrast(rows["title"], c["text"]),
            "artist": row_contrast(rows["artist"], c["sub"]),
            "times": row_contrast(rows["times"], times_color)}


def main():
    app = QApplication.instance() or QApplication([])
    files = sorted(glob.glob(os.path.join(ROOT, "data", "covers", "*.jpg")))
    if not files:
        sys.exit("no pictures, run bench/fetch_covers.py first")
    old = drive.load("aura_widget_v1", os.path.join(ROOT, "tests", "original", "aura_widget_v1.py"))
    new = drive.load("aura_widget")
    datas = [open(f, "rb").read() for f in files]
    out = {"n_covers": len(files), "need": NEED, "source": "results/covers_manifest.json", "versions": {}}
    for name, mod, look in (("1.0", old, None), ("1.1", new, None),
                            ("1.1 high contrast", new, new.Look({"high_contrast": True})),
                            ("1.1 round card", new, new.Look({"shape": "circle"}))):
        per = [score(mod, d, look) for d in datas]
        rows = {}
        for k in ("title", "artist", "times"):
            v = np.array([p[k] for p in per])
            rows[k] = {"min": round(float(v.min()), 2), "median": round(float(np.median(v)), 2),
                       "below_4_5": int((v < NEED).sum()), "below_3": int((v < 3).sum())}
        out["versions"][name] = {"rows": rows, "per_cover": [dict(file=os.path.basename(f), **p) for f, p in zip(files, per)]}
        print(name, rows, flush=True)
    old_rows, new_rows = out["versions"]["1.0"]["per_cover"], out["versions"]["1.1"]["per_cover"]
    out["covers_changed_by_default"] = sum(
        any(abs(a[k] - b[k]) > 0.01 for k in ("title", "artist", "times")) for a, b in zip(old_rows, new_rows))
    print("covers whose text changed with default settings:", out["covers_changed_by_default"])
    with open(os.path.join(ROOT, "results", "contrast.json"), "w") as f:
        json.dump(out, f, indent=2)
    figure(out)
    del app


def figure(out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = list(out["versions"])
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), sharey=True)
    for ax, row in zip(axes, ("title", "artist", "times")):
        data = [[p[row] for p in out["versions"][n]["per_cover"]] for n in names]
        ax.boxplot(data, widths=0.5, showfliers=True)
        for i, d in enumerate(data, 1):
            ax.scatter(np.random.default_rng(0).normal(i, 0.05, len(d)), d, s=6, alpha=0.4, color="#4a4458")
        ax.axhline(NEED, color="#c0392b", lw=1, ls="--")
        ax.axhline(3, color="#c0392b", lw=1, ls=":")
        ax.set_xticks(range(1, len(names) + 1), [n.replace("1.1 ", "1.1\n") for n in names], fontsize=8)
        ax.set_title(row, fontsize=10)
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("contrast ratio (worst 5% of pixels)")
    fig.suptitle(f"Text contrast on the now playing card, {out['n_covers']} public domain pictures "
                 f"(dashed line is WCAG 4.5:1, dotted is the 3:1 floor)", fontsize=10)
    fig.tight_layout()
    os.makedirs(os.path.join(ROOT, "docs", "figures"), exist_ok=True)
    fig.savefig(os.path.join(ROOT, "docs", "figures", "contrast.png"), dpi=150)


if __name__ == "__main__":
    main()
