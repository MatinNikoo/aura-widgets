# Changelog

## 1.1.0

With default settings every card still draws exactly what 1.0 drew, except text that was too faint to read (below).
`tests/test_defaults_match_v1.py` renders the 1.0 files and the new ones side by side and compares every pixel.
Everything new is a setting you turn on.

### Things that act differently on purpose
* Click or drag the progress bar to seek. The bar shows a dot and the time you'd jump to while you hover or drag.
  It uses the same Windows media session as the play buttons. If the player doesn't allow seeking, the bar works
  like before. You can turn it off in Settings.
* GIFs play at their real speed. The old player waited a frame's full delay after it had already spent time
  decoding and scaling that frame, so every frame came late. On my test machine a 20 ms GIF played at 0.65x and a
  GIF at 2x speed played at 0.70x. Frames now run on a timeline, which gives 0.96x to 1.00x
  (`results/gif_timing.json`). Fast GIFs will look a little quicker than before because they're finally right.
* Faint text gets a little brighter, only where it was hard to read. I checked the card's text against the real
  pixels behind it on 122 public domain paintings used as covers. In 1.0 the title always passed WCAG's 4.5:1,
  but the artist line missed 4.5:1 on 115 of them and fell under 3:1 on 11, and the times fell under 3:1 on 44. Now any
  line under 3:1 is made less see-through and then lighter, just until it reaches 3:1. That changed the text on
  55 of the 122 covers and left the rest exactly as 1.0 drew them (`results/contrast.json`). The new
  "High contrast text" setting takes every line to 4.5:1.
* The right click menus have new items. Settings and Reset position on every widget, and Find a GIF in a folder on the GIF boxes.

### Fixes
* Memory leak in the fullscreen check. Every 2 seconds each widget built a new ctypes structure type, and ctypes
  caches a pointer type for each one forever. Running the actual 1.0 function 20,000 times kept about 6.3 KB per call,
  which is about 270 MB a day per widget. The new one keeps nothing (`results/ctypes_leak.json`). Measured on Python
  3.13. Python 3.14 changed how ctypes caches these, so it may not leak there.
* Errors no longer kill a widget without a trace. PyQt6 aborts the app on any error inside a Qt event when no
  error hook is set, and pythonw has no console to show it. Errors now go to `%APPDATA%\Aura\logs` and the widget
  keeps running.
* The log can't fill the disk. It used to grow forever, for example one line every 0.8 s for a cover that
  couldn't be read. Logs now rotate at 1 MB, three old files kept, one log per widget.
* A stuck media call no longer freezes the music card. Every Windows media call gives up after 5 seconds.
* No more "Setup needed" right after login. If the Windows media service isn't ready yet, the widget keeps
  trying with a growing wait instead of giving up. After five failed reads in a row it also asks Windows for a fresh
  media manager.
* Widgets can't get lost off screen. If you unplug the monitor a widget was on, it moves to its last spot on a
  monitor you still have (or to its default spot), then moves back when the monitor returns.
* Copies of `aura_gif.pyw` are separate boxes again, like the README says. Before, a copy shared the original's
  settings and lock, so it just closed itself.
* Choosing a GIF is safe. Picking the GIF that was already showing used to crash the box, and picking a file
  that couldn't be decoded wiped the current GIF.
* The clock catches up after sleep. If its minute timer fires late, the clock redraws within 2 seconds.
* Sharper on very high DPI screens. Album art and GIF frames were always cached at 2x, so at 250% scaling, or 200%
  with the Large size, they were stretched. They're now cached at the detail the screen needs (2x stays the minimum,
  so normal setups draw exactly as before).
* A broken value in the settings no longer stops a widget from starting.
* Drawing is a bit cheaper. The shadows and the clock's letters, date and stars are converted once to the format Qt
  draws with, which stops Qt converting them again on every frame. The pixels are identical (the 1.0 comparison test
  still passes). On my Linux test machine the clock frame went from 2.8 ms to 1.7 ms of CPU
  (`results/render_bench_linux.json`).
* The text contrast check reads a sample of pixels in plain Python, so the music widget doesn't load NumPy. When I
  tried it with NumPy the widget used 93 MB instead of 77 MB.
* `numpy` was missing from `requirements.txt` and `install.bat`, so the clock quietly fell back to flat letters.
  `requirements.txt` uses minimum versions and `install.bat` upgrades, while `requirements-lock.txt` has the exact
  versions CI tests with.

### New, all off or identical by default
* A settings window with a tab per widget, a live preview drawn by the real widget code, and Reset to defaults.
  Settings live in one ini file per widget (`docs/settings.md`), and running widgets pick up changes right away.
  1.0 settings are copied over from the registry the first time.
* Shapes for every widget. You can pick rounded with any corner radius, square, squircle, pill and circle. The round music card
  has its own layout with the album art filling the circle and a progress ring. Text gets cut off with "..." when it
  doesn't fit, and `tests/test_layout.py` checks that nothing overlaps or sticks out of the shape in any combination.
* Music card options are text size, plain dark colors, and which parts show (artist, bar, times, buttons).
* Clock options are a GIF or picture behind the time, any installed font, flat or chrome letters, time size, date formats, and
  the date in 16 languages through Qt's locale data. Persian uses the Persian calendar.
* GIF box options are fill, fit or stretch, and play every GIF in a folder, switching every 1 to 60 minutes, in order or shuffled.
* Opacity, border, shadow, lock position, click through, a tray icon (pause, settings, open with Windows, open log,
  close), pin to a monitor, and a remembered spot on each monitor.
* Make a problem report in Settings zips the logs and settings onto your Desktop after saying exactly what goes
  in it. Nothing is sent anywhere. There's an issue template that asks for it.
* An installer (`AuraSetup.exe`, per user, no admin needed) that can turn on open with Windows and removes
  everything it added when uninstalled. For the source version, `uninstall.bat`.
* An analog clock face. Hour and minute hands in chrome, a thin second hand when Show seconds is on, and the date
  beside the dial (under it on the round clock). Time size scales the dial.
* A blurred cover background for the music card. The cover shows through more, and the tint gets darker on bright
  covers so the text keeps its 3:1 contrast.
* Hide the music card 15 seconds after the player closes, and show it again when something plays.
* Find a GIF in a folder. Search by part of the file name, include subfolders, see thumbnails, double click to use one.
  It's in the GIF box's right click menu and in the settings window.
* Snap to screen edges, the middle of the screen and other widgets while dragging, with Alt held to skip it.
* Reset position, in each widget's right click menu, the tray menu and the settings window.
* A shortcut that hides and shows every widget, plus Hide all and Show all buttons, a tray item, and
  `python aura.py hide`, `show` and `toggle`.
* Profiles that save every setting and every position under a name, and export and import of settings as JSON
  without positions. Imports are checked, and anything unknown is left out.
* A General tab in the settings window for the shortcut, hide and show, profiles and backups.
* A short first run note that shows once, and only when this is a fresh install.
* `python aura.py <widget>` runs any widget, `python aura.py --check` loads them all and draws each card once.

### For checking it
* Tests run offscreen on Linux with the Windows media session faked, and CI runs them on Windows too, along with
  checks against the real winrt and registry, an exe build, an installer build and a silent install and uninstall.
* `bench/bench_windows.py` measures startup, idle CPU, memory, GDI objects, paint timing, fullscreen pausing,
  gaming and battery on a real PC.

## 1.0.0
First version with the now playing card, the GIF boxes and the chrome clock.
