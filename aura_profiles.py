"""
Export and import of settings, and named profiles (a saved set of settings and positions you can switch to).

A file is plain JSON, so it can be read, edited and shared. Export leaves out positions, since a spot on
one PC means nothing on another. A profile keeps them, because switching profile should move the widgets.
"""
import os, re, json, time, logging

from PyQt6.QtCore import QPoint

import aura_common

FORMAT = "aura-settings"
NAME = re.compile(r"^(Widget|Clock|General|Gif(_[\w.\- ]{1,60})?)$")
LAYOUT_KEYS = ("w", "h", "pan_x", "pan_y")          # sizes, kept by the widgets themselves
POSITION_KEYS = ("pos", "spots")
PROFILES = os.path.join(aura_common.APP_DIR, "profiles")


def settings_files():
    """Names of the settings files that exist, like Widget, Clock, Gif_aura_gif_tall."""
    try:
        names = [n[:-4] for n in os.listdir(aura_common.SETTINGS_DIR) if n.endswith(".ini")]
    except OSError:
        return []
    return sorted(n for n in names if NAME.match(n))


def known_keys(name, positions):
    keys = [k for k, *_ in aura_common.fields(name)] if name != "General" else \
        [k for _, rows in aura_common.SCHEMA["General"] for k, *_ in rows]
    if name != "General":
        keys += LAYOUT_KEYS + (POSITION_KEYS if positions else ())
    return keys


def snapshot(positions=False):
    """Every setting that was changed from its default, as a dictionary that json can write."""
    out = {}
    for name in settings_files():
        s = aura_common.settings(name)
        values = {}
        for key in known_keys(name, positions):
            if not s.contains(key):
                continue
            v = s.value(key)
            values[key] = [v.x(), v.y()] if isinstance(v, QPoint) else str(v)
        if values:
            out[name] = values
    return {"format": FORMAT, "version": aura_common.__version__, "positions": positions, "settings": out}


def clean(data):
    """Check a loaded file and return {name: {key: value}} with only keys and values Aura understands,
    plus a list of what was left out. Raises ValueError for a file that isn't an Aura settings file."""
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("settings"), dict):
        raise ValueError("This isn't an Aura settings file.")
    kept, skipped = {}, []
    for name, values in data["settings"].items():
        if not NAME.match(str(name)) or not isinstance(values, dict):
            skipped.append(str(name))
            continue
        allowed = known_keys(name, True)
        fields = {k: (kind, default, extra) for k, kind, default, _, extra in
                  (aura_common.fields(name) if name != "General" else
                   [f for _, rows in aura_common.SCHEMA["General"] for f in rows])}
        got = {}
        for key, value in values.items():
            if key not in allowed:
                skipped.append(f"{name}.{key}")
            elif key == "pos":
                if isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
                    got[key] = (int(value[0]), int(value[1]))
                else:
                    skipped.append(f"{name}.{key}")
            elif key in fields:
                kind, default, extra = fields[key]
                got[key] = aura_common.coerce(kind, value, default, extra)
            else:
                got[key] = str(value)
        if got:
            kept[name] = got
    return kept, skipped


def apply(data):
    """Write a loaded file into the settings files. Settings that the file leaves out go back to their
    defaults, so the result matches the file. Returns (files written, left out)."""
    kept, skipped = clean(data)
    stamp = str(time.time())
    for name, values in kept.items():
        s = aura_common.settings(name)
        for key in known_keys(name, bool(data.get("positions"))) + ["fit"]:
            s.remove(key)
        for key, v in values.items():
            s.setValue(key, QPoint(*v) if key == "pos" else aura_common.store(v))
        if name.startswith("Gif") and "mode" in values:
            s.setValue("fit", "true" if values["mode"] == "fit" else "false")     # 1.0 reads this one
        if data.get("positions"):
            s.setValue("move_token", stamp)           # running widgets move to the saved spot
        s.sync()
    return sorted(kept), skipped


def export_file(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot(positions=False), f, indent=2, sort_keys=True)
    return path


def import_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"Couldn't read that file ({e.__class__.__name__}).") from None
    return apply(data)


# ---------------------------------------------------------------- profiles
def profile_path(name):
    safe = re.sub(r"[^\w.\- ]+", "", name).strip(" .")
    if not safe:
        raise ValueError("Give the profile a name.")
    return os.path.join(PROFILES, safe[:60] + ".json")


def profile_names():
    try:
        return sorted((n[:-5] for n in os.listdir(PROFILES) if n.endswith(".json")), key=str.lower)
    except OSError:
        return []


def save_profile(name):
    path = profile_path(name)
    os.makedirs(PROFILES, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot(positions=True), f, indent=2, sort_keys=True)
    return os.path.splitext(os.path.basename(path))[0]


def load_profile(name):
    with open(profile_path(name), encoding="utf-8") as f:
        data = json.load(f)
    data["positions"] = True
    return apply(data)


def delete_profile(name):
    try:
        os.remove(profile_path(name))
    except OSError:
        logging.warning("couldn't delete the profile %s", name)


def reset_positions():
    """Send every widget back to its default spot."""
    stamp = str(time.time())
    for name in settings_files():
        if name == "General":
            continue
        s = aura_common.settings(name)
        s.remove("pos")
        s.remove("spots")
        s.setValue("move_token", stamp)
        s.sync()
