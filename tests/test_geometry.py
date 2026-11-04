"""Map geometry from Phase 0: bounds from metadata, equirectangular pixels."""

from __future__ import annotations

import copy

import pytest

from custom_components.metoffice_maps.geometry import Extent, FrameGeometry, GeometryError

from .helpers import HOME, HOME_PIXEL, load_fixture

UK = Extent(west=-25.0, east=15.0, south=45.0, north=63.0)


def test_extent_from_real_metadata() -> None:
    assert Extent.from_metadata(load_fixture("precip_meta.json")) == UK
    assert Extent.from_metadata(load_fixture("land_meta.json")) == UK
    assert UK.as_dict() == {"west": -25.0, "east": 15.0, "south": 45.0, "north": 63.0}


def broken(path: list[str], value: object) -> dict:
    meta = copy.deepcopy(load_fixture("precip_meta.json"))
    target = meta["fileDetails"]["file"]["region"]["extent"]
    for key in path[:-1]:
        target = target[key]
    if value is None:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return meta


@pytest.mark.parametrize(
    ("meta", "message"),
    [
        ({}, "no usable extent"),
        (broken(["x", "label"], "easting"), "unexpected axes"),
        (broken(["y", "uomLabel"], "metre"), "not in degrees"),
        (broken(["x", "lowerBound"], "west"), "no usable extent"),
        (broken(["y", "upperBound"], None), "no usable extent"),
        (broken(["x", "upperBound"], "-30.0"), "empty extent"),
    ],
)
def test_extent_errors(meta: dict, message: str) -> None:
    with pytest.raises(GeometryError, match=message):
        Extent.from_metadata(meta)


def test_home_maps_to_expected_pixel() -> None:
    x, y = FrameGeometry(UK, 800, 800).to_pixel(*HOME)
    assert (round(x), round(y)) == HOME_PIXEL
    assert FrameGeometry(UK, 800, 800).to_pixel(63, -25) == (0, 0)
    assert FrameGeometry(UK, 800, 800).to_pixel(45, 15) == (800, 800)


def test_crop_box_covers_equal_distances() -> None:
    left, top, right, bottom = FrameGeometry(UK, 800, 800).crop_box(*HOME, 150)
    # 300 km north-south is 2.7 degrees (119.8 px); east-west it is 4.43 degrees (88.5 px,
    # rounded at each edge).
    assert bottom - top == 119
    assert right - left == 88
    assert (left + right) / 2 == pytest.approx(HOME_PIXEL[0], abs=1)
    assert (top + bottom) / 2 == pytest.approx(HOME_PIXEL[1], abs=1)


def test_crop_box_at_the_edge_is_not_clamped() -> None:
    """Near the western edge the box runs off the image; the renderer pads it."""
    left, top, right, _ = FrameGeometry(UK, 800, 800).crop_box(62.5, -24.5, 150)
    assert left < 0
    assert top < 0
    assert right > 0


def test_crop_box_near_the_pole_stays_finite() -> None:
    left, _, right, _ = FrameGeometry(UK, 800, 800).crop_box(90, 0, 25)
    assert right - left > 0
