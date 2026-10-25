import os, sys, io, tempfile, importlib.machinery, importlib.util

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# keep test runs out of the real %APPDATA%\Aura
_tmp = tempfile.mkdtemp(prefix="aura_test_")
os.environ["APPDATA"] = _tmp
os.environ["AURA_OLD_ORG"] = "AuraTestNothingHere"    # never copy real 1.0 settings from the registry
os.environ["AURA_NO_WELCOME"] = "1"                   # the first run note only shows in its own test


def env_for(tmp_path):
    """Environment for a widget run in a subprocess: its own settings, logs and lock files, so tests
    never clash with widgets that are open on the same PC."""
    t = str(tmp_path)
    os.makedirs(t, exist_ok=True)
    return dict(os.environ, APPDATA=t, TMPDIR=t, TMP=t, TEMP=t, XDG_CONFIG_HOME=t, QT_QPA_PLATFORM="offscreen")

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load(stem):
    """Import a .pyw widget file as a module (Linux doesn't treat .pyw as importable)."""
    if stem in sys.modules:
        return sys.modules[stem]
    path = os.path.join(ROOT, stem + ".pyw")
    loader = importlib.machinery.SourceFileLoader(stem, path)
    spec = importlib.util.spec_from_loader(stem, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[stem] = mod
    loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def music(app):
    return load("aura_widget")


@pytest.fixture(scope="session")
def gif(app):
    return load("aura_gif")


@pytest.fixture(scope="session")
def clock(app):
    return load("aura_clock")


def cover_bytes(color=(200, 40, 60), size=(300, 300), fmt="JPEG", patch=None):
    from PIL import Image
    im = Image.new("RGB", size, color)
    if patch:
        box, c = patch
        im.paste(c, box)
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def make_gif(path, delays, size=(120, 80)):
    from PIL import Image
    frames = [Image.new("RGB", size, (i * 40 % 255, 80, 200 - i * 20 % 200)) for i in range(len(delays))]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=list(delays), loop=0, disposal=2)
    return path


def spin(app, ms):
    """Run the Qt event loop for a while."""
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
