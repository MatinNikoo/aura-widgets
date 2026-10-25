"""
One global hotkey that shows or hides every widget. Windows only, through RegisterHotKey on a small
thread with its own message loop. Nothing is hooked into other programs and no keystrokes are read.

Every widget process tries to register the same key. Windows lets only one succeed, and the others
try again every few seconds, so the key keeps working as long as any widget is open.
"""
import sys, threading, logging

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

MODS = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8, "meta": 0x8, "super": 0x8}
NAMED = {"space": 0x20, "tab": 0x09, "return": 0x0D, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B,
         "backspace": 0x08, "del": 0x2E, "delete": 0x2E, "ins": 0x2D, "insert": 0x2D, "home": 0x24,
         "end": 0x23, "pgup": 0x21, "pageup": 0x21, "pgdown": 0x22, "pagedown": 0x22, "left": 0x25,
         "up": 0x26, "right": 0x27, "down": 0x28}
WM_HOTKEY, WM_APP, WM_QUIT = 0x0312, 0x8000, 0x0012
MOD_NOREPEAT = 0x4000


def parse_hotkey(text):
    """"Ctrl+Alt+A" -> (modifier flags, virtual key code), or None when it isn't a usable shortcut.
    A shortcut needs at least one of Ctrl, Alt, Win so it can't swallow normal typing."""
    parts = [p.strip().lower() for p in str(text or "").split("+") if p.strip()]
    if len(parts) < 2:
        return None
    mods, key = 0, parts[-1]
    for m in parts[:-1]:
        if m not in MODS:
            return None
        mods |= MODS[m]
    if not mods & (0x1 | 0x2 | 0x8):
        return None
    if len(key) == 1 and key.isalnum() and key.isascii():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    elif key in NAMED:
        vk = NAMED[key]
    else:
        return None
    return mods, vk


class Hotkey(QObject):
    pressed = pyqtSignal()
    _registered = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spec = None
        self.active = False            # true while this process owns the key
        self.thread = None
        self.thread_id = 0
        self.retry = QTimer(self, interval=15_000)
        self.retry.timeout.connect(self.try_again)
        self._registered.connect(self._set_active)

    @property
    def supported(self):
        return sys.platform == "win32"

    def set(self, text):
        """Use this shortcut, or none when text is empty or can't be parsed."""
        spec = parse_hotkey(text) if text else None
        if spec == self.spec and (self.thread is not None or spec is None):
            return
        self.stop()
        self.spec = spec
        if spec and self.supported:
            self.start()

    def _set_active(self, ok):
        self.active = ok
        if ok:
            self.retry.stop()
        elif self.spec:
            self.retry.start()

    def start(self):
        ready = threading.Event()
        self.thread = threading.Thread(target=self._loop, args=(self.spec, ready), name="aura-hotkey", daemon=True)
        self.thread.start()
        ready.wait(2)

    def stop(self):
        self.retry.stop()
        if self.thread is not None and self.thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
            self.thread.join(1)
        self.thread, self.thread_id, self.active, self.spec = None, 0, False, None

    def try_again(self):
        if self.thread_id and not self.active:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_APP, 0, 0)

    def _loop(self, spec, ready):
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                                   wintypes.UINT]
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        msg = wintypes.MSG()
        u.PeekMessageW(ctypes.byref(msg), None, 0x400, 0x400, 0)       # makes this thread's message queue exist
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        ready.set()
        mods, vk = spec
        have = False

        def register():
            nonlocal have
            have = bool(u.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))
            if not have:
                logging.info("hotkey is taken, probably by another Aura widget, trying again later")
            self._registered.emit(have)

        register()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.pressed.emit()
            elif msg.message == WM_APP and not have:
                register()
        if have:
            u.UnregisterHotKey(None, 1)
