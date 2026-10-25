"""The math the Windows benchmark reports, checked on made up samples."""
import math, os, sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bench"))
import stats
import bench_windows


def test_slope_finds_a_leak():
    t = np.arange(0, 7200, 10.0)
    rng = np.random.default_rng(1)
    flat = 80 + rng.normal(0, 0.3, len(t))
    leaky = 80 + 5 * t / 3600 + rng.normal(0, 0.3, len(t))
    s0, se0 = stats.slope_per_hour(t, flat)
    s1, se1 = stats.slope_per_hour(t, leaky)
    assert abs(s0) < 3 * se0 + 0.05
    assert abs(s1 - 5) < 0.1
    assert math.isnan(stats.slope_per_hour([0, 1], [1, 2])[0])


def test_paint_summary():
    paints = [(100 + i * 0.04, 2.0 + (i % 10 == 0) * 8) for i in range(250)]       # 25 fps, every 10th slow
    s = stats.paint_summary(paints, 100, 110)
    assert abs(s["paints_per_s"] - 25) < 0.2
    assert abs(s["gap_ms_p50"] - 40) < 0.5
    assert s["paint_ms_p50"] == 2.0 and s["paint_ms_max"] == 10.0
    assert stats.paint_summary(paints, 0, 50) == {"paints_per_s": 0.0}


def test_phase_summary_and_table():
    samples = [{"t": i, "cpu": 0.5, "private_mb": 60 + i / 3600, "handles": 300, "gdi": 20, "user": 15, "threads": 9}
               for i in range(600)]
    s = stats.phase_summary(samples, 0, 600)
    assert s["cpu_pct_mean"] == 0.5 and abs(s["private_mb_slope_per_hour"] - 1) < 1e-6
    res = {w: {"startup_ms": 400, "idle": dict(s, paints_per_s=0.1), "idle again": s} for w in ("music", "clock")}
    t = bench_windows.table(res, ["music", "clock"])
    assert "| Startup to first frame (ms) | 400 | 400 |" in t
    assert "n/a" in t                                # no game phase was run
