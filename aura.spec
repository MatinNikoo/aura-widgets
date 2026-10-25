# Builds dist/Aura, a folder with Aura.exe and everything it needs.
#     pyinstaller aura.spec
import sys
from PyInstaller.utils.hooks import collect_submodules

hidden = ["aura_common", "aura_draw", "aura_ui", "aura_settings", "aura_profiles", "aura_hotkey", "aura_library",
          "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
          "PIL.Image", "PIL.ImageDraw", "PIL.ImageFilter", "PIL.ImageFont", "numpy",
          "asyncio", "colorsys", "datetime", "shutil", "random", "json", "glob", "ctypes", "ctypes.wintypes"]
if sys.platform == "win32":
    # the winrt packages are namespace packages, so the ones the widgets use are named as well
    hidden += ["winrt.windows.media.control", "winrt.windows.storage.streams", "winrt.windows.foundation",
               "winrt.windows.foundation.collections", "winrt._winrt"]
    hidden += collect_submodules("winrt")

# the widgets run from their .pyw files, so they ship as plain files next to the libraries
datas = [(f, ".") for f in ("aura_widget.pyw", "aura_clock.pyw", "aura_gif.pyw", "aura_gif_tall.pyw",
                            "Unbounded.ttf", "OFL.txt", "LICENSE")]

a = Analysis(["aura.py"], datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "scipy", "pandas", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Aura", console=False,
          icon="installer/aura.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="Aura")
