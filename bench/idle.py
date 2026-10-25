"""
What each widget costs while it just sits there, 1.0 vs now: CPU time per minute and how many times a
second Qt wakes it up (timer events, a stand in for battery cost). Runs each real widget offscreen with
fake Windows media for a warmup and then a measured stretch. Writes results/idle.json.

    python bench/idle.py            about 12 minutes
    python bench/idle.py --quick    20 second stretches, for a smoke test
"""
import os, sys, json, subprocess, tempfile, textwrap, platform

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUICK = "--quick" in sys.argv
WARMUP, MEASURE = (5, 20) if QUICK else (15, 75)

CHILD = textwrap.dedent("""
    import os, sys, json, time, resource
    sys.path.insert(0, {tests!r})
    sys.path.insert(0, {root!r})
    import fake_winrt, drive
    from PyQt6.QtCore import QTimer, QObject, QEvent, QSettings
    from conftest import cover_bytes, make_gif
    os.environ.pop("AURA_OLD_ORG", None)    # conftest turns off copying 1.0 settings; this run writes them that way

    world = fake_winrt.install()
    s = world.add("Spotify.exe", "Song", "Artist", cover_bytes(), dur=600, playing={playing})
    if {gif!r}:
        QSettings("Aura", "Gif").setValue("gif", make_gif(os.path.join({tmp!r}, "a.gif"), [40] * 12, (480, 270)))
    for k, v in {extra!r}.items():
        QSettings("Aura", "Clock").setValue(k, v)     # written the 1.0 way, 1.1 copies it over
    mod = drive.load({stem!r}, {path!r})
    if hasattr(mod, "FONT_SPOTS"):
        mod.FONT_SPOTS = [os.path.join({root!r}, "Unbounded.ttf")]
    out = {{}}

    class Count(QObject):
        def __init__(self):
            super().__init__()
            self.timers = self.paints = 0
            self.on = False
        def eventFilter(self, obj, ev):
            if self.on:
                t = ev.type()
                if t == QEvent.Type.Timer:
                    self.timers += 1
                elif t == QEvent.Type.Paint and type(obj).__name__ == "Widget":
                    self.paints += 1
            return False

    def cpu():
        r = resource.getrusage(resource.RUSAGE_SELF)
        return r.ru_utime + r.ru_stime

    def script(app, win):
        c = Count()
        app.installEventFilter(c)
        def start():
            c.on = True
            out["t0"], out["c0"] = time.monotonic(), cpu()
            QTimer.singleShot({measure} * 1000, stop)
        def stop():
            dt = time.monotonic() - out["t0"]
            out["cpu_ms_per_min"] = (cpu() - out["c0"]) * 1000 / dt * 60
            out["timer_wakeups_per_s"] = c.timers / dt
            out["paints_per_s"] = c.paints / dt
            out["rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            app.quit()
        QTimer.singleShot({warmup} * 1000, start)

    drive.run(mod, script)
    print(json.dumps({{k: v for k, v in out.items() if k not in ("t0", "c0")}}))
""")

SCENARIOS = [
    ("music, song playing", "aura_widget", True, False, {}),
    ("music, song paused", "aura_widget", False, False, {}),
    ("clock", "aura_clock", False, False, {}),
    ("clock, sparkle off", "aura_clock", False, False, {"sparkle": "false"}),
    ("gif box, 40 ms frames", "aura_gif", False, True, {}),
]


def run(stem, path, playing, gif, extra):
    tmp = tempfile.mkdtemp(prefix="aura_idle_")
    env = dict(os.environ, APPDATA=tmp, XDG_CONFIG_HOME=tmp, TMPDIR=tmp, QT_QPA_PLATFORM="offscreen")
    code = CHILD.format(tests=os.path.join(ROOT, "tests"), root=ROOT, playing=playing, gif=gif, tmp=tmp, extra=extra,
                        stem=stem, path=path, warmup=WARMUP, measure=MEASURE)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                       timeout=WARMUP + MEASURE + 120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def main():
    rows = []
    for label, stem, playing, gif, extra in SCENARIOS:
        for version, path in (("1.0", os.path.join(ROOT, "tests", "original", stem + "_v1.py")),
                              ("1.1", os.path.join(ROOT, stem + ".pyw"))):
            res = run(stem if version == "1.1" else stem + "_v1", path, playing, gif, extra)
            # a run that didn't get its settings would quietly measure the wrong thing
            if gif and res["paints_per_s"] < 5:
                raise RuntimeError(f"{label} {version}: the GIF never played")
            if extra.get("sparkle") == "false" and res["paints_per_s"] > 1:
                raise RuntimeError(f"{label} {version}: sparkle was still on")
            res.update(scenario=label, version=version)
            rows.append(res)
            print(res, flush=True)
    out = {"machine": platform.platform(), "python": platform.python_version(), "warmup_s": WARMUP,
           "measured_s": MEASURE, "note": "Linux, offscreen Qt, fake media session. Shared 2 core machine.",
           "rows": rows}
    name = "idle_quick.json" if QUICK else "idle.json"
    with open(os.path.join(ROOT, "results", name), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
