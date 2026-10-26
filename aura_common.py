"""
Bits every Aura widget shares: the log file, the fullscreen check, opening with Windows,
reading settings safely and putting the window back where it was.
"""
import sys, os, math, logging, logging.handlers, tempfile, threading

__version__ = "1.1.0"

APP_DIR = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "Aura")
LOG_DIR = os.path.join(APP_DIR, "logs")
SETTINGS_DIR = os.path.join(APP_DIR, "settings")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# ---------------------------------------------------------------- log file
def setup_logging(name):
    """Log to %APPDATA%\\Aura\\logs\\<name>.log, capped at about 4 MB, and log crashes instead of dying silently."""
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(os.path.join(LOG_DIR, name + ".log"),
                                                   maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)

    # pythonw has no console, so without this an error in a Qt slot just kills the widget with no trace
    def log_uncaught(kind, value, tb):
        if issubclass(kind, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(kind, value, tb)
            return
        logging.critical("uncaught error", exc_info=(kind, value, tb))

    sys.excepthook = log_uncaught
    threading.excepthook = lambda a: logging.critical(
        "uncaught error in thread %s", a.thread.name if a.thread else "?",
        exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return handler


# ---------------------------------------------------------------- settings
def settings(name):
    """Each widget keeps its settings in %APPDATA%\\Aura\\settings\\<name>.ini (see docs/settings.md).
    Older versions kept them in the registry, so those get copied over the first time."""
    from PyQt6.QtCore import QSettings
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    path = os.path.join(SETTINGS_DIR, name + ".ini")
    fresh = not os.path.exists(path)
    s = QSettings(path, QSettings.Format.IniFormat)
    if fresh:
        # AURA_OLD_ORG only exists so tests never read or touch the real registry settings
        old = QSettings(os.environ.get("AURA_OLD_ORG", "Aura"), name)
        for k in old.allKeys():
            s.setValue(k, old.value(k))
        s.sync()
        if old.allKeys():
            logging.info("copied %d old settings from the registry into %s", len(old.allKeys()), path)
    return s


def set_hidden(hidden=None):
    """Hide or show every widget by writing the shared General file, which they all watch. With no
    argument it flips what the file says. Returns the new state."""
    import time
    g = settings("General")
    if hidden is None:
        hidden = str(g.value("hidden", "false")).lower() != "true"
    g.setValue("hidden", "true" if hidden else "false")
    g.setValue("hidden_at", time.time())              # changes every time, so every widget notices
    g.sync()
    return hidden


def num(settings, key, default, cast=float):
    """Read a number from QSettings, falling back to the default if it's missing or broken."""
    try:
        return cast(settings.value(key, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- pause while a game is fullscreen
DESKTOP_CLASSES = ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")


def covers_monitor(win, mon):
    """win and mon are (left, top, right, bottom). True when the window covers the whole monitor."""
    return win[0] <= mon[0] and win[1] <= mon[1] and win[2] >= mon[2] and win[3] >= mon[3]


_win32 = None


def win32():
    """user32 with its argument types set, built once. Building the MONITORINFO struct inside the
    2 second check made ctypes cache a new pointer type on every call, which never got freed."""
    global _win32
    if _win32 is None:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        u = ctypes.windll.user32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.MonitorFromWindow.restype = wintypes.HANDLE
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        _win32 = (ctypes, wintypes, u, MONITORINFO)
    return _win32


def fullscreen_app_open():
    """True when the app in front covers the whole monitor (a game, a fullscreen video)."""
    if sys.platform != "win32":
        return False
    try:
        ctypes, wintypes, u, MONITORINFO = win32()
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return False
        name = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, name, 64)
        if name.value in DESKTOP_CLASSES:
            return False          # that's the desktop or taskbar, not an app
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return covers_monitor((r.left, r.top, r.right, r.bottom), (m.left, m.top, m.right, m.bottom))
    except Exception:
        return False


# ---------------------------------------------------------------- open with Windows
def startup_command(script):
    if getattr(sys, "frozen", False):
        # the installed app runs every widget through Aura.exe, picked by name
        return f'"{sys.executable}" {os.path.splitext(os.path.basename(script))[0]}'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else exe}" "{os.path.abspath(script)}"'


def run_key(write=False):
    import winreg
    if write:
        # a brand new Windows account may not have the Run key yet, so create it when turning startup on
        return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_ALL_ACCESS)
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)


def startup_enabled(name):
    try:
        import winreg
        with run_key() as k:
            winreg.QueryValueEx(k, name)
        return True
    except Exception:
        return False


def set_startup(name, on, script):
    import winreg
    with run_key(True) as k:
        if on:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, startup_command(script))
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------- window position
def visible(rect, screens, need=60):
    """True when at least a need x need piece of rect (x, y, w, h) sits on one screen,
    so there's enough of the card left to grab and drag."""
    x, y, w, h = rect
    for sx, sy, sw, sh in screens:
        ow = min(x + w, sx + sw) - max(x, sx)
        oh = min(y + h, sy + sh) - max(y, sy)
        if ow >= min(need, w) and oh >= min(need, h):
            return True
    return False


def place(widget, saved, default, margin):
    """Move to the saved spot, unless that spot is on a monitor that isn't plugged in right now.
    Then use the default spot, and jump back if that monitor shows up while nobody has moved the widget."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QGuiApplication

    def fits(p):
        screens = [s.geometry().getRect() for s in QGuiApplication.screens()]
        return visible((p.x() + margin, p.y() + margin, widget.width() - 2 * margin,
                        widget.height() - 2 * margin), screens)

    if not isinstance(saved, QPoint):
        widget.move(default)
        return
    if fits(saved):
        widget.move(saved)
        return
    logging.info("saved position %s is off every screen, using the default", saved)
    widget.move(default)

    def screen_added(*_):
        if widget.pos() == default and fits(saved):
            widget.move(saved)

    QGuiApplication.instance().screenAdded.connect(screen_added)


# ---------------------------------------------------------------- sharpness on high DPI screens
def detail_for(ratios, scale=1.0):
    """Pixels per point for cached images: 2 like 1.0, more only when a screen times the widget size needs it."""
    need = max(ratios or [1.0]) * scale
    return max(2, min(4, math.ceil(need - 0.01)))


# ---------------------------------------------------------------- positions per monitor
def pick_spot(saved, pinned, spots, screens, defaults, size, margin):
    """Where the widget should go, and why.
    saved     last (x, y) the user dragged it to, or None
    pinned    name of the monitor it's pinned to in settings, or ""
    spots     {monitor name: (dx, dy)} last spot on each monitor, relative to that monitor's corner
    screens   [(name, (x, y, w, h))] with the primary monitor first
    defaults  the default (x, y) on each of those monitors"""
    w, h = size
    rects = [g for _, g in screens]
    names = [n for n, _ in screens]

    def ok(p):
        return visible((p[0] + margin, p[1] + margin, w - 2 * margin, h - 2 * margin), rects)

    def remembered(i):
        name, g = screens[i]
        if name in spots:
            p = (g[0] + spots[name][0], g[1] + spots[name][1])
            if ok(p):
                return p
        return None

    if pinned and pinned in names:
        i = names.index(pinned)
        return remembered(i) or defaults[i], "pinned"
    if saved is not None and ok(saved):
        return saved, "saved"
    for i in range(len(screens)):
        p = remembered(i)
        if p:
            return p, "remembered"
    return defaults[0], "default"


def screen_at(point, screens):
    """Name of the monitor a point is on, or None."""
    x, y = point
    for name, (sx, sy, sw, sh) in screens:
        if sx <= x < sx + sw and sy <= y < sy + sh:
            return name
    return None


# ---------------------------------------------------------------- snapping
SNAP_DIST, EDGE_GAP, WIDGET_GAP = 14, 20, 12


def snap_offset(rect, areas, others, dist=SNAP_DIST, edge_gap=EDGE_GAP, gap=WIDGET_GAP):
    """How far to nudge a card (x, y, w, h) so it lines up with something close by.
    areas   usable rectangles of the monitors, the card snaps to the one it's mostly on
    others  cards of the other widgets
    It snaps to edge_gap from a screen edge, to the middle of the screen, to another card's edges and
    to gap away from the side of a card it's beside. Each direction snaps on its own."""
    x, y, w, h = rect
    cx, cy = x + w / 2, y + h / 2
    area = next((a for a in areas if a[0] <= cx < a[0] + a[2] and a[1] <= cy < a[1] + a[3]), None)
    xs, ys = [], []
    if area:
        ax, ay, aw, ah = area
        xs += [ax + edge_gap - x, ax + aw - edge_gap - w - x, ax + (aw - w) / 2 - x]
        ys += [ay + edge_gap - y, ay + ah - edge_gap - h - y, ay + (ah - h) / 2 - y]
    for ox, oy, ow, oh in others:
        xs += [ox - x, ox + ow - (x + w)]
        ys += [oy - y, oy + oh - (y + h)]
        if min(y + h, oy + oh) - max(y, oy) > -dist:         # level with each other, so it can sit beside it
            xs += [ox + ow + gap - x, ox - gap - w - x]
        if min(x + w, ox + ow) - max(x, ox) > -dist:         # above or below it
            ys += [oy + oh + gap - y, oy - gap - h - y]

    def best(options):
        near = [d for d in options if abs(d) <= dist]
        return min(near, key=abs) if near else 0

    return round(best(xs)), round(best(ys))


def parse_rect(text):
    """"x,y,w,h" -> a tuple of ints, or None."""
    try:
        r = tuple(int(float(v)) for v in str(text).split(","))
        return r if len(r) == 4 and r[2] > 0 and r[3] > 0 else None
    except ValueError:
        return None


def other_cards(own):
    """The last known card rectangles of the other widgets, read from their settings files."""
    from PyQt6.QtCore import QSettings
    out = []
    try:
        names = os.listdir(SETTINGS_DIR)
    except OSError:
        return out
    for n in names:
        if n.endswith(".ini") and n[:-4] not in (own, "General"):
            r = parse_rect(QSettings(os.path.join(SETTINGS_DIR, n), QSettings.Format.IniFormat).value("rect", ""))
            if r:
                out.append(r)
    return out


# ---------------------------------------------------------------- GIF folder
GIF_TYPES = (".gif", ".webp")


def gifs_in(folder):
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names if n.lower().endswith(GIF_TYPES)]


def next_gif(files, current, shuffle=False, rng=None):
    """The next GIF to show from a folder. Shuffle never picks the same one twice in a row."""
    if not files:
        return None
    if shuffle:
        import random
        rng = rng or random
        choices = [f for f in files if f != current] or files
        return rng.choice(choices)
    if current in files:
        return files[(files.index(current) + 1) % len(files)]
    return files[0]


# ---------------------------------------------------------------- every setting, in one place
# (key, kind, default, label, extra). The defaults are what version 1.0 did, so nothing changes until
# you change something. The settings window and docs/settings.md are both built from this list.
SHAPES = [("rounded", "Rounded"), ("square", "Square"), ("squircle", "Squircle"), ("pill", "Pill"),
          ("circle", "Circle")]
BORDERS = [("thin", "Thin"), ("none", "None"), ("bold", "Bold")]
SPEEDS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
LOCALES = [("", "English (like before)"), ("en_US", "English (US)"), ("en_GB", "English (UK)"),
           ("fa_IR", "Persian"), ("ar_SA", "Arabic"), ("he_IL", "Hebrew"), ("zh_CN", "Chinese"),
           ("ja_JP", "Japanese"), ("ko_KR", "Korean"), ("es_ES", "Spanish"), ("fr_FR", "French"),
           ("de_DE", "German"), ("it_IT", "Italian"), ("pt_BR", "Portuguese"), ("ru_RU", "Russian"),
           ("tr_TR", "Turkish"), ("hi_IN", "Hindi"), ("sv_SE", "Swedish")]
DATE_FORMATS = [("weekday", "monday, march 9"), ("full", "monday, march 9, 2026"), ("short", "mar 9"),
                ("numeric", "9/3/2026"), ("iso", "2026-03-09"), ("none", "No date")]


def look(radius=26, scale=True):
    rows = [("shape", "choice", "rounded", "Shape", SHAPES),
            ("radius", "int", radius, "Corner radius", (0, 60))]
    if scale:
        rows.append(("scale", "float", 1.0, "Size", (0.6, 1.6)))
    rows += [("opacity", "float", 1.0, "Opacity", (0.2, 1.0)),
             ("shadow", "bool", True, "Shadow", None),
             ("border", "choice", "thin", "Border", BORDERS)]
    return rows


BEHAVIOR = [("on_top", "bool", False, "Keep on top of windows", None),
            ("locked", "bool", False, "Lock position", None),
            ("click_through", "bool", False, "Click through (get back to it from the tray icon)", None),
            ("tray", "bool", False, "Tray icon", None),
            ("snap", "bool", False, "Snap to screen edges and other widgets (hold Alt to skip)", None),
            ("monitor", "monitor", "", "Monitor", None)]

SCHEMA = {
    "Widget": [
        ("Look", look() + [
            ("colors", "choice", "cover", "Colors", [("cover", "From the album cover"), ("neutral", "Plain dark")]),
            ("backdrop", "choice", "tint", "Background", [("tint", "Tinted card"), ("blur", "Blurred cover")]),
            ("high_contrast", "bool", False, "High contrast text (4.5:1 on every cover)", None),
            ("text_size", "int", 100, "Text size", (80, 130))]),
        ("Shows", [
            ("show_artist", "bool", True, "Artist", None),
            ("show_bar", "bool", True, "Progress bar", None),
            ("show_times", "bool", True, "Times", None),
            ("show_controls", "bool", True, "Controls on hover", None),
            ("hide_idle", "bool", False, "Hide the card while nothing is playing", None)]),
        ("Behavior", [("seek", "bool", True, "Click or drag the progress bar to seek", None)] + BEHAVIOR),
    ],
    "Clock": [
        ("Look", look() + [
            ("face", "choice", "digital", "Face", [("digital", "Digital"), ("analog", "Analog")]),
            ("style", "choice", "chrome", "Text style", [("chrome", "Liquid chrome"), ("flat", "Flat")]),
            ("font", "font", "", "Font", None),
            ("time_size", "int", 100, "Time size", (80, 120)),
            ("sparkle", "bool", True, "Sparkle animation", None),
            ("background", "file", "", "Background GIF or image", None),
            ("background_dim", "int", 45, "Darken background", (0, 90))]),
        ("Time and date", [
            ("h24", "bool", False, "24 hour time", None),
            ("seconds", "bool", False, "Show seconds", None),
            ("date", "choice", "weekday", "Date", DATE_FORMATS),
            ("locale", "choice", "", "Language", LOCALES),
            ("lowercase", "bool", True, "Lowercase date", None)]),
        ("Behavior", list(BEHAVIOR)),
    ],
    "General": [
        ("Shortcut", [
            ("hotkey_on", "bool", False, "Show or hide every widget with a shortcut", None),
            ("hotkey", "hotkey", "Ctrl+Alt+A", "Shortcut", None)]),
    ],
    "Gif": [
        ("Look", look(scale=False) + [
            ("mode", "choice", "fill", "Fit", [("fill", "Fill and crop"), ("fit", "Show whole GIF"),
                                               ("stretch", "Stretch")])]),
        ("Playback", [
            ("speed", "choice", 1.0, "Speed", [(v, f"{v:g}x") for v in SPEEDS]),
            ("paused", "bool", False, "Paused", None),
            ("folder", "folder", "", "Play every GIF in a folder", None),
            ("every", "choice", 10, "Switch GIF", [(m, f"Every {m} min") for m in (1, 5, 10, 30, 60)]),
            ("shuffle", "bool", False, "Shuffle", None)]),
        ("Behavior", list(BEHAVIOR)),
    ],
}


def schema(name):
    """The schema for a settings file name. GIF copies (Gif_<name>) share the Gif one."""
    return SCHEMA["Gif" if name.startswith("Gif") else name]


def fields(name):
    return [f for _, rows in schema(name) for f in rows]


def coerce(kind, value, default, extra):
    try:
        if kind == "bool":
            return value if isinstance(value, bool) else str(value).lower() == "true"
        if kind == "int":
            v = int(float(value))
            return max(extra[0], min(extra[1], v)) if extra else v
        if kind == "float":
            v = float(value)
            return max(extra[0], min(extra[1], v)) if extra else v
        if kind == "choice":
            for v, _ in extra:
                if str(v) == str(value):
                    return v
            return default
        return "" if value is None else str(value)
    except (TypeError, ValueError):
        return default


def options(settings, name):
    """Every setting for a widget, typed and range checked, with defaults filled in."""
    out = {}
    for key, kind, default, _, extra in fields(name):
        out[key] = coerce(kind, settings.value(key, default), default, extra)
    if name.startswith("Gif") and settings.value("mode") is None:
        out["mode"] = "fit" if str(settings.value("fit", "false")) == "true" else "fill"   # 1.0 only had fit
    return out


def store(value):
    return ("true" if value else "false") if isinstance(value, bool) else value


def reset(settings, name):
    """Back to defaults. Position, size and the chosen GIF stay."""
    for key, *_ in fields(name):
        settings.remove(key)
    if name.startswith("Gif"):
        settings.remove("fit")
    settings.sync()


# ---------------------------------------------------------------- problem report
def problem_report(dest_dir, extra=None):
    """Zips the logs, the settings files and some basic system info into dest_dir and returns the path.
    It only makes a file. Nothing is sent anywhere, you decide if and where to share it."""
    import zipfile, platform, datetime
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"aura-report-{datetime.datetime.now():%Y%m%d-%H%M%S}.zip")
    info = [f"aura {__version__}", f"python {platform.python_version()}", f"system {platform.platform()}",
            f"frozen {getattr(sys, 'frozen', False)}"]
    try:
        from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        info.append(f"qt {QT_VERSION_STR}, pyqt {PYQT_VERSION_STR}")
    except Exception:
        pass
    info += list(extra or [])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("system.txt", "\n".join(info) + "\n")
        for folder, arc in ((LOG_DIR, "logs"), (SETTINGS_DIR, "settings")):
            if os.path.isdir(folder):
                for name in sorted(os.listdir(folder)):
                    full = os.path.join(folder, name)
                    if os.path.isfile(full):
                        z.write(full, f"{arc}/{name}")
    return path
