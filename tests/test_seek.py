"""Seeking on the real music widget, with fake Windows media and synthetic mouse events."""
import os, sys, json, subprocess, textwrap

import pytest

from conftest import ROOT, env_for

SCRIPT = textwrap.dedent("""
    import sys, json, time
    sys.path.insert(0, {tests!r})
    import fake_winrt, drive
    from PyQt6.QtCore import QTimer, QPointF, QEvent, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication

    world = fake_winrt.install()
    s = world.add("Spotify.exe", "Song", "Artist", None, dur=200, playing=False)
    s.pos = 10.0
    s.seekable = {seekable}
    s.lag = 1.5                       # the player keeps saying 10 s for a while after the seek
    mod = drive.load("aura_widget")
    out = {{}}

    def mouse(win, kind, frac, buttons):
        card = win.card
        bar = card.bar_rect
        x = (bar.x() + bar.width() * frac + mod.M) * win.scale
        y = (bar.center().y() + mod.M) * win.scale
        btn = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
        ev = QMouseEvent(kind, QPointF(x, y), win.mapToGlobal(QPointF(x, y)), btn, buttons,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(win, ev)

    def script(app, win):
        def hover():
            win.repaint()
            out["can_seek"] = win.can_seek
            mouse(win, QEvent.Type.MouseMove, 0.5, Qt.MouseButton.NoButton)
            out["hover_preview"] = win.card.preview
        def press():
            mouse(win, QEvent.Type.MouseButtonPress, 0.2, Qt.MouseButton.LeftButton)
            out["seeking"] = win.seeking
            out["press_preview"] = win.card.preview
        def drag():
            mouse(win, QEvent.Type.MouseMove, 0.7, Qt.MouseButton.LeftButton)
            out["drag_preview"] = win.card.preview
        def release():
            mouse(win, QEvent.Type.MouseButtonRelease, 0.7, Qt.MouseButton.NoButton)
            out["pos_after_release"] = win.card.position() / 1000
        def check():
            out["pos_during_lag"] = win.card.position() / 1000      # Windows still reports 10 s here
            out["commands"] = [list(c) if isinstance(c, tuple) else c for c in s.commands]
        def done():
            out["pos_after_lag"] = win.card.position() / 1000
            app.quit()
        t0 = time.monotonic()
        def start():
            # wait for the first timeline from the (fake) player, however long a busy machine takes
            if win.card.dur_ms <= 0 and time.monotonic() - t0 < 20:
                QTimer.singleShot(100, start)
                return
            hover()
            QTimer.singleShot(200, press)
            QTimer.singleShot(400, drag)
            QTimer.singleShot(600, release)
            QTimer.singleShot(1600, check)
            QTimer.singleShot(3500, done)
        start()

    drive.run(mod, script)
    print(json.dumps(out))
""")


def run(tmp_path, seekable):
    env = env_for(tmp_path)
    code = SCRIPT.format(tests=os.path.join(ROOT, "tests"), seekable=seekable)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_drag_to_seek(tmp_path):
    out = run(tmp_path, True)
    assert out["can_seek"] and out["seeking"]
    assert abs(out["hover_preview"] - 0.5) < 0.02
    assert abs(out["press_preview"] - 0.2) < 0.02 and abs(out["drag_preview"] - 0.7) < 0.02
    seeks = [c for c in out["commands"] if isinstance(c, list) and c[0] == "seek"]
    assert len(seeks) == 1 and abs(seeks[0][1] / 1e7 - 140) < 3      # 70% of 200 s, in 100 ns ticks
    # the bar jumps to the new spot and doesn't get pulled back while Windows still says 10 s
    assert abs(out["pos_after_release"] - 140) < 3
    assert abs(out["pos_during_lag"] - 140) < 3
    assert abs(out["pos_after_lag"] - 140) < 3


def test_player_that_cannot_seek(tmp_path):
    out = run(tmp_path, False)
    assert not out["can_seek"] and not out["seeking"]
    assert out["hover_preview"] is None and out["press_preview"] is None
    assert not [c for c in out["commands"] if isinstance(c, list) and c[0] == "seek"]
    assert abs(out["pos_after_lag"] - 10) < 1                        # still where the player says
