"""
A stand in for the parts of the winrt package Aura uses, so the media code can run on Linux.
It only copies the shape of the real API (names, async calls, timedelta positions), and a
World object decides what is "playing". Used by the tests and by bench/soak.py.
"""
import sys, types, asyncio, datetime, enum


class Status(enum.IntEnum):
    CLOSED = 0
    OPENED = 1
    CHANGING = 2
    STOPPED = 3
    PLAYING = 4
    PAUSED = 5


async def _value(v, delay=0.0):
    if delay:
        await asyncio.sleep(delay)
    return v


class Stream:
    def __init__(self, data):
        self.data = data
        self.size = len(data)

    def read_async(self, buf, size, opts):
        return _value(bytes(self.data[:size]))


class Thumb:
    def __init__(self, data, fail=False):
        self.data, self.fail = data, fail

    async def _open(self):
        if self.fail:
            raise OSError("thumbnail stream broke")
        return Stream(self.data)

    def open_read_async(self):
        return self._open()


class Props:
    def __init__(self, title, artist, thumbnail):
        self.title, self.artist, self.thumbnail = title, artist, thumbnail


class Timeline:
    def __init__(self, pos_s, dur_s, updated):
        self.position = datetime.timedelta(seconds=pos_s)
        self.end_time = datetime.timedelta(seconds=dur_s)
        self.last_updated_time = updated


class Session:
    def __init__(self, world, app_id, title="", artist="", cover=None, dur=200, playing=True):
        self.world = world
        self.source_app_user_model_id = app_id
        self.title, self.artist, self.cover = title, artist, cover
        self.dur, self.pos, self.playing = dur, 0.0, playing
        self.seekable = True
        self.lag = 0.0                # how long the player keeps reporting the old position after a seek
        self.pending = None
        self.hang = False             # properties call never answers
        self.cover_fails = False
        self.commands = []

    async def _props(self):
        self.world.calls += 1
        if self.hang:
            await asyncio.sleep(3600)
        thumb = Thumb(self.cover, self.cover_fails) if self.cover is not None else None
        return Props(self.title, self.artist, thumb)

    def try_get_media_properties_async(self):
        return self._props()

    def get_timeline_properties(self):
        import time
        if self.pending and time.monotonic() >= self.pending[1]:
            self.pos, self.pending = self.pending[0], None
        return Timeline(self.pos, self.dur, datetime.datetime.now(datetime.timezone.utc))

    def get_playback_info(self):
        controls = types.SimpleNamespace(is_playback_position_enabled=self.seekable)
        return types.SimpleNamespace(playback_status=Status.PLAYING if self.playing else Status.PAUSED,
                                     controls=controls)

    def try_change_playback_position_async(self, ticks):
        import time
        self.commands.append(("seek", ticks))
        if self.seekable:
            self.pending = (ticks / 10_000_000, time.monotonic() + self.lag)
        return _value(self.seekable)

    def _cmd(self, name):
        self.commands.append(name)
        if name == "toggle":
            self.playing = not self.playing
        return _value(True)

    def try_toggle_play_pause_async(self):
        return self._cmd("toggle")

    def try_skip_next_async(self):
        return self._cmd("next")

    def try_skip_previous_async(self):
        return self._cmd("prev")


class World:
    """What the fake Windows thinks is playing."""

    def __init__(self):
        self.sessions = []
        self.current = None
        self.calls = 0
        self.request_failures = 0     # how many request_async calls fail before one works
        self.requests = 0
        self.broken = False           # every manager call raises, like a stale manager

    def add(self, *a, **k):
        s = Session(self, *a, **k)
        self.sessions.append(s)
        if self.current is None:
            self.current = s
        return s

    def remove(self, s):
        self.sessions.remove(s)
        if self.current is s:
            self.current = self.sessions[0] if self.sessions else None


class Manager:
    world = World()

    def __init__(self, world):
        self.w = world

    @classmethod
    async def _request(cls):
        w = cls.world
        w.requests += 1
        if w.request_failures > 0:
            w.request_failures -= 1
            raise OSError("media service not ready")
        return cls(w)

    @classmethod
    def request_async(cls):
        return cls._request()

    def get_sessions(self):
        if self.w.broken:
            raise OSError("manager went stale")
        return list(self.w.sessions)

    def get_current_session(self):
        if self.w.broken:
            raise OSError("manager went stale")
        return self.w.current


class Buffer:
    def __init__(self, size):
        self.length = size


class InputStreamOptions(enum.IntFlag):
    NONE = 0
    PARTIAL = 1
    READ_AHEAD = 2


class DataReader:
    @staticmethod
    def from_buffer(buf):
        raise NotImplementedError


def install(world=None):
    """Put fake winrt modules into sys.modules and return the World that drives them."""
    world = world or World()
    Manager.world = world
    control = types.ModuleType("winrt.windows.media.control")
    control.GlobalSystemMediaTransportControlsSessionManager = Manager
    control.GlobalSystemMediaTransportControlsSessionPlaybackStatus = Status
    streams = types.ModuleType("winrt.windows.storage.streams")
    streams.Buffer, streams.InputStreamOptions, streams.DataReader = Buffer, InputStreamOptions, DataReader
    names = ["winrt", "winrt.windows", "winrt.windows.media", "winrt.windows.storage"]
    for n in names:
        sys.modules[n] = types.ModuleType(n)
    sys.modules["winrt.windows.media.control"] = control
    sys.modules["winrt.windows.storage.streams"] = streams
    return world


def uninstall():
    for n in list(sys.modules):
        if n == "winrt" or n.startswith("winrt."):
            del sys.modules[n]


def fast_asyncio(factor):
    """An asyncio stand in whose sleep runs `factor` times faster, to squeeze hours into minutes."""
    shim = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith("__")})
    real = asyncio.sleep

    async def sleep(t, *a, **k):
        await real(t / factor, *a, **k)

    shim.sleep = sleep
    return shim
