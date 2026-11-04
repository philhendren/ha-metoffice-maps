"""The bundled vector coastline: smooth, accurate and drawn only where it is real."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.metoffice_maps.coast import (
    COAST_COLOUR,
    LAND_TINT,
    Polygon,
    coast_layers,
    load_land,
)
from custom_components.metoffice_maps.geometry import Extent, FrameGeometry

from .helpers import HOME

UK = Extent(-25.0, 15.0, 45.0, 63.0)
SIZE = 240


def view_around(lat: float, lon: float, radius_km: float = 150) -> Extent:
    geometry = FrameGeometry(UK, 800, 800)
    return geometry.box_extent(geometry.crop_box(lat, lon, radius_km))


def test_bundled_land_covers_the_uk_model_extent() -> None:
    land = load_land()
    assert len(land) > 100
    west = min(p.bounds[0] for p in land)
    north = max(p.bounds[3] for p in land)
    assert west < -22  # reaches Iceland's south-west tip
    assert north > 62  # and the Faroes and Norway


def test_land_and_sea_fall_on_the_right_side() -> None:
    """Birmingham is land; the middle of the Bristol Channel and North Sea are not."""
    view = Extent(-6.0, 3.0, 50.0, 55.0)
    tint, outline = coast_layers(load_land(), view, SIZE)

    def at(lat: float, lon: float) -> tuple[int, int]:
        x = (lon - view.west) / (view.east - view.west) * SIZE
        y = (view.north - lat) / (view.north - view.south) * SIZE
        return round(x), round(y)

    assert tint.getpixel(at(52.48, -1.90)) == LAND_TINT  # Birmingham
    assert tint.getpixel(at(51.40, -4.20))[3] == 0  # Bristol Channel
    assert tint.getpixel(at(53.50, 2.50))[3] == 0  # North Sea
    assert outline.getpixel(at(52.48, -1.90))[3] == 0  # no coast inland


def test_coast_is_anti_aliased() -> None:
    _, outline = coast_layers(load_land(), view_around(51.9, -0.65), SIZE)
    alphas = {a for *_, a in outline.getdata() if a}
    assert COAST_COLOUR[3] in alphas
    assert any(0 < a < COAST_COLOUR[3] for a in alphas)  # soft edges, not steps


def test_far_away_polygons_are_skipped() -> None:
    view = view_around(*HOME)
    far = Polygon([[(100.0, 0.0), (101.0, 0.0), (101.0, 1.0), (100.0, 0.0)]], [], (100, 0, 101, 1))
    assert not far.overlaps(view)
    tint, outline = coast_layers((far,), view, SIZE)
    assert tint.getbbox() is None
    assert outline.getbbox() is None


def test_holes_are_not_tinted(tmp_path: Path) -> None:
    square = [-10_000, 40_000, 10_000, 40_000, 10_000, 60_000, -10_000, 60_000, -10_000, 40_000]
    hole = [-1_000, 49_000, 1_000, 49_000, 1_000, 51_000, -1_000, 51_000, -1_000, 49_000]
    path = tmp_path / "land.json"
    path.write_text(
        json.dumps({"scale": 1000, "clip": [-30, 40, 30, 70], "polygons": [[square, hole]]})
    )
    view = Extent(-2.0, 2.0, 48.0, 52.0)
    tint, _ = coast_layers(load_land(path), view, 40)
    assert tint.getpixel((20, 20))[3] == 0  # the lake
    assert tint.getpixel((2, 2)) == LAND_TINT


def test_clip_edges_are_not_drawn_as_coast(tmp_path: Path) -> None:
    """Where the data was cut at its clip box there is no real coast to draw."""
    # Land west of 0 degrees, cut by the clip box at 60N; the real coast is at 0E.
    ring = [-10_000, 50_000, 0, 50_000, 0, 60_000, -10_000, 60_000, -10_000, 50_000]
    path = tmp_path / "land.json"
    path.write_text(json.dumps({"scale": 1000, "clip": [-10, 40, 10, 60], "polygons": [[ring]]}))
    (polygon,) = load_land(path)
    assert polygon.coast == [
        [(-10.0, 50.0), (0.0, 50.0), (0.0, 60.0)],
    ]
    _, outline = coast_layers((polygon,), Extent(-4.0, 4.0, 56.0, 64.0), 80)
    assert outline.getpixel((20, 40))[3] == 0  # along 60N, west of the coast
    assert outline.getpixel((40, 60))[3] > 0  # the real coast at 0E


def test_ring_starting_on_the_clip_edge(tmp_path: Path) -> None:
    ring = [-10_000, 60_000, -10_000, 50_000, 0, 50_000, 0, 60_000, -10_000, 60_000]
    path = tmp_path / "land.json"
    path.write_text(json.dumps({"scale": 1000, "clip": [-10, 40, 10, 60], "polygons": [[ring]]}))
    (polygon,) = load_land(path)
    assert polygon.coast == [[(-10.0, 50.0), (0.0, 50.0), (0.0, 60.0)]]
