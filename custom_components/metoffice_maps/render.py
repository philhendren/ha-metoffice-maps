"""Turn Map Images PNGs into display-ready frames. Pure functions, no I/O.

Phase 0 found the precipitation images are already coloured: a 32-entry
palette of Met Office rain colours with per-entry transparency, where no rain
is fully transparent. So the renderer keeps those colours and only crops,
scales and composites. The land_cover image is a green land mask on a
transparent sea; it becomes a faint land tint and a coastline outline.
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageDraw, ImageFilter

LAND_TINT = (255, 255, 255, 22)
COAST_COLOUR = (255, 255, 255, 150)
MARKER_RING = (255, 255, 255, 255)
MARKER_EDGE = (20, 20, 20, 255)
MARKER_RADIUS = 6
LAND_THRESHOLD = 128

Box = tuple[int, int, int, int]


def image_size(data: bytes) -> tuple[int, int]:
    """Return the (width, height) of a PNG."""
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def _crop_scale(data: bytes, box: Box, size: int) -> Image.Image:
    """Crop to the box (transparent outside the image) and scale to size x size."""
    with Image.open(io.BytesIO(data)) as img:
        rgba = img.convert("RGBA")
    # Resize premultiplied so transparent pixels don't bleed dark fringes.
    cropped = rgba.crop(box).convert("RGBa")
    return cropped.resize((size, size), Image.Resampling.BILINEAR).convert("RGBA")


def coast_layers(land: bytes, box: Box, size: int) -> tuple[Image.Image, Image.Image]:
    """Return two transparent layers: a faint land tint and the coastline outline."""
    mask = (
        _crop_scale(land, box, size)
        .getchannel("A")
        .point(lambda a: 255 if a >= LAND_THRESHOLD else 0)
    )
    edge = ImageChops.subtract(
        mask.filter(ImageFilter.MaxFilter(3)), mask.filter(ImageFilter.MinFilter(3))
    )
    blank = (0, 0, 0, 0)
    tint = Image.new("RGBA", (size, size), blank)
    tint.paste(Image.new("RGBA", (size, size), LAND_TINT), mask=mask)
    outline = Image.new("RGBA", (size, size), blank)
    outline.paste(Image.new("RGBA", (size, size), COAST_COLOUR), mask=edge)
    return tint, outline


def render_frame(
    precip: bytes,
    box: Box,
    size: int,
    land: bytes | None = None,
    marker: tuple[float, float] | None = None,
) -> bytes:
    """Return a size x size transparent PNG: land, rain, coastline, home marker."""
    frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rain = _crop_scale(precip, box, size)
    if land is None:
        frame.alpha_composite(rain)
    else:
        tint, outline = coast_layers(land, box, size)
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
