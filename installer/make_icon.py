"""Draws installer/aura.ico, the same rounded square and dot as the tray icon."""
import os
from PIL import Image, ImageDraw

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aura.ico")
big = 1024
im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle([64, 64, big - 64, big - 64], radius=256, fill=(38, 36, 40, 255))
d.ellipse([352, 352, big - 352, big - 352], fill=(236, 238, 244, 255))
im.resize((256, 256), Image.Resampling.LANCZOS).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
