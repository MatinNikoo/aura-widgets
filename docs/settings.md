# Settings

Every widget keeps its settings in one small file in `%APPDATA%\Aura\settings\`. The easiest way to
change them is the settings window (right click a widget, Settings, or run `python aura.py settings`).
It shows a live preview and writes the file for you. You can also edit the file while the widgets run,
they pick up the change within a second.

With the defaults every card looks exactly like version 1.0 (a test checks this pixel by pixel). Two
things act differently on purpose. Clicking or dragging the progress bar seeks, and GIFs play at their
real speed. The CHANGELOG explains both.

Version 1.0 kept settings in the registry (`HKCU\Software\Aura`). The first time 1.1 runs it copies them
over and leaves the registry alone.

This page is made from the list in `aura_common.py` by `docs/make_settings_doc.py`.

## Now playing card (Widget.ini)

**Look**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `shape` | Shape | `rounded` | `rounded`, `square`, `squircle`, `pill`, `circle` |
| `radius` | Corner radius | `26` | 0 to 60 |
| `scale` | Size | `1.0` | 0.6 to 1.6 |
| `opacity` | Opacity | `1.0` | 0.2 to 1.0 |
| `shadow` | Shadow | true | true or false |
| `border` | Border | `thin` | `thin`, `none`, `bold` |
| `colors` | Colors | `cover` | `cover`, `neutral` |
| `backdrop` | Background | `tint` | `tint`, `blur` |
| `high_contrast` | High contrast text (4.5:1 on every cover) | false | true or false |
| `text_size` | Text size | `100` | 80 to 130 |

**Shows**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `show_artist` | Artist | true | true or false |
| `show_bar` | Progress bar | true | true or false |
| `show_times` | Times | true | true or false |
| `show_controls` | Controls on hover | true | true or false |
| `hide_idle` | Hide the card while nothing is playing | false | true or false |

**Behavior**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `seek` | Click or drag the progress bar to seek | true | true or false |
| `on_top` | Keep on top of windows | false | true or false |
| `locked` | Lock position | false | true or false |
| `click_through` | Click through (get back to it from the tray icon) | false | true or false |
| `tray` | Tray icon | false | true or false |
| `snap` | Snap to screen edges and other widgets (hold Alt to skip) | false | true or false |
| `monitor` | Monitor | empty | a monitor name, or empty for wherever you drag it |

## Clock (Clock.ini)

**Look**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `shape` | Shape | `rounded` | `rounded`, `square`, `squircle`, `pill`, `circle` |
| `radius` | Corner radius | `26` | 0 to 60 |
| `scale` | Size | `1.0` | 0.6 to 1.6 |
| `opacity` | Opacity | `1.0` | 0.2 to 1.0 |
| `shadow` | Shadow | true | true or false |
| `border` | Border | `thin` | `thin`, `none`, `bold` |
| `face` | Face | `digital` | `digital`, `analog` |
| `style` | Text style | `chrome` | `chrome`, `flat` |
| `font` | Font | empty | any installed font family, or empty for Unbounded |
| `time_size` | Time size | `100` | 80 to 120 |
| `sparkle` | Sparkle animation | true | true or false |
| `background` | Background GIF or image | empty | a path to a GIF, WebP, PNG or JPG, or empty |
| `background_dim` | Darken background | `45` | 0 to 90 |

**Time and date**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `h24` | 24 hour time | false | true or false |
| `seconds` | Show seconds | false | true or false |
| `date` | Date | `weekday` | `weekday`, `full`, `short`, `numeric`, `iso`, `none` |
| `locale` | Language | empty | ``, `en_US`, `en_GB`, `fa_IR`, `ar_SA`, `he_IL`, `zh_CN`, `ja_JP`, `ko_KR`, `es_ES`, `fr_FR`, `de_DE`, `it_IT`, `pt_BR`, `ru_RU`, `tr_TR`, `hi_IN`, `sv_SE` |
| `lowercase` | Lowercase date | true | true or false |

**Behavior**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `on_top` | Keep on top of windows | false | true or false |
| `locked` | Lock position | false | true or false |
| `click_through` | Click through (get back to it from the tray icon) | false | true or false |
| `tray` | Tray icon | false | true or false |
| `snap` | Snap to screen edges and other widgets (hold Alt to skip) | false | true or false |
| `monitor` | Monitor | empty | a monitor name, or empty for wherever you drag it |

## GIF boxes (Gif.ini, and Gif_<file name>.ini for each copy)

**Look**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `shape` | Shape | `rounded` | `rounded`, `square`, `squircle`, `pill`, `circle` |
| `radius` | Corner radius | `26` | 0 to 60 |
| `opacity` | Opacity | `1.0` | 0.2 to 1.0 |
| `shadow` | Shadow | true | true or false |
| `border` | Border | `thin` | `thin`, `none`, `bold` |
| `mode` | Fit | `fill` | `fill`, `fit`, `stretch` |

**Playback**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `speed` | Speed | `1.0` | `0.25`, `0.5`, `0.75`, `1.0`, `1.25`, `1.5`, `2.0` |
| `paused` | Paused | false | true or false |
| `folder` | Play every GIF in a folder | empty | a folder path, or empty |
| `every` | Switch GIF | `10` | `1`, `5`, `10`, `30`, `60` |
| `shuffle` | Shuffle | false | true or false |

**Behavior**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `on_top` | Keep on top of windows | false | true or false |
| `locked` | Lock position | false | true or false |
| `click_through` | Click through (get back to it from the tray icon) | false | true or false |
| `tray` | Tray icon | false | true or false |
| `snap` | Snap to screen edges and other widgets (hold Alt to skip) | false | true or false |
| `monitor` | Monitor | empty | a monitor name, or empty for wherever you drag it |

## Shared by every widget (General.ini)

**Shortcut**

| Key | What it does | Default | Allowed |
|---|---|---|---|
| `hotkey_on` | Show or hide every widget with a shortcut | false | true or false |
| `hotkey` | Shortcut | `Ctrl+Alt+A` | Ctrl, Alt or Win plus a key, like `Ctrl+Alt+A` |

## Kept by the widgets themselves

| Key | Where | What it is |
|---|---|---|
| `pos` | all | last spot you dragged the widget to |
| `spots` | all | the last spot on each monitor, so unplugging one doesn't lose the widget |
| `w`, `h` | GIF boxes | card size after resizing |
| `pan_x`, `pan_y` | GIF boxes | which part of a cropped GIF shows (Ctrl + drag) |
| `gif` | GIF boxes | the GIF you chose (a copy kept in `%APPDATA%\Aura\gifs`) |
| `folder_current` | GIF boxes | which GIF from the folder is showing |
| `fit` | GIF boxes | the 1.0 version of `mode`, still read if `mode` is missing |
| `rect` | all | where the card sits, so other widgets can snap to it (removed when the widget closes) |
| `move_token` | all | the settings window changes this to ask a running widget to go back to its saved or default spot |
| `choose` | GIF boxes | the settings window puts a file path here to ask a running box to show that GIF |

## Kept in General.ini

| Key | What it is |
|---|---|
| `hidden`, `hidden_at` | whether the widgets are hidden right now. Widgets only react to a change, so a value left over from last time does nothing |
| `library` | the folder Find a GIF searched last |
| `welcomed` | set once the first run note has shown |
| `version` | the version that created the file |

## Other files

* Logs go to `%APPDATA%\Aura\logs\<widget>.log` and take at most about 4 MB each. Nothing is sent anywhere.
* Profiles are JSON files in `%APPDATA%\Aura\profiles\`. Export writes the same format without positions.
* Open when my PC starts is a value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` named `AuraWidget`, `AuraClockWidget`, `AuraGifWidget` or `Aura_<file name>`.
