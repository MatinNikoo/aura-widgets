"""The settings window writes the settings file, and a running widget picks the change up live."""
import os, sys, json, subprocess, textwrap

import pytest

from conftest import ROOT, env_for

SCRIPT = textwrap.dedent("""
    import sys, json, time
    sys.path.insert(0, {tests!r})
    import fake_winrt, drive
    from PyQt6.QtCore import QTimer
    fake_winrt.install().add("Spotify.exe", "Song", "Artist", None)
    mod = drive.load("aura_widget")
    out = {{}}

    def script(app, win):
        import aura_settings, aura_common
        w = aura_settings.open_window("Widget")
        tab = w.tabs.currentWidget()
        out["tab"] = w.tabs.tabText(w.tabs.currentIndex())
        out["radius_enabled_before"] = tab.editors["radius"][1].isEnabled()
        shape = tab.editors["shape"][1]
        shape.setCurrentIndex(shape.findData("circle"))
        tab.editors["text_size"][1].setValue(115)
        tab.editors["show_artist"][1].setChecked(False)
        out["radius_enabled_after"] = tab.editors["radius"][1].isEnabled()
        out["ini"] = {{k: str(tab.s.value(k)) for k in ("shape", "text_size", "show_artist")}}

        def wait(cond, then, t0=None):
            t0 = t0 or time.monotonic()
            if cond() or time.monotonic() - t0 > 15:
                then()
            else:
                QTimer.singleShot(100, lambda: wait(cond, then, t0))

        def check():
            out["preview"] = tab.preview.img is not None      # drawn on the next turn of the event loop
            out["live_shape"] = win.card.look.shape
            out["live_artist"] = win.card.look.artist
            out["window_size"] = [win.width(), win.height()]
            tab.reset()
            wait(lambda: win.card.look.shape == "rounded", after_reset)

        def after_reset():
            out["after_reset"] = win.card.look.shape
            out["after_reset_size"] = [win.width(), win.height()]
            out["defaults"] = aura_common.options(tab.s, "Widget")["shape"]
            app.quit()
        wait(lambda: win.card.look.shape == "circle", check)

    drive.run(mod, script)
    print(json.dumps(out))
""")


def test_settings_window_changes_a_running_widget(tmp_path):
    env = env_for(tmp_path)
    code = SCRIPT.format(tests=os.path.join(ROOT, "tests"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["tab"] == "Music" and out["preview"]
    assert out["radius_enabled_before"] and not out["radius_enabled_after"]
    assert out["ini"] == {"shape": "circle", "text_size": "115", "show_artist": "false"}
    assert out["live_shape"] == "circle" and out["live_artist"] is False
    assert out["window_size"] == [252, 252]               # 200 px circle plus the shadow room
    assert out["after_reset"] == "rounded" and out["after_reset_size"] == [452, 184]
    assert out["defaults"] == "rounded"


CLOSE = textwrap.dedent("""
    import sys, json
    sys.path.insert(0, {tests!r})
    import fake_winrt, drive
    from PyQt6.QtCore import QTimer
    fake_winrt.install().add("Spotify.exe", "Song", "Artist", None)
    mod = drive.load({stem!r})
    alive = {{"v": False}}

    def script(app, win):
        import aura_settings
        w = aura_settings.open_window()
        QTimer.singleShot(1000, w.close)
        QTimer.singleShot(3000, lambda: (alive.update(v=True), app.quit()))

    drive.run(mod, script)
    print(json.dumps(alive))
""")


@pytest.mark.parametrize("stem", ["aura_widget", "aura_clock", "aura_gif"])
def test_closing_settings_leaves_the_widget_running(tmp_path, stem):
    """Closing the settings window used to quit the music widget along with it."""
    env = env_for(tmp_path)
    code = CLOSE.format(tests=os.path.join(ROOT, "tests"), stem=stem)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1])["v"]


def test_a_widget_only_watches_its_own_file(app, tmp_path):
    """Another widget saving its settings must not make this one reapply everything."""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QWidget
    import aura_ui

    def norm(paths):
        # Qt hands paths back with forward slashes, Windows paths from pathlib use backslashes
        return [os.path.normcase(os.path.normpath(p)) for p in paths]

    own = tmp_path / "Music.ini"
    s = QSettings(str(own), QSettings.Format.IniFormat)
    w = QWidget()
    ex = aura_ui.Extras(w, s, "Music", "Music", "aura_widget", "AuraWidget", __file__, (0, 0), 0)
    folder = norm([str(tmp_path)])[0]
    assert folder in norm(ex.watcher.directories())     # no file yet, so the folder is watched
    s.setValue("opacity", 0.9)
    s.sync()
    ex.watch()
    assert norm([str(own)])[0] in norm(ex.watcher.files())
    assert ex.watcher.directories() == []                # the file exists, so only the file is watched
    ex.watcher.removePaths(ex.watcher.files())
    own.unlink()
    ex.watch()
    assert folder in norm(ex.watcher.directories())     # the file went away, so it watches for it to return


# ---------------------------------------------------------------- the General tab and the new rows
@pytest.fixture
def window(app, tmp_path, monkeypatch):
    import aura_common, aura_profiles, aura_settings
    monkeypatch.setattr(aura_common, "SETTINGS_DIR", str(tmp_path / "settings"))
    monkeypatch.setattr(aura_profiles, "PROFILES", str(tmp_path / "profiles"))
    w = aura_settings.SettingsWindow()
    w.general_tab.said = []
    monkeypatch.setattr(aura_settings.GeneralTab, "say", lambda self, text: self.said.append(text))
    yield w
    w.close()


def test_every_widget_has_a_tab_and_general_comes_last(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["Music", "Clock", "GIF", "General"]
    window.select("General")
    assert window.tabs.currentWidget() is window.general_tab


def test_hotkey_row_follows_its_switch_and_saves_what_you_press(window):
    from PyQt6.QtGui import QKeySequence
    tab = window.general_tab
    edit = tab.editors["hotkey"][1]
    assert not edit.isEnabled()
    tab.editors["hotkey_on"][1].setChecked(True)
    assert edit.isEnabled()
    edit.setKeySequence(QKeySequence("Ctrl+Shift+F9"))
    edit.editingFinished.emit()
    assert str(tab.s.value("hotkey")) == "Ctrl+Shift+F9" and str(tab.s.value("hotkey_on")) == "true"


def test_analog_face_greys_out_what_only_the_digital_face_uses(window):
    tab = window.tabs.widget(1)
    assert tab.editors["h24"][1].isEnabled() and tab.editors["style"][1].isEnabled()
    face = tab.editors["face"][1]
    face.setCurrentIndex(face.findData("analog"))
    assert not tab.editors["h24"][1].isEnabled() and not tab.editors["style"][1].isEnabled()
    assert tab.editors["seconds"][1].isEnabled()                  # the second hand


def test_reset_position_button_asks_the_widget_to_move(window):
    tab = window.tabs.widget(0)
    tab.s.setValue("pos", "x")
    tab.reset_position()
    assert not tab.s.contains("pos") and tab.s.contains("move_token")


def test_profiles_from_the_window(window):
    tab = window.general_tab
    music = window.tabs.widget(0)
    shape = music.editors["shape"][1]
    shape.setCurrentIndex(shape.findData("pill"))
    tab.save_profile_as("Streaming")
    assert tab.profiles.currentText() == "Streaming"
    shape.setCurrentIndex(shape.findData("circle"))
    tab.switch_profile_to("Streaming")
    assert shape.currentData() == "pill"                          # the tab shows what the profile put back
    assert tab.said == []
    tab.switch_profile_to("Nope")
    assert tab.said and "profile" in tab.said[0]


def test_import_and_export_from_the_window(window, tmp_path):
    import aura_profiles
    tab = window.general_tab
    music = window.tabs.widget(0)
    music.editors["text_size"][1].setValue(120)
    path = str(tmp_path / "out.json")
    aura_profiles.export_file(path)
    music.editors["text_size"][1].setValue(90)
    assert tab.import_from(path)[0] == ["Widget"]
    assert music.editors["text_size"][1].value() == 120
    (tmp_path / "junk.json").write_text("{}")
    assert tab.import_from(str(tmp_path / "junk.json")) is None and tab.said


def test_gif_tab_asks_the_box_to_load_a_gif(window):
    gif = window.gif_tab
    gif.choose_gif("/some/where.gif")
    assert str(gif.s.value("choose")) == "/some/where.gif"
