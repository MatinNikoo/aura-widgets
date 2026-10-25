"""
Starts one Aura widget by name. The installed Aura.exe is this file, and it works from source too.

    python aura.py music        (or clock, gif, gif_tall)
    python aura.py settings     the settings window
    python aura.py hide         hide every running widget (show brings them back, toggle flips it)
    python aura.py --check      load every widget and draw each card once, then exit
    python aura.py --version
"""
import sys, os, runpy, tempfile

import aura_common

WIDGETS = {
    "music": "aura_widget", "clock": "aura_clock", "gif": "aura_gif", "gif_tall": "aura_gif_tall",
}

# the packaged app keeps the .pyw files next to its libraries, the source version keeps them next to this file
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def say(text):
    # the packaged app has no console, so there the report goes to %TEMP%\aura_check.txt
    if sys.stdout is not None:
        print(text, flush=True)
        return
    with open(os.path.join(tempfile.gettempdir(), "aura_check.txt"), "a", encoding="utf-8") as f:
        f.write(text + "\n")


def script_for(name):
    stem = WIDGETS.get(name, name)
    path = os.path.join(HERE, stem + ".pyw")
    return path if stem in WIDGETS.values() and os.path.exists(path) else None


def check():
    """Smoke test for CI and for a fresh install: every widget loads and every card draws."""
    from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QColor
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    ok = True
    for stem in WIDGETS.values():
        try:
            mod = runpy.run_path(os.path.join(HERE, stem + ".pyw"), run_name="aura_check")
            if stem == "aura_widget":
                card = mod["Card"]()
            elif stem == "aura_clock":
                card = mod["ClockCard"]()
            else:
                card = mod["GifCard"]()
            img = QImage(500, 200, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QColor(0, 0, 0, 0))
            p = QPainter(img)
            card.paint(p)
            p.end()
            say(f"ok   {stem}")
        except Exception as e:
            ok = False
            say(f"FAIL {stem}: {e!r}")
    if sys.platform == "win32":
        try:
            import winrt.windows.media.control, winrt.windows.storage.streams  # noqa: F401,F811
            say("ok   winrt")
        except Exception as e:
            ok = False
            say(f"FAIL winrt: {e!r}")
    del app
    return ok


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        say(__doc__.strip())
        return 0
    if argv[0] == "--version":
        say(aura_common.__version__)
        return 0
    if argv[0] == "--check":
        say(f"aura {aura_common.__version__}")
        return 0 if check() else 1
    if argv[0] in ("hide", "show", "toggle"):
        aura_common.set_hidden({"hide": True, "show": False, "toggle": None}[argv[0]])
        return 0
    if argv[0] == "settings":
        import aura_settings
        return aura_settings.main()
    path = script_for(argv[0])
    if path is None:
        say(f"no widget called {argv[0]!r}, pick one of: {', '.join(WIDGETS)}, settings, hide, show, toggle")
        return 2
    sys.argv = [path] + argv[1:]
    runpy.run_path(path, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
