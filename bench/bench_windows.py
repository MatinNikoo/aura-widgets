"""
The benchmark to run on a real Windows PC. Close any Aura widgets first, then from the repo folder:

    py bench\\bench_windows.py                       about 12 minutes
    py bench\\bench_windows.py --game-minutes 10     then start a game when it says so
    py bench\\bench_windows.py --long-hours 8        leave it overnight for the memory trend
    py bench\\bench_windows.py --battery-minutes 20  on a laptop running on battery

What it does
  1. starts the music, clock and GIF widgets with paint timing on, and times how long each takes to show
  2. idle: samples CPU, private memory, handles and GDI/USER objects of each widget once a second
  3. fullscreen: opens a black fullscreen window on top, which should make every widget pause
  4. idle again, then optionally a real game, a long run, and a battery A/B
Everything goes into results/windows_<computer>_<date>.json, and a table to paste into the README is printed.
Play a song in Spotify while it runs, or the music card has nothing to draw.
"""
import os, sys, json, time, ctypes, argparse, platform, subprocess, tempfile, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import stats

WIDGETS = {"music": "aura_widget", "clock": "aura_clock", "gif": "aura_gif"}


def gui_objects(pid):
    """GDI and USER object counts, the usual place a Windows UI leak shows up."""
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None, None
    try:
        u = ctypes.windll.user32
        return u.GetGuiResources(h, 0), u.GetGuiResources(h, 1)
    finally:
        k.CloseHandle(h)


def already_running():
    import psutil
    for p in psutil.process_iter(["name", "cmdline"]):
        cmd = " ".join(p.info.get("cmdline") or [])
        if p.info.get("name") == "Aura.exe" or ("aura_" in cmd and "python" in (p.info.get("name") or "").lower()
                                                 and "bench" not in cmd):
            return True
    return False


def read_paints(path):
    rows = []
    try:
        with open(path) as f:
            for line in f:
                t, ms = line.strip().split(",")
                rows.append((float(t), float(ms)))
    except (OSError, ValueError):
        pass
    return rows


def cover_window(seconds):
    """A black fullscreen window, like a game, for the fullscreen phase."""
    from PyQt6.QtWidgets import QApplication, QWidget
    from PyQt6.QtCore import QTimer, Qt
    app = QApplication(sys.argv)
    w = QWidget()
    w.setStyleSheet("background: black;")
    w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    w.showFullScreen()
    w.raise_()
    w.activateWindow()
    QTimer.singleShot(int(seconds * 1000), app.quit)
    app.exec()


class Run:
    def __init__(self, args):
        import psutil
        self.psutil = psutil
        self.args = args
        self.tmp = tempfile.mkdtemp(prefix="aura_bench_")
        self.procs = {}
        self.samples = {k: [] for k in args.widgets}
        self.phases = []
        self.events = []
        self.fullscreen_seen = []

    def start(self, suffix=""):
        flags = 0x08000000 if sys.platform == "win32" else 0          # no console window
        self.startup = getattr(self, "startup", {}) if suffix else {}
        for name in self.args.widgets:
            csv = os.path.join(self.tmp, name + suffix + ".csv")
            t0 = time.time()
            p = subprocess.Popen([sys.executable, os.path.join(HERE, "profile_widget.py"), WIDGETS[name], "--out", csv],
                                 creationflags=flags)
            self.procs[name] = (p, self.psutil.Process(p.pid), csv, t0)
        if suffix:
            return
        deadline = time.time() + 60
        while time.time() < deadline and len(self.startup) < len(self.procs):
            for name, (p, _, csv, t0) in self.procs.items():
                if p.poll() is not None:
                    sys.exit(f"{name} closed right away. Is it already open? Close every Aura widget and try again.")
                rows = read_paints(csv)
                if rows and name not in self.startup:
                    self.startup[name] = (rows[0][0] - t0) * 1000
            time.sleep(0.05)
        print("startup ms:", {k: round(v) for k, v in self.startup.items()})

    def sample(self, seconds, label):
        from aura_common import fullscreen_app_open
        t_start = time.time()
        last_cpu = {k: v[1].cpu_times() for k, v in self.procs.items()}
        last_t = time.time()
        last_wall, last_mono = time.time(), time.monotonic()
        while time.time() - t_start < seconds:
            time.sleep(1)
            now = time.time()
            if (now - last_wall) - (time.monotonic() - last_mono) > 20:
                self.events.append({"t": now, "event": "the PC slept", "seconds": now - last_wall})
            last_wall, last_mono = now, time.monotonic()
            self.fullscreen_seen.append((now, label, fullscreen_app_open()))
            dt = now - last_t
            for name, (p, proc, _, _) in self.procs.items():
                try:
                    c = proc.cpu_times()
                    used = (c.user - last_cpu[name].user) + (c.system - last_cpu[name].system)
                    last_cpu[name] = c
                    mem = proc.memory_info()
                    row = {"t": now, "cpu": 100 * used / dt, "private_mb": getattr(mem, "private", mem.rss) / 1e6,
                           "rss_mb": mem.rss / 1e6, "threads": proc.num_threads()}
                    if sys.platform == "win32":
                        row["handles"] = proc.num_handles()
                        row["gdi"], row["user"] = gui_objects(proc.pid)
                    self.samples[name].append(row)
                except self.psutil.NoSuchProcess:
                    self.events.append({"t": now, "event": f"{name} stopped"})
            last_t = now
        self.phases.append({"phase": label, "t0": t_start, "t1": time.time()})
        print(f"{label}: done ({seconds:.0f} s)", flush=True)

    def phase_fullscreen(self, seconds):
        cover = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--cover-window", str(seconds + 6)])
        time.sleep(4)                                # give the widgets one 2 second check to notice
        self.sample(seconds, "fullscreen window")
        cover.wait()

    def phase_game(self, minutes):
        from aura_common import fullscreen_app_open
        print("Start your game now, fullscreen or borderless. Sampling starts once it covers the screen.")
        while not fullscreen_app_open():
            time.sleep(1)
        time.sleep(5)
        self.sample(minutes * 60, "real game")

    def battery(self, minutes):
        """Runs after stop(): battery drain with the widgets closed, then with them open.
        Battery percent is coarse and the rest of the PC matters a lot, so run it more than once."""
        b = self.psutil.sensors_battery()
        if b is None or b.power_plugged:
            print("battery test skipped, this needs a laptop running on battery")
            return None
        out = {}
        for label, run_widgets in (("widgets closed", False), ("widgets open", True)):
            if run_widgets:
                self.start("_battery")
            start = self.psutil.sensors_battery().percent
            time.sleep(minutes * 60)
            end = self.psutil.sensors_battery().percent
            out[label] = {"percent_used": start - end, "percent_per_hour": (start - end) * 60 / minutes}
            print(label, out[label])
        for p, *_ in self.procs.values():
            p.kill()
        return out

    def stop(self):
        for p, *_ in self.procs.values():
            p.kill()
        time.sleep(1)
        self.paints = {name: read_paints(csv) for name, (_, _, csv, _) in self.procs.items()}

    def summary(self):
        res = {}
        for name in self.args.widgets:
            res[name] = {"startup_ms": self.startup.get(name)}
            for ph in self.phases:
                s = stats.phase_summary(self.samples[name], ph["t0"], ph["t1"])
                s.update(stats.paint_summary(self.paints.get(name, []), ph["t0"], ph["t1"]))
                res[name][ph["phase"]] = s
        seen = [f for _, label, f in self.fullscreen_seen if label == "fullscreen window"]
        res["fullscreen_detected_share"] = sum(seen) / len(seen) if seen else None
        return res


def table(res, widgets):
    def f(v, d=1):
        return "n/a" if v is None or v != v else f"{v:.{d}f}"
    lines = ["| | " + " | ".join(widgets) + " |", "|---|" + "---|" * len(widgets)]
    rows = [("Startup to first frame (ms)", lambda r: f(r.get("startup_ms"), 0)),
            ("Idle CPU, mean % of one core", lambda r: f(r.get("idle", {}).get("cpu_pct_mean"), 2)),
            ("Idle CPU, 95th percentile %", lambda r: f(r.get("idle", {}).get("cpu_pct_p95"), 2)),
            ("Private memory at end of idle (MB)", lambda r: f(r.get("idle again", {}).get("private_mb_end"))),
            ("Paints per second, idle", lambda r: f(r.get("idle", {}).get("paints_per_s"), 2)),
            ("Paint time p50 / p99 (ms)", lambda r: f(r.get("idle", {}).get("paint_ms_p50"), 2) + " / "
             + f(r.get("idle", {}).get("paint_ms_p99"), 2)),
            ("Frame gap p50 / p95 (ms)", lambda r: f(r.get("idle", {}).get("gap_ms_p50"), 1) + " / "
             + f(r.get("idle", {}).get("gap_ms_p95"), 1)),
            ("CPU % with a fullscreen window", lambda r: f(r.get("fullscreen window", {}).get("cpu_pct_mean"), 2)),
            ("Paints per second, fullscreen", lambda r: f(r.get("fullscreen window", {}).get("paints_per_s"), 2)),
            ("CPU % during the game", lambda r: f(r.get("real game", {}).get("cpu_pct_mean"), 2)),
            ("Memory trend over the long run (MB/hour)",
             lambda r: f(r.get("long run", {}).get("private_mb_slope_per_hour"), 2)),
            ("GDI objects start to end", lambda r: f"{r.get('idle', {}).get('gdi_start', 'n/a')} to "
                                                   f"{r.get('long run', r.get('idle again', {})).get('gdi_end', 'n/a')}")]
    for label, fn in rows:
        lines.append(f"| {label} | " + " | ".join(fn(res[w]) for w in widgets) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--widgets", nargs="+", default=list(WIDGETS), choices=list(WIDGETS))
    ap.add_argument("--idle-minutes", type=float, default=5)
    ap.add_argument("--fullscreen-minutes", type=float, default=2)
    ap.add_argument("--game-minutes", type=float, default=0)
    ap.add_argument("--long-hours", type=float, default=0)
    ap.add_argument("--battery-minutes", type=float, default=0)
    ap.add_argument("--cover-window", type=float, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.cover_window:
        return cover_window(args.cover_window)
    if sys.platform != "win32":
        sys.exit("this one is for Windows; bench/idle.py and bench/soak.py run anywhere")
    if already_running():
        sys.exit("Close every Aura widget first (right click, Close widget), then run this again.")

    run = Run(args)
    run.start()
    time.sleep(20)                                   # let startup work settle
    run.sample(args.idle_minutes * 60, "idle")
    run.phase_fullscreen(args.fullscreen_minutes * 60)
    run.sample(60, "idle again")
    if args.game_minutes:
        run.phase_game(args.game_minutes)
    if args.long_hours:
        run.sample(args.long_hours * 3600, "long run")
    run.stop()
    battery = run.battery(args.battery_minutes) if args.battery_minutes else None

    res = run.summary()
    res["battery"] = battery
    info = {"computer": platform.node(), "windows": platform.platform(), "python": platform.python_version(),
            "cpu_count": os.cpu_count(), "date": datetime.datetime.now().isoformat(timespec="seconds")}
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        info["screens"] = [{"name": s.name(), "size": [s.geometry().width(), s.geometry().height()],
                            "scale": s.devicePixelRatio()} for s in app.screens()]
    except Exception:
        pass
    out = {"info": info, "summary": res, "phases": run.phases, "events": run.events, "samples": run.samples}
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    path = os.path.join(ROOT, "results", f"windows_{platform.node()}_{datetime.date.today()}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print("\nsaved", path, "\n")
    print(table(res, args.widgets))
    print("\nfullscreen window detected", f"{100 * (res['fullscreen_detected_share'] or 0):.0f}% of the time")
    print("\nThe widgets it started are closed now. Open yours again from the Start menu or the .pyw files.")


if __name__ == "__main__":
    main()
