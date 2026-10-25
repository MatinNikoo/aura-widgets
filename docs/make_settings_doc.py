"""Writes docs/settings.md from the settings list in aura_common.py, so the two never disagree.
    python docs/make_settings_doc.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import aura_common

TITLES = {"Widget": "Now playing card (Widget.ini)", "Clock": "Clock (Clock.ini)",
          "Gif": "GIF boxes (Gif.ini, and Gif_<file name>.ini for each copy)",
          "General": "Shared by every widget (General.ini)"}


def allowed(kind, extra):
    if kind == "bool":
        return "true or false"
    if kind in ("int", "float"):
        return f"{extra[0]} to {extra[1]}"
    if kind == "choice":
        return ", ".join(f"`{v}`" for v, _ in extra)
    if kind == "monitor":
        return "a monitor name, or empty for wherever you drag it"
    if kind == "font":
        return "any installed font family, or empty for Unbounded"
    if kind == "file":
        return "a path to a GIF, WebP, PNG or JPG, or empty"
    if kind == "folder":
        return "a folder path, or empty"
    if kind == "hotkey":
        return "Ctrl, Alt or Win plus a key, like `Ctrl+Alt+A`"
    return ""


def show(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return "empty" if v == "" else f"`{v}`"


def main():
    lines = ["# Settings", "",
             "Every widget keeps its settings in one small file in `%APPDATA%\\Aura\\settings\\`. The easiest way to",
             "change them is the settings window (right click a widget, Settings, or run `python aura.py settings`).",
             "It shows a live preview and writes the file for you. You can also edit the file while the widgets run,",
             "they pick up the change within a second.", "",
             "With the defaults every card looks exactly like version 1.0 (a test checks this pixel by pixel). Two",
             "things act differently on purpose. Clicking or dragging the progress bar seeks, and GIFs play at their",
             "real speed. The CHANGELOG explains both.", "",
             "Version 1.0 kept settings in the registry (`HKCU\\Software\\Aura`). The first time 1.1 runs it copies them",
             "over and leaves the registry alone.", "",
             "This page is made from the list in `aura_common.py` by `docs/make_settings_doc.py`.", ""]
    for name, title in TITLES.items():
        lines += [f"## {title}", ""]
        for section, rows in aura_common.SCHEMA[name]:
            lines += [f"**{section}**", "", "| Key | What it does | Default | Allowed |", "|---|---|---|---|"]
            for key, kind, default, label, extra in rows:
                lines.append(f"| `{key}` | {label} | {show(default)} | {allowed(kind, extra)} |")
            lines.append("")
    lines += ["## Kept by the widgets themselves", "",
              "| Key | Where | What it is |", "|---|---|---|",
              "| `pos` | all | last spot you dragged the widget to |",
              "| `spots` | all | the last spot on each monitor, so unplugging one doesn't lose the widget |",
              "| `w`, `h` | GIF boxes | card size after resizing |",
              "| `pan_x`, `pan_y` | GIF boxes | which part of a cropped GIF shows (Ctrl + drag) |",
              "| `gif` | GIF boxes | the GIF you chose (a copy kept in `%APPDATA%\\Aura\\gifs`) |",
              "| `folder_current` | GIF boxes | which GIF from the folder is showing |",
              "| `fit` | GIF boxes | the 1.0 version of `mode`, still read if `mode` is missing |",
              "| `rect` | all | where the card sits, so other widgets can snap to it (removed when the widget closes) |",
              "| `move_token` | all | the settings window changes this to ask a running widget to go back to its saved or default spot |",
              "| `choose` | GIF boxes | the settings window puts a file path here to ask a running box to show that GIF |", "",
              "## Kept in General.ini", "",
              "| Key | What it is |", "|---|---|",
              "| `hidden`, `hidden_at` | whether the widgets are hidden right now. Widgets only react to a change, so a value left over from last time does nothing |",
              "| `library` | the folder Find a GIF searched last |",
              "| `welcomed` | set once the first run note has shown |",
              "| `version` | the version that created the file |", "",
              "## Other files", "",
              "* Logs go to `%APPDATA%\\Aura\\logs\\<widget>.log` and take at most about 4 MB each. Nothing is sent anywhere.",
              "* Profiles are JSON files in `%APPDATA%\\Aura\\profiles\\`. Export writes the same format without positions.",
              "* Open when my PC starts is a value under `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`"
              " named `AuraWidget`, `AuraClockWidget`, `AuraGifWidget` or `Aura_<file name>`.", ""]
    with open(os.path.join(HERE, "settings.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(os.path.join(HERE, "settings.md"))


if __name__ == "__main__":
    main()
