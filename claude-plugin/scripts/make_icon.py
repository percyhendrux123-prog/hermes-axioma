"""Draw the Axioma listing icon: three stacked rings (the three lights), the middle one brass.

Run with: env -u PYTHONPATH /usr/bin/python3 claude-plugin/scripts/make_icon.py
"""
import os
from PIL import Image, ImageDraw

SIZE = 1024
INK, STONE, BRASS = "#121316", "#F2EEE6", "#8C7350"
OUT = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "axioma", ".claude-plugin", "icon.png")


def main():
    scale = 4  # draw large, then shrink for clean edges
    img = Image.new("RGB", (SIZE * scale, SIZE * scale), INK)
    d = ImageDraw.Draw(img)
    cx, r, gap, line = SIZE // 2, 92, 52, 14
    top = SIZE // 2 - (3 * 2 * r + 2 * gap) // 2
    for i in range(3):
        cy = top + r + i * (2 * r + gap)
        box = [(cx - r) * scale, (cy - r) * scale, (cx + r) * scale, (cy + r) * scale]
        if i == 1:
            d.ellipse(box, fill=BRASS)
        else:
            d.ellipse(box, outline=STONE, width=line * scale)
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    img.save(OUT, optimize=True)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main()
