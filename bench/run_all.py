"""
Reruns everything that can run without Windows, in order, and rebuilds the files the README quotes.
About an hour on a slow machine, most of it the idle and soak runs.

    python bench/run_all.py            everything
    python bench/run_all.py --fast     just the tests, the docs and the quick measurements
"""
import os, sys, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FAST = "--fast" in sys.argv

STEPS = [
    ("tests", [sys.executable, "-m", "pytest", "-q", "tests"]),
    ("settings doc", [sys.executable, "docs/make_settings_doc.py"]),
    ("fullscreen check memory", [sys.executable, "bench/ctypes_leak.py"]),
    ("gif timing", [sys.executable, "bench/gif_timing.py"]),
    ("render cost", [sys.executable, "bench/render_bench.py"]),
]
if not FAST:
    STEPS += [
        ("idle cost", [sys.executable, "bench/idle.py"]),
        ("long run memory", [sys.executable, "bench/soak.py"]),
        ("cover pictures", [sys.executable, "bench/fetch_covers.py"]) if not os.path.exists(
            os.path.join(ROOT, "results", "covers_manifest.json")) else ("cover pictures (already there)", ["true"]),
        ("text contrast", [sys.executable, "bench/contrast.py"]),
        ("figures", [sys.executable, "bench/figures.py"]),
        ("readme pictures", [sys.executable, "bench/demo.py"]),
        ("gallery", [sys.executable, "bench/gallery.py"]),
    ]


def main():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    for name, cmd in STEPS:
        t0 = time.time()
        print(f"== {name}", flush=True)
        r = subprocess.run(cmd, cwd=ROOT, env=env)
        print(f"   {'ok' if r.returncode == 0 else 'FAILED'} in {time.time() - t0:.0f} s", flush=True)
        if r.returncode != 0:
            sys.exit(r.returncode)


if __name__ == "__main__":
    main()
