#!/usr/bin/env python3
"""Render the SongSplit app icon: a white waveform on an accent-blue tile.

Matches the tile drawn in the app's window header (IconTile in src/main.swift).
Writes src/icon/AppIcon.png at 1024x1024, laid out on Apple's macOS icon grid
(the rounded square fills 824x824 of the canvas). scripts/build_app.sh turns
it into AppIcon.icns.

    python3 src/icon/make_icon.py
"""
from PIL import Image, ImageDraw, ImageFilter
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "AppIcon.png")

S = 4                    # supersample for smooth edges
N = 1024 * S
TILE = 824 * S           # Apple's grid: icon body is 824/1024 of the canvas
R = int(TILE * 0.2237)   # macOS squircle-ish corner radius
X0 = (N - TILE) // 2
Y0 = (N - TILE) // 2

# macOS default accent blue, lightened at the top and darkened at the bottom,
# the same blend IconTile uses on screen.
ACCENT = (0, 122, 255)
def blend(c, other, f):
    return tuple(round(a + (b - a) * f) for a, b in zip(c, other))
TOP = blend(ACCENT, (255, 255, 255), 0.22)
BOTTOM = blend(ACCENT, (0, 0, 0), 0.22)

# ----- tile with vertical gradient
grad = Image.new("RGBA", (N, N), (0, 0, 0, 0))
gd = ImageDraw.Draw(grad)
for y in range(Y0, Y0 + TILE):
    t = (y - Y0) / (TILE - 1)
    gd.line([(X0, y), (X0 + TILE, y)], fill=blend(TOP, BOTTOM, t) + (255,))
mask = Image.new("L", (N, N), 0)
ImageDraw.Draw(mask).rounded_rectangle([X0, Y0, X0 + TILE - 1, Y0 + TILE - 1], radius=R, fill=255)

# soft drop shadow beneath the tile, as macOS icons have
shadow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
sh = Image.new("L", (N, N), 0)
ImageDraw.Draw(sh).rounded_rectangle([X0, Y0 + 10 * S, X0 + TILE - 1, Y0 + TILE - 1 + 10 * S], radius=R, fill=110)
sh = sh.filter(ImageFilter.GaussianBlur(14 * S))
shadow.putalpha(sh)

icon = Image.new("RGBA", (N, N), (0, 0, 0, 0))
icon.alpha_composite(shadow)
tile = Image.new("RGBA", (N, N), (0, 0, 0, 0))
tile.paste(grad, (0, 0), mask)
icon.alpha_composite(tile)

# subtle top-edge highlight for a little depth
hl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
hd = ImageDraw.Draw(hl)
hd.rounded_rectangle([X0, Y0, X0 + TILE - 1, Y0 + TILE - 1], radius=R, outline=(255, 255, 255, 70), width=3 * S)
hl_mask = Image.new("L", (N, N), 0)
ImageDraw.Draw(hl_mask).rectangle([0, 0, N, Y0 + TILE // 2], fill=255)
hl.putalpha(Image.composite(hl.getchannel("A"), Image.new("L", (N, N), 0), hl_mask))
icon.alpha_composite(hl)

# ----- waveform: rounded vertical bars, like the SF Symbol "waveform"
heights = [0.22, 0.46, 0.78, 0.40, 1.00, 0.58, 0.86, 0.34, 0.22]
bar_w = int(TILE * 0.052)
gap = int(TILE * 0.032)
total = len(heights) * bar_w + (len(heights) - 1) * gap
max_h = TILE * 0.50
cx = N // 2
cy = N // 2
x = cx - total // 2
wave = ImageDraw.Draw(icon)
for h in heights:
    bh = int(max_h * h)
    wave.rounded_rectangle([x, cy - bh // 2, x + bar_w - 1, cy + bh // 2], radius=bar_w // 2, fill=(255, 255, 255, 255))
    x += bar_w + gap

icon = icon.resize((1024, 1024), Image.LANCZOS)
icon.save(OUT, "PNG")
print("wrote", OUT)
