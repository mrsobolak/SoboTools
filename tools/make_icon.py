"""Render assets/sobolak.ico (multi-size) and assets/sobolak.png from the brand mark."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sobolak_repair.theme import _gradient, squircle_points  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
S = 1024
tile = _gradient(S, S, ("#0A84FF", "#BF5AF2"), 45).convert("RGBA")
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).polygon(squircle_points(24, 24, S - 24, S - 24, 300), fill=255)
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
img.paste(tile, (0, 0), mask)
font = ImageFont.truetype(os.path.join(ROOT, "assets", "fonts", "InterDisplay-Bold.otf"), 600)
ImageDraw.Draw(img).text((S / 2, S / 2 + 20), "S", font=font, fill="white", anchor="mm")
img.resize((256, 256), Image.LANCZOS).save(os.path.join(ROOT, "assets", "sobolak.png"))
img.save(os.path.join(ROOT, "assets", "sobolak.ico"),
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok")
