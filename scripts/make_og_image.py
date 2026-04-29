"""Generate the Open Graph thumbnail (1200x630 PNG) for discourse-lens.

Run: python scripts/make_og_image.py
Output: web/public/og-image.png
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "public" / "og-image.png"

W, H = 1200, 630
BG = (250, 250, 247)
FG = (17, 24, 39)
MUTED = (107, 114, 128)
LS = (37, 99, 235)
ET = (217, 119, 6)
LINE = (229, 231, 235)


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        f"C:/Windows/Fonts/{name}",
        f"/usr/share/fonts/truetype/dejavu/{name.replace('arial', 'DejaVuSans')}",
        f"/System/Library/Fonts/{name}",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def draw_cluster(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple,
                 label: str, font_label):
    """A small abstract cluster — circle nodes with edges + a label above."""
    rng = random.Random(hash(label))
    n_nodes = 13
    points = []
    for _ in range(n_nodes):
        angle = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(22, 120)
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

    # Edges first (under nodes)
    for i in range(n_nodes):
        for j in range(i + 1, n_nodes):
            if rng.random() < 0.20:
                draw.line([points[i], points[j]], fill=(*color, 80), width=1)

    # Nodes
    for x, y in points:
        size = rng.choice([7, 9, 11, 13])
        draw.ellipse([x - size, y - size, x + size, y + size],
                     fill=color, outline=BG, width=2)

    # Label badge ABOVE the cluster (clear of footer line)
    bbox = draw.textbbox((0, 0), label, font=font_label)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad_x, pad_y = 14, 6
    bx = cx - tw / 2 - pad_x
    by = cy - 175
    draw.rounded_rectangle([bx, by, bx + tw + 2 * pad_x, by + th + 2 * pad_y],
                           radius=14, fill=color)
    draw.text((cx - tw / 2, by + pad_y - 2), label, fill=BG, font=font_label)


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")

    title_font = load_font("arialbd.ttf", 86)
    subtitle_font = load_font("arial.ttf", 36)
    body_font = load_font("arial.ttf", 26)
    small_font = load_font("arial.ttf", 22)
    chip_font = load_font("arialbd.ttf", 22)

    # Header
    draw.text((72, 64), "discourse-lens", fill=FG, font=title_font)
    draw.text((76, 168), "Learning Sciences  ×  Educational Technology",
              fill=MUTED, font=subtitle_font)

    # Two side-by-side clusters
    draw.line([(W / 2, 270), (W / 2, 478)], fill=LINE, width=1)
    draw_cluster(draw, 320, 388, LS, "LS — Learning Sciences", chip_font)
    draw_cluster(draw, 880, 388, ET, "ET — Educational Technology", chip_font)

    # Footer line
    draw.line([(72, H - 110), (W - 72, H - 110)], fill=LINE, width=1)
    draw.text((72, H - 88),
              "1,545 abstracts  ·  9 flagship journals  ·  2015–2025",
              fill=FG, font=body_font)
    draw.text((72, H - 50),
              "8 LLM-tagged discourse threads  ·  bootstrap CI  ·  BERTopic validity",
              fill=MUTED, font=small_font)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT}  ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
