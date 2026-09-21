# Aura

Aesthetic desktop widgets for Windows. A now playing card for Spotify that takes its colors from the album cover, plus rounded GIF boxes that loop your favorite GIFs.

<img src="https://github.com/user-attachments/assets/80a9b825-ec9b-4324-8986-ba44bebc5dcf" width="100%" alt="Aura widgets">

## Widgets

**Now playing (`aura_widget.pyw`)**
* Album art dissolves into a rounded card tinted with the cover's main color
* Title, artist and progress bar are colored to match each song
* Smooth crossfade between songs, with playback controls on hover
* Reads playback through the Windows media session, so no Spotify login or API key is needed

**GIF boxes (`aura_gif.pyw`, `aura_gif_tall.pyw`)**
* Loops any GIF or animated WebP forever inside a rounded card
* Adjustable speed from 0.25x to 2x, pause and play
* Resize by dragging the edges, and hold Ctrl while dragging to choose which part of the GIF shows
* Copy the file under a new name to get another independent box

   **Clock (`aura_clock.pyw`)**
   * Time in 3D liquid chrome using the Unbounded font, with the date underneath
   * A 3D chrome star that softly shines every few seconds, plus tiny twinkling stars
   * Uses your PC's clock, with 12 or 24 hour time and optional seconds
   * 
**All widgets**
* Drag anywhere on the desktop, and positions are remembered
* Optional launch at startup
* Automatically pause while a fullscreen game or video is open, so they use almost no resources while gaming
* Nothing is injected into other programs, which keeps them friendly with game anti cheat

## How it works

* **Now playing data** comes from the Windows `GlobalSystemMediaTransportControlsSessionManager` API through the `winrt` Python bindings, polled on a background asyncio thread and passed to the UI with Qt signals
* **Color palette** is pulled from the cover with median cut quantization in Pillow, scored by how common and how saturated each color is, then turned into background, text and accent shades in HSV
* **Rendering** uses PyQt6 with a frameless translucent window, antialiased rounded clipping, a gradient alpha mask for the art fade and a pre blurred drop shadow
* **GIF playback** uses a custom frame scheduler that follows each frame's own delay, applies the same minimum delay rule browsers use, and scales timing by the chosen speed
* **Game detection** checks every two seconds whether the foreground window covers the whole monitor, using Win32 calls through `ctypes`
* **3D chrome text** turns each letter into a height map, works out which way every pixel faces, and shades it like a polished metal reflection with NumPy. Each character is rendered once and reused, so updating the time costs almost nothing
## Setup

1. Install [Python 3.12+](https://www.python.org/downloads/) and check **Add python.exe to PATH**
2. Download this repo and double click `install.bat`
3. Double click any `.pyw` file to open that widget, then right click it for options

Or install the requirements yourself.

    pip install -r requirements.txt

## Built with

Python, PyQt6, Pillow, NumPy, WinRT (Windows media session API), Win32 via ctypes

## License

MIT

The Unbounded font is included under the SIL Open Font License (see `fonts/OFL.txt`).
