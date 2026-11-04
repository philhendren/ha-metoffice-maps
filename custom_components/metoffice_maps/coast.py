"""Land tint and coastline drawn from bundled vector data. Pure functions.

The outline comes from Natural Earth 1:10m land polygons (public domain),
clipped to the UK model extent by `scripts/build_coastline.py`. Drawing them
at several times the frame size and scaling down gives a smooth, anti-aliased
coast at any radius, unlike the model's own land mask, whose pixels are about
3 km across.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from itertools import pairwise
import json
from pathlib import Path

from PIL import Image, ImageDraw

from .geometry import Extent

LAND_FILE = Path(__file__).parent / "data" / "land.json"
LAND_TINT = (255, 255, 255, 22)
COAST_COLOUR = (255, 255, 255, 150)
COAST_WIDTH = 1.6  # in frame pixels
SUPERSAMPLE = 4

Point = tuple[float, float]


@dataclass(slots=True, frozen=True)
class Polygon:
    """One land polygon: its rings (exterior first, then holes) and coast lines."""

    rings: list[list[Point]]
    coast: list[list[Point]]
    bounds: tuple[float, float, float, float]  # west, south, east, north

    def overlaps(self, view: Extent) -> bool:
        """Return True if the polygon's bounding box overlaps the view."""
        west, south, east, north = self.bounds
        return west < view.east and east > view.west and south < view.north and north > view.south


def _coast_lines(ring: list[Point], clip: tuple[float, float, float, float]) -> list[list[Point]]:
    """Split a ring into lines, leaving out the edges made by clipping the data."""
    west, south, east, north = clip

    def on_clip(a: Point, b: Point) -> bool:
        return any(
            a[i] == b[i] == edge for i, edge in ((0, west), (0, east), (1, south), (1, north))
        )

    lines: list[list[Point]] = []
    line: list[Point] = [ring[0]]
    for a, b in pairwise(ring):
        if on_clip(a, b):
            if len(line) > 1:
                lines.append(line)
            line = [b]
        else:
            line.append(b)
    if len(line) > 1:
        lines.append(line)
    return lines


@cache
def load_land(path: Path = LAND_FILE) -> tuple[Polygon, ...]:
    """Return the bundled land polygons (blocking: read once, then cached)."""
    data = json.loads(path.read_text())
    scale = float(data["scale"])
    clip = tuple(data["clip"])
    polygons = []
    for flat_rings in data["polygons"]:
        rings = [
            [(flat[i] / scale, flat[i + 1] / scale) for i in range(0, len(flat), 2)]
            for flat in flat_rings
        ]
        lons = [lon for lon, _ in rings[0]]
        lats = [lat for _, lat in rings[0]]
        coast = [line for ring in rings for line in _coast_lines(ring, clip)]
        polygons.append(Polygon(rings, coast, (min(lons), min(lats), max(lons), max(lats))))
    return tuple(polygons)


def coast_layers(
    polygons: tuple[Polygon, ...], view: Extent, size: int
) -> tuple[Image.Image, Image.Image]:
    """Return two size x size transparent layers: a faint land tint and the coastline."""
    big = size * SUPERSAMPLE
    sx = big / (view.east - view.west)
    sy = big / (view.north - view.south)

    def px(points: list[Point]) -> list[Point]:
        return [((lon - view.west) * sx, (view.north - lat) * sy) for lon, lat in points]

    fill = Image.new("L", (big, big), 0)
    line = Image.new("L", (big, big), 0)
    draw_fill, draw_line = ImageDraw.Draw(fill), ImageDraw.Draw(line)
    width = round(COAST_WIDTH * SUPERSAMPLE)
    for polygon in polygons:
        if not polygon.overlaps(view):
            continue
        for index, ring in enumerate(polygon.rings):
            draw_fill.polygon(px(ring), fill=0 if index else 255)
        for points in polygon.coast:
            draw_line.line(px(points), fill=255, width=width, joint="curve")
    return _layer(fill, LAND_TINT, size), _layer(line, COAST_COLOUR, size)


def _layer(mask: Image.Image, colour: tuple[int, int, int, int], size: int) -> Image.Image:
    """Scale a supersampled mask down (anti-aliasing it) and colour it."""
    alpha = mask.resize((size, size), Image.Resampling.BOX).point(lambda v: v * colour[3] // 255)
    layer = Image.new("RGBA", (size, size), (*colour[:3], 0))
    layer.putalpha(alpha)
    return layer
