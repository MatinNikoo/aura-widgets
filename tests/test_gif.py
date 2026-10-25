"""GIF timing and the GIF widget's file handling."""
import os, sys, json, time, subprocess, textwrap

import pytest

from conftest import make_gif, spin, ROOT, env_for


def test_frame_delay_rules(gif):
    assert gif.frame_delay(40, 1.0) == 40
    assert gif.frame_delay(0, 1.0) == 100         # browsers treat 0 to 10 ms as 100 ms
    assert gif.frame_delay(10, 1.0) == 100
    assert gif.frame_delay(40, 2.0) == 20
    assert gif.frame_delay(20, 2.0) == 10
    assert gif.frame_delay(20, 4.0) == 10         # never faster than 10 ms


def test_frame_clock_takes_out_the_drawing_time(gif):
    c = gif.FrameClock()
    now = 0.0
    shown = []
    for _ in range(50):
        shown.append(now)
        now += 7                                   # decoding and scaling took 7 ms
        wait = c.wait(40, now)
        now += wait + 1                            # and the timer fired 1 ms late
    gaps = [b - a for a, b in zip(shown, shown[1:])]
    assert abs(sum(gaps) / len(gaps) - 40) < 0.5   # the old way averaged 48 ms here


def test_frame_clock_averages_out_coarse_timers(gif):
    """Windows' default timers tick every 15.6 ms. A 20 ms GIF should still average 20 ms."""
    import math
    c = gif.FrameClock()
    now, shown = 0.0, []
    for _ in range(200):
        shown.append(now)
        wait = c.wait(20, now)
        now += math.ceil(wait / 15.625) * 15.625 if wait else 0.5
    gaps = [b - a for a, b in zip(shown, shown[1:])]
    assert abs(sum(gaps) / len(gaps) - 20) < 1


def test_frame_clock_restarts_after_a_stall(gif):
    c = gif.FrameClock()
    c.wait(40, 0)
    assert c.wait(40, 10_000) == 40                # after a long stall, no burst of catch up frames


def test_player_loops_and_keeps_time(gif, app, tmp_path):
    path = make_gif(str(tmp_path / "a.gif"), [40] * 5)
    p = gif.GifPlayer()
    stamps = []
    p.frame.connect(lambda img: stamps.append(time.monotonic()))
    assert p.open(path)
    spin(app, 1500)
    p.set_paused(True)
    n = len(stamps)
    assert n > 10                                  # went round the 5 frames more than twice
    rate = (n - 1) / (stamps[-1] - stamps[0])
    assert 20 < rate < 27                          # about 25 frames a second
    spin(app, 300)
    assert len(stamps) == n                        # paused means no more frames


def test_player_speed(gif, app, tmp_path):
    path = make_gif(str(tmp_path / "b.gif"), [100] * 4)
    p = gif.GifPlayer()
    stamps = []
    p.frame.connect(lambda img: stamps.append(time.monotonic()))
    p.set_speed(2.0)
    p.open(path)
    spin(app, 1200)
    p.set_paused(True)
    rate = (len(stamps) - 1) / (stamps[-1] - stamps[0])
    assert 17 < rate < 21                          # 100 ms frames at 2x is 20 a second


def test_still_image_and_bad_files(gif, app, tmp_path):
    from PIL import Image
    still = str(tmp_path / "still.gif")
    Image.new("RGB", (50, 50), (1, 2, 3)).save(still)
    p = gif.GifPlayer()
    got = []
    p.frame.connect(got.append)
    assert p.open(still)
    spin(app, 300)
    assert len(got) == 1 and not p.timer.isActive()
    bad = tmp_path / "bad.gif"
    bad.write_bytes(b"GIF89a not really")
    assert not gif.GifPlayer().open(str(bad))
    assert not gif.GifPlayer().open(str(tmp_path / "missing.gif"))


CHOOSE = textwrap.dedent("""
    import os, sys, json
    sys.path.insert(0, {tests!r})
    import drive
    mod = drive.load("aura_gif")
    out = {{}}

    def script(app, w):
        d = mod.GIF_DIR
        w.choose({first!r})
        out["after_first"] = sorted(os.listdir(d))
        w.choose({bad!r})                              # not a GIF: keep the current one
        out["after_bad"] = sorted(os.listdir(d))
        out["still_playing"] = w.player.path is not None
        w.choose(os.path.join(d, "current.gif"))       # pick the copy Aura already keeps
        out["after_self"] = sorted(os.listdir(d))
        out["playing_after_self"] = w.player.path is not None
        w.choose({second!r})
        out["after_second"] = sorted(os.listdir(d))
        app.quit()

    drive.run(mod, script)
    print(json.dumps(out))
""")


def test_choosing_gifs(tmp_path):
    first = make_gif(str(tmp_path / "first.gif"), [50] * 3)
    second = make_gif(str(tmp_path / "second.gif"), [50] * 3)
    bad = tmp_path / "notes.gif"
    bad.write_text("hello")
    env = env_for(tmp_path / "appdata")
    code = CHOOSE.format(tests=os.path.join(ROOT, "tests"), first=first, second=second, bad=str(bad))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["after_first"] == ["current.gif"]
    assert out["after_bad"] == ["current.gif"] and out["still_playing"]
    # the old code deleted current.gif before copying it onto itself, then crashed
    assert out["after_self"] == ["current.gif"] and out["playing_after_self"]
    assert out["after_second"] == ["current.gif"]


def test_gif_copies_get_their_own_settings(tmp_path):
    """README: copy the file under a new name to get another box. Before, copies of aura_gif.pyw shared
    the original's lock and settings, so the copy just closed itself."""
    import shutil
    for name in ("aura_gif.pyw", "aura_common.py"):
        shutil.copy(os.path.join(ROOT, name), tmp_path / name)
    shutil.copy(os.path.join(ROOT, "aura_gif.pyw"), tmp_path / "aura_gif_cats.pyw")
    code = textwrap.dedent(f"""
        import sys, json
        sys.path.insert(0, {os.path.join(ROOT, 'tests')!r})
        import drive
        a = drive.load("aura_gif", {str(tmp_path / 'aura_gif.pyw')!r})
        b = drive.load("aura_gif_cats", {str(tmp_path / 'aura_gif_cats.pyw')!r})
        print(json.dumps([[a.SETTINGS_KEY, a.RUN_NAME, a.GIF_DIR], [b.SETTINGS_KEY, b.RUN_NAME, b.GIF_DIR],
                          [a.LOCK_NAME, b.LOCK_NAME]]))
    """)
    env = env_for(tmp_path / "appdata")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env)
    assert r.returncode == 0, r.stderr
    a, b, locks = json.loads(r.stdout.strip().splitlines()[-1])
    assert a[:2] == ["Gif", "AuraGifWidget"] and a[2].endswith("gifs")      # the original keeps its old names
    assert b[:2] == ["Gif_aura_gif_cats", "Aura_aura_gif_cats"] and b[2].endswith("gifs_aura_gif_cats")
    assert locks == ["aura_gif_widget.lock", "aura_aura_gif_cats.lock"]     # the original keeps its 1.0 lock name
