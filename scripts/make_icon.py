"""Draw the brand icon: a raindrop over rain bands. Not the Met Office logo."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path("custom_components/metoffice_maps/brand")


def icon(size: int) -> Image.Image:
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = big // 16
    draw.rounded_rectangle((pad, pad, big - pad, big - pad), radius=big // 5, fill=(18, 52, 86))
    bands = [(0.70, (46, 160, 220)), (0.80, (80, 200, 120)), (0.90, (250, 200, 60))]
    for top, colour in bands:
        y = int(big * top)
        draw.rounded_rectangle(
            (pad * 2, y - big // 30, big - pad * 2, y + big // 30), radius=big // 30, fill=colour
        )
    cx, r = big // 2, big // 7
    cy = int(big * 0.47)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255))
    draw.polygon(
        [(cx - r * 0.93, cy - r * 0.37), (cx, cy - r * 2.3), (cx + r * 0.93, cy - r * 0.37)],
        fill=(255, 255, 255),
    )
    return img.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    icon(256).save(OUT / "icon.png", optimize=True)
    icon(512).save(OUT / "icon@2x.png", optimize=True)
