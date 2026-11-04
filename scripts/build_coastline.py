"""Build the bundled land outline from Natural Earth 1:10m data.

Natural Earth is public domain (https://www.naturalearthdata.com). Download
`ne_10m_land.geojson` and `ne_10m_minor_islands.geojson` (v5.1.2) from
https://github.com/nvkelso/natural-earth-vector/tree/v5.1.2/geojson, then run:

    uv run --with shapely python scripts/build_coastline.py ne_10m_land.geojson \\
        ne_10m_minor_islands.geojson

It clips the polygons to the UK model extent plus a margin, rounds coordinates
to 0.001 degrees (about 100 m) and writes
`custom_components/metoffice_maps/data/land.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from shapely.geometry import box, shape
from shapely.ops import unary_union

# UK model extent (see geometry.py) plus a margin, so clip edges stay off the maps.
WEST, EAST, SOUTH, NORTH = -25.0, 15.0, 45.0, 63.0
MARGIN = 1.0
SCALE = 1000  # coordinates are stored as integers in thousandths of a degree
OUT = Path(__file__).parent.parent / "custom_components/metoffice_maps/data/land.json"


def rings(polygon) -> list[list[int]]:
    """Return the exterior and holes as flat [lon, lat, lon, lat, ...] integer lists."""
    out = []
    for ring in [polygon.exterior, *polygon.interiors]:
        flat: list[int] = []
        for lon, lat in ring.coords:
            point = [round(lon * SCALE), round(lat * SCALE)]
            if flat[-2:] != point:
                flat += point
        if len(flat) >= 8:
            out.append(flat)
    return out


def main(paths: list[str]) -> None:
    clip = box(WEST - MARGIN, SOUTH - MARGIN, EAST + MARGIN, NORTH + MARGIN)
    shapes = [
        shape(feature["geometry"])
        for path in paths
        for feature in json.loads(Path(path).read_text())["features"]
    ]
    land = unary_union([s.intersection(clip) for s in shapes if s.intersects(clip)])
    polygons = [p for p in getattr(land, "geoms", [land]) if p.geom_type == "Polygon"]
    data = {
        "source": "Natural Earth 1:10m land and minor islands v5.1.2 (public domain)",
        "scale": SCALE,
        "clip": [WEST - MARGIN, SOUTH - MARGIN, EAST + MARGIN, NORTH + MARGIN],
        "polygons": [r for p in polygons if (r := rings(p))],
    }
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"{len(data['polygons'])} polygons, {OUT.stat().st_size // 1024} KiB -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
