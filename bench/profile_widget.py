"""
Runs one widget exactly as normal, but times every time its window paints. Used by bench_windows.py.
It swaps in a QApplication that wraps notify(), so the widget code itself is untouched.

    python bench/profile_widget.py aura_clock --out paints.csv
Each line of the csv is: wall clock time, how long that paint took in ms.
"""
import os, sys, time, runpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PyQt6 import QtWidgets
from PyQt6.QtCore import QEvent, QTimer


def main():
    stem = sys.argv[1]
    out = sys.argv[sys.argv.index("--out") + 1]
    f = open(out, "w", buffering=1)
    rows = []

    class Timed(QtWidgets.QApplication):
        def __init__(self, argv):
            super().__init__(argv)
            # written out once a second, since the benchmark ends this process with a hard kill
            self.flusher = QTimer(interval=1000)
            self.flusher.timeout.connect(self.flush)
            self.flusher.start()

        def flush(self):
            if rows:
                f.write("".join(f"{t:.4f},{ms:.3f}\n" for t, ms in rows))
                rows.clear()

        def notify(self, obj, ev):
            if ev.type() == QEvent.Type.Paint and type(obj).__name__ == "Widget":
                t0 = time.perf_counter()
                r = super().notify(obj, ev)
                rows.append((time.time(), (time.perf_counter() - t0) * 1000))
                return r
            return super().notify(obj, ev)

    QtWidgets.QApplication = Timed
    sys.argv = [os.path.join(ROOT, stem + ".pyw")]
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
