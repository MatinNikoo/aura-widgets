"""
Memory kept by the fullscreen check, 1.0 vs now. Runs the real 1.0 function (tests/original) and the new
one against a fake user32, so it works on Linux. The leak is in ctypes itself, not in Windows, so the
per call number carries over. Writes results/ctypes_leak.json.

    python bench/ctypes_leak.py
"""
import os, sys, json, ctypes, gc, platform, tracemalloc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import drive
from test_common import fake_user32
import aura_common

CALLS = 20_000
CALLS_PER_DAY = 24 * 3600 / 2          # the widgets check every 2 seconds


def measure(fn):
    for _ in range(200):
        fn()
    gc.collect()
    cache = getattr(ctypes, "_pointer_type_cache", {})
    n0 = len(cache)
    tracemalloc.start()
    snap = tracemalloc.take_snapshot()
    for _ in range(CALLS):
        assert fn() is True
    gc.collect()
    grown = sum(s.size_diff for s in tracemalloc.take_snapshot().compare_to(snap, "filename"))
    tracemalloc.stop()
    return {"bytes_per_call": grown / CALLS, "pointer_types_cached": len(cache) - n0,
            "mb_per_day_per_widget": grown / CALLS * CALLS_PER_DAY / 1e6}


def main():
    old = drive.load("aura_widget_v1", os.path.join(ROOT, "tests", "original", "aura_widget_v1.py"))
    ctypes.windll = type("W", (), {"user32": fake_user32(win_rect=(0, 0, 1920, 1080))})()
    real_platform = sys.platform
    sys.platform = "win32"           # only the check itself looks at this, after everything is imported
    try:
        out = {"python": platform.python_version(), "calls": CALLS,
               "v1_0": measure(old.fullscreen_app_open),
               "v1_1": measure(aura_common.fullscreen_app_open)}
    finally:
        sys.platform = real_platform
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "ctypes_leak.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
