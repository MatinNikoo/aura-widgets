"""Each widget's real main() runs for a few seconds, with default and with heavy non-default settings,
and must not log a single error."""
import os, sys, json, subprocess, textwrap

import pytest

from conftest import ROOT, make_gif, env_for

SCRIPT = textwrap.dedent("""
    import sys, json, time
    sys.path.insert(0, {tests!r})
    import fake_winrt, drive, aura_common
    from PyQt6.QtCore import QTimer
    from conftest import cover_bytes
    fake_winrt.install().add("Spotify.exe", "Song", "Artist", cover_bytes())
    settings = json.loads({settings!r})
    if settings:
        s = aura_common.settings({key!r})
        for k, v in settings.items():
            s.setValue(k, v)
        s.sync()
    mod = drive.load({stem!r})
    out = {{}}

    def script(app, win):
        def done():
            out["size"] = [win.width(), win.height()]
            win.grab()                                   # paints once more through the real paintEvent
            app.quit()
        QTimer.singleShot(3000, done)

    drive.run(mod, script)
    print(json.dumps(out))
""")

HEAVY = {"shape": "circle", "opacity": 0.5, "tray": "true", "click_through": "true", "locked": "true",
         "border": "bold", "shadow": "false", "on_top": "true"}

CASES = [
    ("aura_widget", "Widget", {}, [452, 184]),
    ("aura_widget", "Widget", dict(HEAVY, text_size=130, colors="neutral", show_times="false"), [252, 252]),
    ("aura_widget", "Widget", {"shape": "pill", "scale": 1.5, "show_artist": "false"}, [678, 276]),
    ("aura_clock", "Clock", {}, [452, 184]),
    ("aura_clock", "Clock", dict(HEAVY, locale="fa_IR", seconds="true", style="flat", time_size=120,
                                 background="GIF"), [252, 252]),
    ("aura_clock", "Clock", {"shape": "squircle", "font": "DejaVu Serif", "date": "full", "locale": "ja_JP"},
     [452, 184]),
    ("aura_widget", "Widget", {"backdrop": "blur", "hide_idle": "true", "snap": "true"}, [452, 184]),
    ("aura_clock", "Clock", {"face": "analog", "seconds": "true", "shape": "pill", "snap": "true"}, [452, 184]),
    ("aura_clock", "Clock", {"face": "analog", "shape": "circle", "date": "full", "locale": "fa_IR"}, [252, 252]),
    ("aura_gif", "Gif", {}, [492, 212]),
    ("aura_gif", "Gif", dict(HEAVY, folder="FOLDER", every=1, shuffle="true", mode="stretch", speed=2.0),
     [212, 212]),
    ("aura_gif_tall", "Gif_aura_gif_tall", {"shape": "squircle", "mode": "fit"}, [322, 392]),
]


@pytest.mark.parametrize("stem,key,settings,size", CASES)
def test_widget_runs(tmp_path, stem, key, settings, size):
    folder = tmp_path / "gifs"
    folder.mkdir()
    for i in range(3):
        make_gif(str(folder / f"g{i}.gif"), [40] * 4)
    settings = {k: (str(folder) if v == "FOLDER" else str(folder / "g0.gif") if v == "GIF" else v)
                for k, v in settings.items()}
    env = env_for(tmp_path)
    code = SCRIPT.format(tests=os.path.join(ROOT, "tests"), settings=json.dumps(settings), key=key, stem=stem)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["size"] == size
    logs = tmp_path / "Aura" / "logs" / f"{stem}.log"
    text = logs.read_text() if logs.exists() else ""
    assert "ERROR" not in text and "CRITICAL" not in text, text
