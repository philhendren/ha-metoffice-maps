"""Turn Map Images PNGs into display-ready frames. Pure functions, no I/O.

Phase 0 found the precipitation images are already coloured: a 32-entry
palette of Met Office rain colours with per-entry transparency, where no rain
is fully transparent. So the renderer keeps those colours and only crops,
scales and composites. Each source pixel covers about 3 km, so a frame is
several times larger than the crop: the rain is scaled with a bicubic filter
and softened by about half a source pixel so the steps don't show. The land
tint and coastline come from `coast.py`.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFilter

MARKER_RING = (255, 255, 255, 255)
MARKER_EDGE = (20, 20, 20, 255)
MARKER_RADIUS = 6
SOFTEN = 0.8  # blur radius, in source pixels

Box = tuple[int, int, int, int]
Layers = tuple[Image.Image, Image.Image]


def image_size(data: bytes) -> tuple[int, int]:
    """Return the (width, height) of a PNG."""
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def scale_rain(data: bytes, box: Box, size: int) -> Image.Image:
    """Crop to the box (transparent outside the image) and scale smoothly to size x size."""
    with Image.open(io.BytesIO(data)) as img:
        rgba = img.convert("RGBA")
    # Work premultiplied so transparent pixels don't bleed dark fringes.
    cropped = rgba.crop(box).convert("RGBa")
    scaled = cropped.resize((size, size), Image.Resampling.BICUBIC)
    left, top, right, bottom = box
    zoom = size / ((right - left + bottom - top) / 2)
    if zoom > 1:
        scaled = scaled.filter(ImageFilter.GaussianBlur(SOFTEN * zoom))
    return scaled.convert("RGBA")


def render_frame(
    precip: bytes,
    box: Box,
    size: int,
    coast: Layers | None = None,
    marker: tuple[float, float] | None = None,
) -> bytes:
    """Return a size x size transparent PNG: land, rain, coastline, home marker."""
    frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rain = scale_rain(precip, box, size)
    if coast is None:
        frame.alpha_composite(rain)
    else:
        tint, outline = coast
        frame.alpha_composite(tint)
        frame.alpha_composite(rain)
        frame.alpha_composite(outline)
    if marker is not None:
        x, y = marker
        r = MARKER_RADIUS
        draw = ImageDraw.Draw(frame)
        draw.ellipse((x - r - 1, y - r - 1, x + r + 1, y + r + 1), outline=MARKER_EDGE, width=4)
        draw.ellipse((x - r, y - r, x + r, y + r), outline=MARKER_RING, width=2)
    out = io.BytesIO()
    frame.save(out, format="PNG", optimize=True)
    return out.getvalue()
