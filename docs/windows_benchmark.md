# Measuring on Windows

Every number in the README comes from a Linux machine with the widgets drawing offscreen. This is how to get the
same kind of numbers from a real Windows PC.

Close any Aura widgets, play a song in Spotify so the music card has something to draw, and run this from the
repo folder.

    py bench\bench_windows.py

It takes about 12 minutes. It starts the music, clock and GIF widgets one at a time with paint timing on, and
measures how long each takes to show up. Then it samples CPU, private memory, handles and GDI and USER objects
once a second while the PC is idle. Then it opens a black fullscreen window, which should make every widget
pause, and samples again.

Longer runs are optional.

    py bench\bench_windows.py --game-minutes 10       start a game when it says so
    py bench\bench_windows.py --long-hours 8          leave it overnight for the memory trend
    py bench\bench_windows.py --battery-minutes 20    on a laptop running on battery

The results are saved to `results/windows_<computer>_<date>.json` and a table is printed that can be pasted into
the README. Until that has been run the README only has the Linux numbers.
