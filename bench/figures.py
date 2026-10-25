"""
Figures for the README, made only from the saved results/*.json files.
    python bench/figures.py
"""
import os, json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "figures")
OLD, NEW = "#9a96a3", "#5b4bb7"
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})


def load(name):
    path = os.path.join(ROOT, "results", name)
    return json.load(open(path)) if os.path.exists(path) else None


def gif_speed():
    d = load("gif_timing.json")
    if not d:
        return
    cases = []
    for r in d["rows"]:
        key = f"{r['delay_ms']} ms frames\nat {r['speed']:g}x"
        if key not in cases:
            cases.append(key)
    old = [r["playback_speed"] for r in d["rows"] if r["version"] == "v1_0"]
    new = [r["playback_speed"] for r in d["rows"] if r["version"] == "v1_1"]
    x = np.arange(len(cases))
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    ax.bar(x - 0.18, old, 0.36, color=OLD, label="1.0")
    ax.bar(x + 0.18, new, 0.36, color=NEW, label="1.1")
    ax.axhline(1, color="#333", lw=0.8, ls="--")
    ax.set_xticks(x, cases)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("playback speed (1 = correct)")
    ax.set_title("How fast GIFs really play (Linux, offscreen)")
    ax.legend(frameon=False, loc="center left", bbox_to_anchor=(1.0, 0.5))
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "gif_speed.png"), dpi=160)


def idle():
    d = load("idle.json") or load("idle_quick.json")
    if not d:
        return
    scen = []
    for r in d["rows"]:
        if r["scenario"] not in scen:
            scen.append(r["scenario"])
    get = lambda v, s, k: next(r[k] for r in d["rows"] if r["version"] == v and r["scenario"] == s)
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 2.9))
    for ax, key, label in ((axes[0], "cpu_ms_per_min", "CPU ms per minute"),
                           (axes[1], "timer_wakeups_per_s", "timer wakeups per second")):
        y = np.arange(len(scen))
        ax.barh(y + 0.18, [get("1.0", s, key) for s in scen], 0.36, color=OLD, label="1.0")
        ax.barh(y - 0.18, [get("1.1", s, key) for s in scen], 0.36, color=NEW, label="1.1")
        ax.set_yticks(y, scen)
        ax.invert_yaxis()
        ax.set_xlabel(label)
    axes[1].set_yticklabels([])
    axes[0].legend(frameon=False)
    fig.suptitle(f"What each widget costs just sitting there ({d['measured_s']} s each, Linux, offscreen)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "idle.png"), dpi=160)


def soak():
    d = load("soak.json") or load("soak_short.json")
    if not d:
        return
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    colors = {"music": "#5b4bb7", "clock": "#2b8a7e", "gif": "#c0703a"}
    for kind, run in d["runs"].items():
        t = np.array([s[0] for s in run["samples"]]) / 60
        y = np.array([s[1] for s in run["samples"]])
        f = run["fit"]
        label = f"{kind}: {f['slope_mb_per_hour']:+.1f} MB/hour"
        if kind == "music":
            label += f" over {run['songs_seen']} songs"
        ax.plot(t, y, color=colors[kind], lw=1.2, label=label)
    ax.axvspan(0, d["warmup_s"] / 60, color="#eee", lw=0)
    ax.set_xlabel("minutes (shaded part is warmup, not fit)")
    ax.set_ylabel("memory (RSS, MB)")
    ax.set_title("Memory during the squeezed long run (Linux, offscreen)")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "soak.png"), dpi=160)


def main():
    os.makedirs(OUT, exist_ok=True)
    gif_speed()
    idle()
    soak()
    print(sorted(os.listdir(OUT)))


if __name__ == "__main__":
    main()
