"""The optional extras added in 1.1 that sit around the cards: snapping, the hotkey, hiding every widget,
reset position, profiles, import and export, the first run note, and finding a GIF in a folder."""
import os, sys, json, subprocess, textwrap

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QWidget

from conftest import ROOT, env_for, make_gif, spin
import aura_common
import aura_hotkey
import aura_profiles
import aura_ui


# ---------------------------------------------------------------- snapping
AREA = [(0, 0, 1920, 1080)]


def test_snap_to_the_screen_edges_and_middle():
    assert aura_common.snap_offset((25, 600, 400, 130), AREA, []) == (-5, 0)          # 20 px from the left
    assert aura_common.snap_offset((1490, 940, 400, 130), AREA, []) == (10, -10)      # right and bottom edges
    assert aura_common.snap_offset((750, 470, 400, 130), AREA, []) == (10, 5)       # centered both ways


def test_nothing_close_means_no_snap():
    assert aura_common.snap_offset((300, 300, 400, 130), AREA, []) == (0, 0)


def test_snap_to_another_card():
    other = (500, 400, 400, 130)
    # just right of it, a little low: lines up the top and leaves the gap
    assert aura_common.snap_offset((920, 405, 400, 130), AREA, [other]) == (-8, -5)
    # just under it
    assert aura_common.snap_offset((505, 545, 400, 130), AREA, [other]) == (-5, -3)
    # level with it but far to the right, so it must not jump over to it
    assert aura_common.snap_offset((1300, 405, 400, 130), AREA, [other])[0] == 0


def test_snap_ignores_a_card_that_is_far_off_to_the_side():
    other = (500, 400, 400, 130)
    dx, dy = aura_common.snap_offset((920, 700, 400, 130), AREA, [other])
    assert (dx, dy) == (0, 0)           # beside it in x, but nowhere near level, so no side snap


def test_rects_are_read_back():
    assert aura_common.parse_rect("10,20,400,130") == (10, 20, 400, 130)
    assert aura_common.parse_rect("nope") is None
    assert aura_common.parse_rect("1,2,0,4") is None


# ---------------------------------------------------------------- hotkey
@pytest.mark.parametrize("text,want", [
    ("Ctrl+Alt+A", (0x3, ord("A"))), ("ctrl+shift+f9", (0x6, 0x78)), ("Win+Space", (0x8, 0x20)),
    ("Ctrl+Alt+7", (0x3, ord("7"))), ("Alt+Left", (0x1, 0x25)),
    ("A", None), ("Shift+A", None), ("", None), ("Ctrl+", None), ("Ctrl+Banana", None), ("Ctrl+F25", None),
    ("Hyper+A", None)])
def test_parse_hotkey(text, want):
    assert aura_hotkey.parse_hotkey(text) == want


@pytest.mark.skipif(sys.platform == "win32", reason="on Windows the hotkey is real, tests/windows_checks.py covers it")
def test_hotkey_does_nothing_off_windows(app):
    hk = aura_hotkey.Hotkey()
    hk.set("Ctrl+Alt+A")
    assert hk.thread is None and not hk.active
    hk.set("")
    hk.stop()


# ---------------------------------------------------------------- Extras around a plain window
@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(aura_common, "SETTINGS_DIR", str(tmp_path / "settings"))
    monkeypatch.setattr(aura_profiles, "PROFILES", str(tmp_path / "profiles"))
    return tmp_path


def make_extras(name="Music"):
    w = QWidget()
    w.resize(200, 100)
    paused = []
    ex = aura_ui.Extras(w, aura_common.settings(name), name, name, "aura_widget", "AuraWidget", __file__,
                        lambda g: QPoint(g.left() + 40, g.top() + 40), lambda: 10, refresh=lambda: paused.append(
                            ex.hidden_all))
    return w, ex, paused


def test_hide_all_and_show_all(app, isolated):
    w, ex, calls = make_extras()
    w.show()
    other_w, other, other_calls = make_extras("Clock")
    other_w.show()
    ex.toggle_all()
    assert not w.isVisible() and calls[-1] is True
    assert ex.hidden_all
    spin(app, 700)                                  # the other widget sees the shared file change
    assert other.hidden_all and not other_w.isVisible() and other_calls[-1] is True
    ex.toggle_all()
    spin(app, 700)
    assert w.isVisible() and other_w.isVisible() and other_calls[-1] is False


def test_hiding_does_not_come_back_from_a_flag_change(app, isolated):
    w, ex, _ = make_extras()
    w.show()
    ex.toggle_all()
    ex.reshow()                                     # what a widget does after changing its window flags
    assert not w.isVisible()


def test_stale_hidden_flag_does_not_trap_a_new_widget(app, isolated):
    aura_common.set_hidden(True)                    # left over from a session that ended hidden
    w, ex, _ = make_extras()
    w.show()
    assert w.isVisible()
    ex.toggle_all()                                 # the key still does something on the first press
    assert not w.isVisible()


def test_idle_hides_a_widget_until_it_has_something_to_show(app, isolated):
    w, ex, _ = make_extras()
    w.show()
    ex.set_idle(True)
    assert not w.isVisible()
    ex.set_idle(False)
    assert w.isVisible()


def test_tray_menu_hides_everything_and_resets_the_position(app, isolated):
    w, ex, _ = make_extras()
    w.show()
    ex.s.setValue("tray", "true")
    ex.update_tray()
    menu = ex.tray.contextMenu()
    actions = {a.text(): a for a in menu.actions()}
    assert {"Hide all widgets", "Settings", "Reset position", "Open log", "Close widget"} <= set(actions)
    actions["Hide all widgets"].trigger()
    assert not w.isVisible()
    menu.aboutToShow.emit()
    assert actions["Hide all widgets"].text() == "Show all widgets"
    actions["Hide all widgets"].trigger()
    assert w.isVisible()
    w.move(300, 300)
    ex.remember()
    actions["Reset position"].trigger()
    assert not aura_common.settings("Music").contains("pos")


def test_cli_hide_and_show(isolated):
    import aura
    assert aura.main(["hide"]) == 0
    assert aura_common.settings("General").value("hidden") == "true"
    assert aura.main(["show"]) == 0
    assert aura_common.settings("General").value("hidden") == "false"
    assert aura.main(["toggle"]) == 0
    assert aura_common.settings("General").value("hidden") == "true"


def test_reset_position_goes_back_to_the_default_spot(app, isolated):
    w, ex, _ = make_extras()
    ex.place()
    default = w.pos()
    w.move(default + QPoint(333, 111))
    ex.remember()
    assert aura_common.settings("Music").contains("pos")
    ex.reset_position()
    assert w.pos() == default
    assert not aura_common.settings("Music").contains("pos")
    assert not aura_common.settings("Music").contains("spots")


def test_another_window_can_ask_for_a_reset(app, isolated):
    w, ex, _ = make_extras()
    ex.place()
    default = w.pos()
    w.move(default + QPoint(200, 90))
    ex.remember()
    s = aura_common.settings("Music")           # what the settings window does
    s.remove("pos")
    s.remove("spots")
    s.setValue("move_token", "1")
    s.sync()
    spin(app, 700)
    assert w.pos() == default


def test_snapping_follows_the_setting_and_alt_skips_it(app, isolated, monkeypatch):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    w, ex, _ = make_extras()
    area = QGuiApplication.primaryScreen().availableGeometry()
    near = QPoint(area.left() + 12, area.top() + 400)         # card sits 12 px (minus the 10 px margin) from the left
    assert ex.snap(near) == near                              # off by default
    ex.s.setValue("snap", "true")
    snapped = ex.snap(near)
    assert snapped.x() + 10 == area.left() + aura_common.EDGE_GAP
    monkeypatch.setattr(QGuiApplication, "keyboardModifiers", staticmethod(lambda: Qt.KeyboardModifier.AltModifier))
    assert ex.snap(near) == near


def test_widgets_snap_to_each_other_through_their_files(app, isolated):
    a_w, a, _ = make_extras("Music")
    b_w, b, _ = make_extras("Clock")
    a_w.move(500, 400)
    a.remember()
    a.s.sync()
    b.s.setValue("snap", "true")
    b.cards = (0.0, [])
    left, top, w, h = a.card_rect()
    near = QPoint(left + w + 12 - 10 + 3, top - 10 + 4)       # a little off from sitting right beside it
    got = b.snap(near)
    assert got == QPoint(left + w + aura_common.WIDGET_GAP - 10, top - 10)


def test_a_closed_widget_stops_attracting_others(app, isolated):
    w, ex, _ = make_extras()
    ex.remember()
    assert aura_common.settings("Music").contains("rect")
    ex.goodbye()
    assert not aura_common.settings("Music").contains("rect")


# ---------------------------------------------------------------- profiles, export and import
def seed(isolated):
    m = aura_common.settings("Widget")
    m.setValue("shape", "circle")
    m.setValue("text_size", 115)
    m.setValue("pos", QPoint(40, 60))
    m.setValue("spots", json.dumps({"DP-1": [40, 60]}))
    m.sync()
    c = aura_common.settings("Clock")
    c.setValue("face", "analog")
    c.setValue("seconds", "true")
    c.sync()
    g = aura_common.settings("Gif_aura_gif_tall")
    g.setValue("mode", "fit")
    g.setValue("w", 300)
    g.sync()


def test_export_leaves_positions_out_and_import_restores_the_rest(isolated):
    seed(isolated)
    path = str(isolated / "mine.json")
    aura_profiles.export_file(path)
    data = json.load(open(path))
    assert data["format"] == "aura-settings"
    assert data["settings"]["Widget"] == {"shape": "circle", "text_size": "115"}
    assert data["settings"]["Gif_aura_gif_tall"] == {"mode": "fit", "w": "300"}
    for f in os.listdir(aura_common.SETTINGS_DIR):
        os.remove(os.path.join(aura_common.SETTINGS_DIR, f))
    done, skipped = aura_profiles.import_file(path)
    assert done == ["Clock", "Gif_aura_gif_tall", "Widget"] and skipped == []
    opts = aura_common.options(aura_common.settings("Widget"), "Widget")
    assert opts["shape"] == "circle" and opts["text_size"] == 115
    assert aura_common.options(aura_common.settings("Clock"), "Clock")["face"] == "analog"
    gif = aura_common.settings("Gif_aura_gif_tall")
    assert aura_common.options(gif, "Gif_aura_gif_tall")["mode"] == "fit" and gif.value("fit") == "true"
    assert not aura_common.settings("Widget").contains("pos")


def test_import_sets_everything_the_file_leaves_out_back_to_default(isolated):
    seed(isolated)
    path = str(isolated / "small.json")
    json.dump({"format": "aura-settings", "settings": {"Widget": {"shape": "pill"}}}, open(path, "w"))
    aura_profiles.import_file(path)
    opts = aura_common.options(aura_common.settings("Widget"), "Widget")
    assert opts["shape"] == "pill" and opts["text_size"] == 100


def test_import_rejects_what_it_does_not_understand(isolated):
    seed(isolated)
    for text in ("not json at all", "[1, 2]", json.dumps({"format": "other", "settings": {}})):
        path = isolated / "bad.json"
        path.write_text(text)
        with pytest.raises(ValueError):
            aura_profiles.import_file(str(path))
    with pytest.raises(ValueError):
        aura_profiles.import_file(str(isolated / "missing.json"))
    assert aura_common.options(aura_common.settings("Widget"), "Widget")["shape"] == "circle"     # untouched


def test_import_drops_unknown_names_keys_and_bad_values(isolated):
    path = str(isolated / "odd.json")
    json.dump({"format": "aura-settings", "settings": {
        "Widget": {"shape": "triangle", "opacity": "7", "nonsense": "1", "pos": "oops"},
        "../../evil": {"shape": "pill"}, "Clock": "nope", "General": {"hotkey": "Ctrl+Alt+K", "hotkey_on": "true"}}},
        open(path, "w"))
    done, skipped = aura_profiles.import_file(path)
    assert done == ["General", "Widget"]
    assert set(skipped) == {"Widget.nonsense", "Widget.pos", "../../evil", "Clock"}
    opts = aura_common.options(aura_common.settings("Widget"), "Widget")
    assert opts["shape"] == "rounded" and opts["opacity"] == 1.0          # bad values fall back and clamp
    assert not os.path.exists(os.path.join(str(isolated), "evil.ini"))
    assert aura_common.settings("General").value("hotkey") == "Ctrl+Alt+K"


def test_profiles_keep_positions_and_move_the_widgets(app, isolated):
    seed(isolated)
    w, ex, _ = make_extras("Widget")
    ex.place()
    assert w.pos() == QPoint(40, 60)
    assert aura_profiles.save_profile("Work: desk / 1") == "Work desk  1"
    assert aura_profiles.profile_names() == ["Work desk  1"]
    s = aura_common.settings("Widget")
    s.setValue("shape", "pill")
    s.setValue("pos", QPoint(500, 300))
    s.sync()
    aura_profiles.load_profile("Work desk  1")
    opts = aura_common.options(aura_common.settings("Widget"), "Widget")
    assert opts["shape"] == "circle"
    assert aura_common.settings("Widget").value("pos") == QPoint(40, 60)
    spin(app, 700)
    assert w.pos() == QPoint(40, 60)               # the running widget went there
    aura_profiles.delete_profile("Work desk  1")
    assert aura_profiles.profile_names() == []


@pytest.mark.parametrize("name", ["  ../ ", "***", ""])
def test_a_profile_needs_a_name(isolated, name):
    with pytest.raises(ValueError):
        aura_profiles.save_profile(name)


def test_reset_all_positions(app, isolated):
    seed(isolated)
    aura_profiles.reset_positions()
    s = aura_common.settings("Widget")
    assert not s.contains("pos") and not s.contains("spots") and s.contains("move_token")


# ---------------------------------------------------------------- first run note
def test_the_first_run_note_shows_once(app, isolated, monkeypatch):
    monkeypatch.delenv("AURA_NO_WELCOME")
    w, ex, _ = make_extras("Widget")
    w.show()
    assert ex.fresh
    ex.welcome()
    assert isinstance(ex.welcome_window, aura_ui.Welcome) and ex.welcome_window.isVisible()
    w2, ex2, _ = make_extras("Clock")
    w2.show()
    ex2.welcome()
    assert not hasattr(ex2, "welcome_window")       # one note is enough
    ex.welcome_window.close()


def test_no_first_run_note_for_someone_who_has_used_it(app, isolated, monkeypatch):
    monkeypatch.delenv("AURA_NO_WELCOME")
    s = aura_common.settings("Widget")
    s.setValue("pos", QPoint(10, 10))
    s.sync()
    w, ex, _ = make_extras("Widget")
    assert not ex.fresh


# ---------------------------------------------------------------- find a GIF in a folder
@pytest.fixture
def gifs(tmp_path):
    root = tmp_path / "library"
    (root / "memes" / "old").mkdir(parents=True)
    (root / ".hidden").mkdir()
    for path in ("cat dance.gif", "memes/cat nap.gif", "memes/old/dog run.webp", "memes/old/notes.txt",
                 "Catwalk.GIF", ".hidden/cat secret.gif"):
        full = root / path
        if path.endswith("txt"):
            full.write_text("x")
        else:
            make_gif(str(full), [40, 40], (60, 40))
    return str(root)


def test_find_gifs_by_name(gifs):
    import aura_library
    names = lambda text, deep=True: [os.path.basename(p) for p in aura_library.find_gifs(gifs, text, deep)]
    assert sorted(names("")) == ["Catwalk.GIF", "cat dance.gif", "cat nap.gif", "dog run.webp"]
    assert names("cat dance") == ["cat dance.gif"]
    assert names("NAP") == ["cat nap.gif"]
    assert names("cat", deep=False) == ["cat dance.gif", "Catwalk.GIF"]
    assert names("zzz") == []
    assert aura_library.find_gifs("", "") == [] and aura_library.find_gifs(gifs + "/nowhere", "") == []


def test_the_library_window_lists_filters_and_returns_a_choice(app, gifs, isolated):
    import aura_library
    dlg = aura_library.GifLibrary(None, gifs)
    assert dlg.list.count() == 4 and "4 found" in dlg.note.text()
    spin(app, 300)
    assert not dlg.list.item(0).icon().isNull()               # thumbnails arrive a few at a time
    got = []
    dlg.chosen.connect(got.append)
    dlg.search.setText("dog")
    spin(app, 500)
    assert dlg.list.count() == 1
    dlg.list.setCurrentRow(0)
    assert dlg.use_button.isEnabled()
    dlg.use_button.click()
    assert [os.path.basename(p) for p in got] == ["dog run.webp"]


# ---------------------------------------------------------------- a running GIF box takes a request from the settings window
CHOOSE = textwrap.dedent("""
    import sys, json, time
    sys.path.insert(0, {tests!r})
    import drive
    from PyQt6.QtCore import QTimer
    mod = drive.load("aura_gif")
    out = {{}}

    def script(app, win):
        import aura_common, aura_settings
        tab = aura_settings.Tab("Gif", "aura_gif")
        tab.choose_gif({gif!r})
        t0 = time.monotonic()

        def wait():
            if win.player.path or time.monotonic() - t0 > 15:
                out["path"] = bool(win.player.path)
                out["request_cleared"] = str(win.extras.s.value("choose", "")) == ""
                out["saved"] = str(win.extras.s.value("gif", ""))
                app.quit()
            else:
                QTimer.singleShot(100, wait)
        wait()

    drive.run(mod, script)
    print(json.dumps(out))
""")


def test_gif_box_loads_a_gif_picked_in_the_settings_window(tmp_path):
    gif = make_gif(str(tmp_path / "pick.gif"), [40] * 3)
    code = CHOOSE.format(tests=os.path.join(ROOT, "tests"), gif=gif)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env_for(tmp_path))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["path"] and out["request_cleared"] and out["saved"].endswith("current.gif")


# ---------------------------------------------------------------- a running music card hides when nothing plays
IDLE = textwrap.dedent("""
    import sys, json, time
    sys.path.insert(0, {tests!r})
    import fake_winrt, drive, aura_common
    from PyQt6.QtCore import QTimer
    from conftest import cover_bytes
    world = fake_winrt.install()
    song = world.add("Spotify.exe", "Song", "Artist", cover_bytes())
    s = aura_common.settings("Widget")
    s.setValue("hide_idle", "true")
    s.sync()
    mod = drive.load("aura_widget")
    mod.IDLE_AFTER_MS = 400
    out = {{}}

    def script(app, win):
        def until(cond, then, t0=None):
            t0 = t0 or time.monotonic()
            if cond() or time.monotonic() - t0 > 20:
                then()
            else:
                QTimer.singleShot(100, lambda: until(cond, then, t0))

        def stopped():
            out["visible_while_playing"] = win.isVisible()
            world.remove(song)
            until(lambda: not win.isVisible(), hidden)

        def hidden():
            out["hidden_when_idle"] = not win.isVisible()
            world.add("Spotify.exe", "Back", "Again", cover_bytes())
            until(win.isVisible, back)

        def back():
            out["back_when_playing"] = win.isVisible()
            app.quit()
        until(lambda: win.card.cur.title == "Song", stopped)

    drive.run(mod, script)
    print(json.dumps(out))
""")


def test_music_card_hides_while_nothing_plays(tmp_path):
    code = IDLE.format(tests=os.path.join(ROOT, "tests"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env_for(tmp_path))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out == {"visible_while_playing": True, "hidden_when_idle": True, "back_when_playing": True}


# ---------------------------------------------------------------- hiding pauses a running widget
HIDE = textwrap.dedent("""
    import sys, json, time
    sys.path.insert(0, {tests!r})
    import drive, aura_common
    from PyQt6.QtCore import QTimer
    from conftest import make_gif
    gif = make_gif({gif!r}, [40] * 4)
    s = aura_common.settings("Gif")
    s.setValue("gif", gif)
    s.sync()
    mod = drive.load("aura_gif")
    out = {{}}

    def script(app, win):
        def until(cond, then, t0=None):
            t0 = t0 or time.monotonic()
            if cond() or time.monotonic() - t0 > 15:
                then()
            else:
                QTimer.singleShot(100, lambda: until(cond, then, t0))

        def hid():
            out["hidden"] = not win.isVisible()
            out["paused_while_hidden"] = win.player.paused
            aura_common.set_hidden(False)
            until(win.isVisible, shown)

        def shown():
            out["shown"] = win.isVisible()
            out["playing_again"] = not win.player.paused
            app.quit()

        def go():
            aura_common.set_hidden(True)
            until(lambda: not win.isVisible(), hid)
        QTimer.singleShot(800, go)

    drive.run(mod, script)
    print(json.dumps(out))
""")


def test_hiding_from_another_process_pauses_and_returns_a_running_box(tmp_path):
    code = HIDE.format(tests=os.path.join(ROOT, "tests"), gif=str(tmp_path / "x.gif"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env_for(tmp_path))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {
        "hidden": True, "paused_while_hidden": True, "shown": True, "playing_again": True}


@pytest.mark.parametrize("bad", ["\\\\attacker\\share\\a.gif", "//attacker/share/a.gif", "\\\\?\\UNC\\attacker\\s\\a.gif",
                                 "file://attacker/share/a.gif", "https://example.com/a.gif"])
def test_import_leaves_out_network_and_link_paths(isolated, bad):
    path = str(isolated / "shared.json")
    json.dump({"format": "aura-settings", "settings": {"Clock": {"background": bad}, "Gif": {"folder": bad}}}, open(path, "w"))
    done, skipped = aura_profiles.import_file(path)
    assert "Clock.background" in skipped and "Gif.folder" in skipped
    assert aura_common.options(aura_common.settings("Clock"), "Clock")["background"] == ""


def test_import_keeps_a_normal_local_path(isolated):
    path = str(isolated / "mine.json")
    json.dump({"format": "aura-settings", "settings": {"Clock": {"background": "C:\\Users\\me\\Pictures\\a.gif"}}}, open(path, "w"))
    aura_profiles.import_file(path)
    assert aura_common.options(aura_common.settings("Clock"), "Clock")["background"] == "C:\\Users\\me\\Pictures\\a.gif"
