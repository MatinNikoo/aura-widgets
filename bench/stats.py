"""Small summaries the Windows benchmark uses. Kept separate so they can be tested anywhere."""
import numpy as np


def pct(x, q):
    x = np.asarray(x, float)
    return float(np.percentile(x, q)) if len(x) else float("nan")


def slope_per_hour(t_s, y):
    """Least squares slope of y per hour, with its standard error. Samples close in time are
    correlated, so the error is a rough guide, not a real interval."""
    t = np.asarray(t_s, float) / 3600
    y = np.asarray(y, float)
    if len(t) < 3 or np.ptp(t) == 0:
        return float("nan"), float("nan")
    X = np.column_stack([np.ones_like(t), t])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    s2 = resid @ resid / (len(y) - 2)
    return float(beta[1]), float(np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1]))


def paint_summary(paints, t0, t1):
    """paints: list of (wall time, ms). Summary of the ones between t0 and t1."""
    p = [(t, ms) for t, ms in paints if t0 <= t < t1]
    if not p:
        return {"paints_per_s": 0.0}
    times = np.array([t for t, _ in p])
    ms = np.array([m for _, m in p])
    gaps = np.diff(times) * 1000
    out = {"paints_per_s": len(p) / max(1e-9, t1 - t0),
           "paint_ms_p50": pct(ms, 50), "paint_ms_p95": pct(ms, 95), "paint_ms_p99": pct(ms, 99),
           "paint_ms_max": float(ms.max())}
    if len(gaps) >= 10:
        out.update(gap_ms_p50=pct(gaps, 50), gap_ms_p95=pct(gaps, 95),
                   gap_jitter_ms=float(np.std(gaps)))
    return out


def phase_summary(samples, t0, t1):
    """samples: dicts with t, cpu (percent of one core), private_mb, handles, gdi, user."""
    s = [x for x in samples if t0 <= x["t"] < t1]
    if not s:
        return {}
    cpu = [x["cpu"] for x in s]
    mem = [x["private_mb"] for x in s]
    slope, se = slope_per_hour([x["t"] for x in s], mem)
    out = {"cpu_pct_mean": float(np.mean(cpu)), "cpu_pct_p95": pct(cpu, 95),
           "private_mb_start": mem[0], "private_mb_end": mem[-1],
           "private_mb_slope_per_hour": slope, "slope_se": se, "n": len(s)}
    for k in ("handles", "gdi", "user", "threads"):
        if k in s[0]:
            out[k + "_start"], out[k + "_end"] = s[0][k], s[-1][k]
    return out
