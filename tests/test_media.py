"""The media worker against a fake Windows media session, with its sleeps sped up 50x."""
import asyncio, datetime

import pytest

import fake_winrt
from conftest import cover_bytes


class Recorder:
    def __init__(self):
        self.tracks, self.timelines, self.errors = [], [], []
        self.track = type("S", (), {"emit": lambda _, v: self.tracks.append(v)})()
        self.timeline = type("S", (), {"emit": lambda _, v: self.timelines.append(v)})()
        self.error = type("S", (), {"emit": lambda _, v: self.errors.append(v)})()


@pytest.fixture
def world(music, monkeypatch):
    w = fake_winrt.install()
    monkeypatch.setattr(music, "asyncio", fake_winrt.fast_asyncio(50))
    monkeypatch.setattr(music, "TIMEOUT", 0.3)
    yield w
    fake_winrt.uninstall()


def run_for(worker, seconds, during=None):
    async def go():
        task = asyncio.ensure_future(worker.main())
        if during:
            await during()
        await asyncio.sleep(seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            raise
    asyncio.run(go())


def titles(rec):
    return [t[0] if t else None for t in rec.tracks]


def test_reads_track_and_cover(music, world):
    world.add("Spotify.exe", "Kiss of Life", "Sade", cover_bytes())
    rec = Recorder()
    run_for(music.MediaWorker(rec), 0.3)
    assert titles(rec)[-1] == "Kiss of Life"
    assert rec.tracks[-1][2][:2] == b"\xff\xd8"           # the jpeg bytes came through
    assert titles(rec).count("Kiss of Life") == 1          # not re-sent every poll
    pos, dur, playing, seekable = rec.timelines[-1]
    assert dur == 200_000 and playing and seekable


def test_prefers_spotify_over_other_players(music, world):
    world.add("Chrome", "Some video", "YouTube", cover_bytes())
    world.add("Spotify.exe", "Song", "Artist", cover_bytes())
    rec = Recorder()
    run_for(music.MediaWorker(rec), 0.3)
    assert titles(rec)[-1] == "Song"


def test_player_closes_and_another_takes_over(music, world):
    sp = world.add("Spotify.exe", "Song", "Artist", cover_bytes())
    rec = Recorder()

    async def during():
        await asyncio.sleep(0.2)
        world.remove(sp)                                   # Spotify closed, nothing else playing
        await asyncio.sleep(0.2)
        world.add("Chrome", "Video", "Channel", None)      # a browser starts, no cover art
    run_for(music.MediaWorker(rec), 0.3, during)
    assert titles(rec) == ["Song", None, "Video"]
    assert rec.tracks[-1][2] is None
    assert (0, 0, False, False) in rec.timelines


def test_cover_that_shows_up_late(music, world):
    s = world.add("Spotify.exe", "Song", "Artist", None)
    rec = Recorder()

    async def during():
        await asyncio.sleep(0.25)
        s.cover = cover_bytes()
    run_for(music.MediaWorker(rec), 0.3, during)
    assert titles(rec) == ["Song", "Song"]
    assert rec.tracks[0][2] is None and rec.tracks[1][2] is not None


def test_broken_cover_stream_is_survived(music, world):
    s = world.add("Spotify.exe", "Song", "Artist", cover_bytes())
    s.cover_fails = True
    rec = Recorder()
    run_for(music.MediaWorker(rec), 0.3)
    assert titles(rec) == ["Song"] and rec.tracks[0][2] is None


def test_hung_media_call_does_not_freeze_the_card(music, world):
    """Before, one media call that never answered froze the card on that song forever."""
    s = world.add("Spotify.exe", "Song A", "Artist", cover_bytes())
    rec = Recorder()

    async def during():
        await asyncio.sleep(0.15)
        s.hang = True
        await asyncio.sleep(0.8)                           # a few timeouts go by
        s.hang = False
        s.title = "Song B"
    run_for(music.MediaWorker(rec), 0.6, during)
    assert titles(rec)[-1] == "Song B"


def test_media_service_not_ready_at_login(music, world):
    """Before, any error here showed 'Setup needed' for good. Now it waits and tries again."""
    world.request_failures = 3
    world.add("Spotify.exe", "Song", "Artist", cover_bytes())
    rec = Recorder()
    run_for(music.MediaWorker(rec), 1.0)
    assert world.requests == 4
    assert rec.errors == [] and titles(rec)[-1] == "Song"


def test_stale_manager_gets_replaced(music, world):
    world.add("Spotify.exe", "Song", "Artist", cover_bytes())
    rec = Recorder()

    async def during():
        await asyncio.sleep(0.1)
        world.broken = True
        await asyncio.sleep(0.15)
        world.broken = False
    run_for(music.MediaWorker(rec), 0.3, during)
    assert world.requests >= 2


def test_missing_winrt_says_setup_needed(music):
    fake_winrt.uninstall()
    import sys
    sys.modules["winrt"] = None                            # makes the import fail like a missing package
    try:
        rec = Recorder()
        music.MediaWorker(rec).run()
        assert len(rec.errors) == 1
    finally:
        del sys.modules["winrt"]


def test_commands_reach_the_player(music, world):
    s = world.add("Spotify.exe", "Song", "Artist", cover_bytes())
    w = music.MediaWorker(Recorder())

    async def go():
        w.mgr = await fake_winrt.Manager.request_async()
        for c in ("toggle", "next", "prev"):
            await w._command(c)
    asyncio.run(go())
    assert s.commands == ["toggle", "next", "prev"]


def test_position_math(music):
    assert music.to_ms(datetime.timedelta(seconds=61.5)) == 61_500
    assert music.to_ms(None) == 0
    assert music.to_ms(10_000_000) == 1000              # raw 100 ns ticks
    now = datetime.datetime(2026, 1, 1, 12, 0, 10, tzinfo=datetime.timezone.utc)
    assert music.caught_up(5000, 200_000, now - datetime.timedelta(seconds=2), now) == 7000
    assert music.caught_up(5000, 200_000, now + datetime.timedelta(seconds=2), now) == 5000   # clock skew
    assert music.caught_up(5000, 1000, now - datetime.timedelta(seconds=2), now) == 5000      # stale report
    assert music.caught_up(5000, 200_000, None, now) == 5000
