import os, sys, ctypes, logging, subprocess, textwrap

import pytest

import aura_common as ac
from conftest import ROOT


def test_covers_monitor():
    mon = (0, 0, 1920, 1080)
    assert ac.covers_monitor((0, 0, 1920, 1080), mon)
    assert ac.covers_monitor((-8, -8, 1928, 1088), mon)        # borderless games often overhang a bit
    assert not ac.covers_monitor((0, 0, 1920, 1040), mon)      # maximized, taskbar still showing
    assert not ac.covers_monitor((1920, 0, 3840, 1080), mon)   # fullscreen on the other monitor


def test_visible_on_screens():
    screens = [(0, 0, 1920, 1080), (1920, 0, 2560, 1440)]
    assert ac.visible((100, 100, 400, 132), screens)
    assert ac.visible((3000, 500, 400, 132), screens)          # on the second monitor
    assert not ac.visible((5000, 500, 400, 132), screens)      # that monitor is gone
    assert not ac.visible((1900, -120, 400, 132), screens)     # only a sliver above the top edge
    assert ac.visible((1880, 900, 400, 132), screens)          # straddles two monitors


class FakeSettings:
    def __init__(self, d):
        self.d = d

    def value(self, k, default=None):
        return self.d.get(k, default)


def test_num_falls_back_on_bad_values():
    s = FakeSettings({"scale": "1.25", "w": "abc", "h": None})
    assert ac.num(s, "scale", 1.0) == 1.25
    assert ac.num(s, "w", 440, int) == 440
    assert ac.num(s, "h", 160, int) == 160
    assert ac.num(s, "missing", 0.5) == 0.5


def test_startup_command_source_and_frozen(monkeypatch):
    cmd = ac.startup_command(os.path.join(ROOT, "aura_clock.pyw"))
    assert cmd.endswith('aura_clock.pyw"') and cmd.startswith('"')
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Users\me\AppData\Local\Programs\Aura\Aura.exe")
    # the old code pointed the Run key at the .pyw inside the exe's temp folder, which is gone after a reboot
    assert ac.startup_command("/somewhere/_internal/aura_clock.pyw") == \
        r'"C:\Users\me\AppData\Local\Programs\Aura\Aura.exe" aura_clock'


def test_logging_rotates_and_catches_crashes(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "LOG_DIR", str(tmp_path))
    old_hook = sys.excepthook
    try:
        h = ac.setup_logging("t")
        assert h.maxBytes == 1_000_000 and h.backupCount == 3
        try:
            raise ValueError("boom")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        h.flush()
        text = (tmp_path / "t.log").read_text()
        assert "uncaught error" in text and "ValueError: boom" in text
    finally:
        sys.excepthook = old_hook
        logging.getLogger().handlers[:] = []


SLOT_CRASH = textwrap.dedent("""
    import os, sys
    sys.path.insert(0, {root!r})
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["APPDATA"] = {appdata!r}
    from PyQt6.QtCore import QCoreApplication, QTimer
    import aura_common
    if {hook}:
        aura_common.setup_logging("crash")
    app = QCoreApplication([])
    QTimer.singleShot(10, lambda: 1 / 0)
    QTimer.singleShot(200, lambda: (print("still alive"), app.quit()))
    app.exec()
""")


@pytest.mark.parametrize("hook", [False, True])
def test_error_in_a_qt_slot(tmp_path, hook):
    """Without a hook PyQt6 aborts the whole widget on any error in a slot, and pythonw shows nothing."""
    code = SLOT_CRASH.format(root=ROOT, appdata=str(tmp_path), hook=hook)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    if hook:
        assert r.returncode == 0 and "still alive" in r.stdout
        log = (tmp_path / "Aura" / "logs" / "crash.log").read_text()
        assert "ZeroDivisionError" in log
    else:
        assert r.returncode != 0 and "still alive" not in r.stdout


# ---------------------------------------------------------------- fullscreen check, with a fake user32
class FakeFn:
    def __init__(self, f):
        self.f = f

    def __call__(self, *a):
        return self.f(*a)


def fake_user32(win_rect, cls_name="UnityWndClass", mon=(0, 0, 1920, 1080)):
    def get_rect(hwnd, ref):
        r = ref._obj
        r.left, r.top, r.right, r.bottom = win_rect
        return 1

    def get_class(hwnd, buf, n):
        buf.value = cls_name
        return len(cls_name)

    def get_mon_info(hmon, ref):
        m = ref._obj.rcMonitor
        m.left, m.top, m.right, m.bottom = mon
        return 1

    u = type("U", (), {})()
    u.GetForegroundWindow = FakeFn(lambda: 1234)
    u.GetClassNameW = FakeFn(get_class)
    u.GetWindowRect = FakeFn(get_rect)
    u.MonitorFromWindow = FakeFn(lambda h, f: 1)
    u.GetMonitorInfoW = FakeFn(get_mon_info)
    return u


@pytest.fixture
def fake_windows(monkeypatch):
    def use(**k):
        monkeypatch.setattr(ac, "_win32", None)
        monkeypatch.setattr(ctypes, "windll", type("W", (), {"user32": fake_user32(**k)})(), raising=False)
        monkeypatch.setattr(ac.sys, "platform", "win32")
    return use


def test_fullscreen_detection(fake_windows):
    fake_windows(win_rect=(0, 0, 1920, 1080))
    assert ac.fullscreen_app_open()
    fake_windows(win_rect=(0, 0, 1920, 1040))
    assert not ac.fullscreen_app_open()
    fake_windows(win_rect=(0, 0, 1920, 1080), cls_name="WorkerW")     # the desktop itself
    assert not ac.fullscreen_app_open()


def test_fullscreen_check_does_not_leak(fake_windows):
    """The old check built a ctypes struct class every 2 seconds and ctypes cached a pointer type for each one."""
    fake_windows(win_rect=(0, 0, 1920, 1080))
    ac.fullscreen_app_open()
    cache = getattr(ctypes, "_pointer_type_cache", None)
    if cache is None:
        pytest.skip("this python has no global pointer cache")
    before = len(cache)
    for _ in range(500):
        ac.fullscreen_app_open()
    assert len(cache) == before


# ---------------------------------------------------------------- settings file and window placement
def test_settings_copied_from_registry_once(app, tmp_path, monkeypatch):
    from PyQt6.QtCore import QSettings, QPoint
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "native"))
    monkeypatch.setattr(ac, "SETTINGS_DIR", str(tmp_path / "ini"))
    monkeypatch.setenv("AURA_OLD_ORG", "AuraTestCopy")         # on Windows this is a throwaway registry key
    old = QSettings("AuraTestCopy", "Clock")
    old.setValue("h24", "true")
    old.setValue("scale", 1.25)
    old.setValue("pos", QPoint(300, 40))
    old.sync()

    s = ac.settings("Clock")
    assert s.value("h24") == "true"
    assert ac.num(s, "scale", 1.0) == 1.25
    assert s.value("pos") == QPoint(300, 40)
    assert (tmp_path / "ini" / "Clock.ini").exists()

    # later changes go to the ini and the registry copy doesn't overwrite them
    s.setValue("h24", "false")
    s.sync()
    assert ac.settings("Clock").value("h24") == "false"
    old.clear()
    old.sync()


def test_place_falls_back_when_monitor_is_gone(app):
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import QPoint
    w = QWidget()
    w.setFixedSize(452, 184)
    ac.place(w, QPoint(100, 100), QPoint(20, 300), 26)
    assert w.pos() == QPoint(100, 100)
    ac.place(w, QPoint(9000, 100), QPoint(20, 300), 26)      # was on a monitor that's unplugged now
    assert w.pos() == QPoint(20, 300)
    ac.place(w, None, QPoint(30, 30), 26)
    assert w.pos() == QPoint(30, 30)


def test_detail_only_rises_when_needed():
    assert ac.detail_for([1.0]) == 2                 # 1.0 always drew at 2x
    assert ac.detail_for([1.5], 1.25) == 2           # 150% screen, Large size, still under 2
    assert ac.detail_for([2.0], 1.0) == 2
    assert ac.detail_for([2.0], 1.25) == 3           # 200% screen and Large size
    assert ac.detail_for([1.0, 2.5]) == 3            # any screen it might move to counts
    assert ac.detail_for([4.0], 1.6) == 4            # capped
    assert ac.detail_for([]) == 2


def test_problem_report(tmp_path, monkeypatch):
    import zipfile
    logs, sets = tmp_path / "logs", tmp_path / "settings"
    logs.mkdir()
    sets.mkdir()
    (logs / "aura_clock.log").write_text("2026 ERROR something\n")
    (sets / "Clock.ini").write_text("[General]\nh24=true\n")
    monkeypatch.setattr(ac, "LOG_DIR", str(logs))
    monkeypatch.setattr(ac, "SETTINGS_DIR", str(sets))
    path = ac.problem_report(str(tmp_path / "out"), ["screen X 1920x1080 scale 1.5"])
    with zipfile.ZipFile(path) as z:
        assert sorted(z.namelist()) == ["logs/aura_clock.log", "settings/Clock.ini", "system.txt"]
        info = z.read("system.txt").decode()
        assert info.startswith("aura " + ac.__version__) and "scale 1.5" in info
