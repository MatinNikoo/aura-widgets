"""
Checks that only mean something on real Windows, run by CI on windows-latest.
    python tests/windows_checks.py
"""
import os, sys, asyncio, ctypes, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="aura_win_")

import aura_common
import drive

failed = []


def check(name, fn):
    try:
        fn()
        print(f"ok   {name}")
    except Exception as e:
        failed.append(name)
        print(f"FAIL {name}: {e!r}")


def fullscreen_no_leak():
    aura_common.fullscreen_app_open()
    cache = getattr(ctypes, "_pointer_type_cache", None)
    before = len(cache) if cache is not None else 0
    t0 = time.perf_counter()
    for _ in range(2000):
        assert aura_common.fullscreen_app_open() in (True, False)
    per_call = (time.perf_counter() - t0) / 2000 * 1e6
    after = len(cache) if cache is not None else 0
    assert after == before, f"pointer cache grew by {after - before}"
    print(f"     fullscreen check takes {per_call:.1f} us a call")


def music():
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    return drive.load("aura_widget")


def cover_through_real_stream():
    from winrt.windows.storage.streams import (InMemoryRandomAccessStream, DataWriter,
                                               RandomAccessStreamReference)
    mod = music()
    data = bytes(range(256)) * 40

    async def go():
        stream = InMemoryRandomAccessStream()
        w = DataWriter(stream)
        w.write_bytes(data)
        await mod.within(w.store_async())                 # wait_for around a real winrt operation
        await mod.within(w.flush_async())
        w.detach_stream()
        stream.seek(0)
        ref = RandomAccessStreamReference.create_from_stream(stream)
        worker = mod.MediaWorker(None)
        return await worker.read_cover(ref)

    got = asyncio.run(go())
    assert got == data, f"read {len(got or b'')} bytes, wanted {len(data)}"


def media_manager():
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    mod = music()

    async def go():
        mgr = await mod.within(Manager.request_async())
        s = mgr.get_current_session()
        if s is None:
            print("     no media session on this machine, that's expected on a CI runner")
            return
        info = s.get_playback_info()
        print("     can seek:", mod.can_seek(info))

    asyncio.run(go())


def run_key_round_trip():
    name = "AuraTestValue"
    aura_common.set_startup(name, True, os.path.join(os.path.dirname(HERE), "aura_clock.pyw"))
    assert aura_common.startup_enabled(name)
    aura_common.set_startup(name, False, "")
    assert not aura_common.startup_enabled(name)


def registry_settings_copied():
    from PyQt6.QtCore import QSettings, QPoint
    os.environ["AURA_OLD_ORG"] = "AuraTestCopy"                 # a throwaway key, not the real Aura one
    old = QSettings("AuraTestCopy", "TestCopy")
    old.setValue("pos", QPoint(120, 80))
    old.setValue("scale", 1.25)
    old.setValue("h24", "true")
    old.sync()
    try:
        s = aura_common.settings("TestCopy")
        assert s.value("pos") == QPoint(120, 80)
        assert aura_common.num(s, "scale", 1.0) == 1.25
        assert s.value("h24") == "true"
    finally:
        old.clear()
        old.sync()


def hotkey_registers_and_is_exclusive():
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
    import aura_hotkey
    global _app
    _app = QCoreApplication.instance() or QCoreApplication([])

    def spin(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    first, second = aura_hotkey.Hotkey(), aura_hotkey.Hotkey()
    first.set("Ctrl+Alt+Shift+F12")
    spin(300)
    assert first.active, "the first widget should get the key"
    second.set("Ctrl+Alt+Shift+F12")
    spin(300)
    assert not second.active, "the same key can't be registered twice"
    first.stop()
    second.try_again()
    spin(300)
    assert second.active, "the second one takes the key over once the first lets go"
    second.stop()


if __name__ == "__main__":
    if sys.platform != "win32":
        print("these checks only run on Windows")
        sys.exit(0)
    check("fullscreen check doesn't leak", fullscreen_no_leak)
    check("cover bytes through a real winrt stream", cover_through_real_stream)
    check("windows media manager answers", media_manager)
    check("open with windows on and off", run_key_round_trip)
    check("old registry settings copied to the ini", registry_settings_copied)
    check("hotkey registers and only one widget gets it", hotkey_registers_and_is_exclusive)
    sys.exit(1 if failed else 0)
