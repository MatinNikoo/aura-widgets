"""
Drawing pieces the widgets share: card shapes, how far a shape cuts into a row of text,
shaped shadows, and the GIF player (used by the GIF boxes and the clock background).
"""
import math, time

from PIL import Image, ImageDraw, ImageFilter
from PyQt6.QtCore import QObject, QPointF, QRectF, QTimer, pyqtSignal
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QImageReader, QPainterPath, QPen, QPolygonF


# ---------------------------------------------------------------- shapes
def corner(shape, w, h, radius):
    """Corner radius a shape really uses on a w x h card."""
    if shape == "square":
        return 0
    if shape in ("pill", "circle"):
        return min(w, h) / 2
    return max(0, min(radius, min(w, h) / 2))


def squircle_points(x, y, w, h, n=4, steps=120):
    a, b = w / 2, h / 2
    cx, cy = x + a, y + b
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        pts.append((cx + a * math.copysign(abs(c) ** (2 / n), c), cy + b * math.copysign(abs(s) ** (2 / n), s)))
    return pts


def shape_path(shape, rect, radius):
    p = QPainterPath()
    if shape == "circle":
        p.addEllipse(rect)
    elif shape == "squircle":
        p.addPolygon(QPolygonF([QPointF(*pt) for pt in squircle_points(rect.x(), rect.y(), rect.width(), rect.height())]))
        p.closeSubpath()
    elif shape == "square":
        p.addRect(rect)
    else:
        r = corner(shape, rect.width(), rect.height(), radius)
        p.addRoundedRect(rect, r, r)
    return p


def border_path(shape, w, h, radius):
    return shape_path(shape, QRectF(0.5, 0.5, w - 1, h - 1), radius - 0.5)


def draw_border(p, kind, shape, w, h, radius, thin_alpha=20):
    """The hairline edge around a card. Thin is what 1.0 drew."""
    if kind == "none":
        return
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "bold":
        p.setPen(QPen(QColor(255, 255, 255, 70), 2))
        p.drawPath(shape_path(shape, QRectF(1, 1, w - 2, h - 2), radius - 1))
    else:
        p.setPen(QPen(QColor(255, 255, 255, thin_alpha), 1))
        p.drawPath(border_path(shape, w, h, radius))


def inset(shape, w, h, radius, y0, y1):
    """How far in from the left and right edge the shape is, at its narrowest between y0 and y1.
    Text on that band has to stay inside this, or the shape would cut it off."""
    y0, y1 = max(0.0, y0), min(float(h), y1)
    if shape == "square":
        return 0.0
    if shape == "circle":
        r = w / 2
        dy = max(abs(y0 - h / 2), abs(y1 - h / 2))
        return r if dy >= r else r - math.sqrt(r * r - dy * dy)
    if shape == "squircle":
        a, b = w / 2, h / 2
        dy = min(1.0, max(abs(y0 - b), abs(y1 - b)) / b)
        return a - a * (1 - dy ** 4) ** 0.25
    r = corner(shape, w, h, radius)
    d = min(y0, h - y1)
    if d >= r:
        return 0.0
    return r - math.sqrt(max(0.0, r * r - (r - d) ** 2))


def shadow_pil(w, h, m, shape, radius, alpha, s=2):
    """The soft shadow under a card, blurred in Pillow like 1.0 did."""
    im = Image.new("RGBA", ((w + 2 * m) * s, (h + 2 * m) * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = [m * s + 6, (m + 6) * s, (m + w) * s - 6, (m + h + 2) * s]
    if shape == "circle":
        d.ellipse(box, fill=(0, 0, 0, alpha))
    elif shape == "squircle":
        d.polygon(squircle_points(box[0], box[1], box[2] - box[0], box[3] - box[1]), fill=(0, 0, 0, alpha))
    else:
        d.rounded_rectangle(box, radius=corner(shape, w, h, radius) * s, fill=(0, 0, 0, alpha))
    return im.filter(ImageFilter.GaussianBlur(13 * s))


# ---------------------------------------------------------------- GIF playback
def readable(path):
    """True when Qt can actually decode a first frame, not just recognize the file header."""
    r = QImageReader(path)
    return r.canRead() and not r.read().isNull()


def frame_delay(delay, speed):
    """How long a frame stays up, in ms, for the GIF's own delay and the chosen speed."""
    if delay <= 10:
        delay = 100       # same rule browsers use: GIFs that ask for 0 to 10 ms run at 100 ms
    return max(10, int(delay / speed))


class FrameClock:
    """Keeps frames on a timeline. Waiting the full delay after each frame was drawn made every
    frame late by the time it took to decode and scale, so GIFs played slower than they should."""

    def __init__(self):
        self.due = None

    def reset(self):
        self.due = None

    def wait(self, step, now):
        # more than a frame behind (after a pause, sleep or a slow frame): start the timeline again
        if self.due is None or now - self.due > step:
            self.due = now
        self.due += step
        return max(0, int(round(self.due - now)))


class GifPlayer(QObject):
    """Plays a GIF frame by frame with its real timing, times a speed you choose."""
    frame = pyqtSignal(QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.reader = None
        self.speed = 1.0
        self.paused = False
        self.clock = FrameClock()
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self.next_frame)

    def open(self, path):
        if not readable(path):
            return False
        self.path = path
        self.reader = None
        self.timer.stop()
        self.clock.reset()
        self.next_frame()
        return True

    def first_frame(self):
        return QImageReader(self.path).read() if self.path else QImage()

    def next_frame(self):
        if self.path is None:
            return
        if self.reader is None or not self.reader.canRead():
            self.reader = QImageReader(self.path)       # back to the start, so it loops forever
        img = self.reader.read()
        if img.isNull():
            self.reader = QImageReader(self.path)
            img = self.reader.read()
            if img.isNull():
                return
        self.frame.emit(img)
        if self.reader.imageCount() == 1:
            return                                        # a still image, nothing to animate
        if not self.paused:
            step = frame_delay(self.reader.nextImageDelay(), self.speed)
            self.timer.start(self.clock.wait(step, time.monotonic() * 1000))

    def set_speed(self, v):
        self.speed = v
        self.clock.reset()

    def set_paused(self, paused):
        self.paused = paused
        if paused:
            self.timer.stop()
        elif self.path and not self.timer.isActive():
            self.clock.reset()
            self.next_frame()


# ---------------------------------------------------------------- previews
def sample_cover(size=480, seed=3):
    """A made up album cover for previews: soft color blobs on a gradient."""
    import random
    rng = random.Random(seed)
    base = [(rng.randint(20, 235), rng.randint(20, 235), rng.randint(20, 235)) for _ in range(2)]
    im = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(im)
    for y in range(size):
        t = y / size
        d.line([(0, y), (size, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(*base)))
    for _ in range(6):
        r = rng.randint(size // 10, size // 3)
        x, y = rng.randint(0, size), rng.randint(0, size)
        c = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    return im.filter(ImageFilter.GaussianBlur(size / 40))


def render(paint, w, h, dpr=2, opacity=1.0):
    """Draw a card into an image, the way the window would with that opacity."""
    from PyQt6.QtGui import QPainter
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint(p)
    p.end()
    if opacity >= 0.999:
        return img
    out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setOpacity(opacity)
    p.drawImage(0, 0, img)
    p.end()
    return out
