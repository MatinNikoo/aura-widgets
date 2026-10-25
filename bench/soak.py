"""
Long run memory check with time squeezed. Each real widget runs offscreen with fake Windows media:
  music  a new song (with new cover art) 4 times a second, so 5 minutes is about 1200 songs
  clock  repaints every 50 ms with seconds on, and a shine plus a twinkle every 300 ms
  gif    a folder of GIFs at 2x speed, switching GIF every 3 seconds
Memory (RSS) is sampled every 2 seconds. After a 30 second warmup a line is fit to it; a widget that
leaks shows a clear upward slope. Writes results/soak.json.

    python bench/soak.py              5 minutes per widget
    python bench/soak.py --minutes 1
"""
import os, sys, json, subprocess, tempfile, textwrap, platform

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MINUTES = float(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 5.0
WARMUP = 30

CHILD = textwrap.dedent("""
    import os, sys, json, time, io, random
    sys.path.insert(0, {tests!r})
    sys.path.insert(0, {root!r})
    import fake_winrt, drive, aura_draw
    from PyQt6.QtCore import QTimer, QSettings
    from conftest import make_gif
    os.environ.pop("AURA_OLD_ORG", None)    # conftest turns off copying 1.0 settings; this run writes them that way

    def rss_mb():
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6

    world = fake_winrt.install()
    covers = []
    for seed in range(24):
        buf = io.BytesIO()
        aura_draw.sample_cover(640, seed=seed).convert("RGB").save(buf, "JPEG", quality=88)
        covers.append(buf.getvalue())
    s = world.add("Spotify.exe", "Song 0", "Artist", covers[0], dur=240)
    kind = {kind!r}
    if kind == "gif":
        folder = os.path.join({tmp!r}, "gifs")
        os.makedirs(folder)
        for i in range(5):
            make_gif(os.path.join(folder, f"g{{i}}.gif"), [20 + 10 * i] * 10, (360 + 40 * i, 220))
        q = QSettings("Aura", "Gif")
        q.setValue("folder", folder)
        q.setValue("speed", 2.0)
        q.sync()
    if kind == "clock":
        q = QSettings("Aura", "Clock")
        q.setValue("seconds", "true")
        q.sync()
    mod = drive.load({stem!r})
    if kind == "music":
        mod.asyncio = fake_winrt.fast_asyncio(40)
    samples = []

    def script(app, win):
        t0 = time.monotonic()
        n = [0]
        def churn():
            n[0] += 1
            if kind == "music":
                s.title, s.cover = f"Song {{n[0]}}", covers[n[0] % len(covers)]
                s.pos = (n[0] * 7) % 200
            elif kind == "clock":
                win.card.effects.clear()
                win.shine()
                win.twinkle()
            else:
                if n[0] % 12 == 0:
                    win.next_from_folder()
        def tick():
            if kind == "clock":
                win.tick()
        def sample():
            samples.append([round(time.monotonic() - t0, 2), round(rss_mb(), 2)])
            if time.monotonic() - t0 >= {seconds}:
                out = {{"samples": samples, "events": n[0]}}
                if kind == "gif":
                    out["gif_playing"] = bool(win.player.path)
                if kind == "clock":
                    out["seconds_on"] = win.card.seconds
                if kind == "music":
                    out["songs_seen"] = n[0]
                print(json.dumps(out))
                app.quit()
        for ms, fn in ((250 if kind != "clock" else 300, churn), (50, tick), (2000, sample)):
            t = QTimer(win, interval=ms)
            t.timeout.connect(fn)
            t.start()
        sample()

    drive.run(mod, script)
""")

KINDS = [("music", "aura_widget"), ("clock", "aura_clock"), ("gif", "aura_gif")]


def fit(samples):
    t = np.array([x[0] for x in samples if x[0] >= WARMUP])
    y = np.array([x[1] for x in samples if x[0] >= WARMUP])
    X = np.column_stack([np.ones_like(t), t / 3600])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    s2 = resid @ resid / (len(y) - 2)
    se = np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1])
    first, last = y[: max(3, len(y) // 10)], y[-max(3, len(y) // 10):]
    return {"slope_mb_per_hour": round(float(beta[1]), 2), "slope_se": round(float(se), 2),
            "rss_after_warmup_mb": round(float(np.median(first)), 1), "rss_at_end_mb": round(float(np.median(last)), 1),
            "n_samples": int(len(y))}


def main():
    out = {"machine": platform.platform(), "python": platform.python_version(), "minutes_each": MINUTES,
           "warmup_s": WARMUP, "note": "Linux, offscreen Qt, fake media session. The slope's standard error "
                                       "assumes independent samples, so treat it as rough.", "runs": {}}
    for kind, stem in KINDS:
        tmp = tempfile.mkdtemp(prefix="aura_soak_")
        env = dict(os.environ, APPDATA=tmp, XDG_CONFIG_HOME=tmp, TMPDIR=tmp, QT_QPA_PLATFORM="offscreen")
        code = CHILD.format(tests=os.path.join(ROOT, "tests"), root=ROOT, kind=kind, stem=stem, tmp=tmp,
                            seconds=int(MINUTES * 60))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                           timeout=MINUTES * 60 + 300)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-3000:])
        res = json.loads(r.stdout.strip().splitlines()[-1])
        if res.get("gif_playing") is False or res.get("seconds_on") is False:
            raise RuntimeError(f"{kind}: the run didn't get its settings")
        res["fit"] = fit(res["samples"])
        out["runs"][kind] = res
        print(kind, res["fit"], res.get("songs_seen", ""), flush=True)
    name = "soak.json" if MINUTES >= 5 else "soak_short.json"
    with open(os.path.join(ROOT, "results", name), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
