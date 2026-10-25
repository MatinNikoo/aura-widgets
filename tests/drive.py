"""
Runs a widget's real main() offscreen and hands the live window to a script.
Used by the GIF tests, bench/soak.py, bench/demo.py and bench/profile_widget.py.
"""
import os, sys, importlib.machinery, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)


def load(stem, path=None):
    path = path or os.path.join(ROOT, stem + ".pyw")
    loader = importlib.machinery.SourceFileLoader(stem, path)
    spec = importlib.util.spec_from_loader(stem, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[stem] = mod
    loader.exec_module(mod)
    return mod


def run(mod, script, app_class=None):
    """Call mod.main() and run script(app, window) once the event loop starts.
    The script quits the app when it's done and keeps its own results."""
    from PyQt6 import QtWidgets
    from PyQt6.QtCore import QTimer
    base = app_class or QtWidgets.QApplication

    class Driven(base):
        def exec(self):
            def start():
                wins = [w for w in self.topLevelWidgets() if type(w).__name__ == "Widget"]
                script(self, wins[0])
            QTimer.singleShot(0, start)
            return super().exec()

    real = QtWidgets.QApplication
    QtWidgets.QApplication = Driven
    try:
        mod.main()
    except SystemExit:
        pass
    finally:
        QtWidgets.QApplication = real
