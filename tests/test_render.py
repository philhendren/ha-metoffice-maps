"""Rendering frames: crop, scale, rain colours, coastline and home marker."""

from __future__ import annotations

import io

from PIL import Image

from custom_components.metoffice_maps.coast import LAND_TINT, Polygon, coast_layers
from custom_components.metoffice_maps.geometry import Extent, FrameGeometry
from custom_components.metoffice_maps.render import image_size, render_frame, scale_rain

from .helpers import HOME, HOME_PIXEL, RAIN_HEAVY, RAIN_LIGHT, precip_png

UK = Extent(-25.0, 15.0, 45.0, 63.0)
SIZE = 240
BOX = FrameGeometry(UK, 800, 800).crop_box(*HOME, 150)


def same_colour(actual: tuple[int, ...], expected: tuple[int, ...]) -> bool:
    """Equal within 1 per channel: the premultiplied resize rounds alpha-254 pixels."""
    return all(abs(a - e) <= 1 for a, e in zip(actual, expected, strict=True))


def open_png(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    assert img.mode == "RGBA"
    assert img.size == (SIZE, SIZE)
    return img


def test_image_size() -> None:
    assert image_size(precip_png()) == (800, 800)


def test_rain_keeps_met_office_colours_and_no_rain_is_transparent() -> None:
    img = open_png(render_frame(precip_png(), BOX, SIZE))
    # The heavy-rain patch is centred on home, so the middle of the frame shows it.
    assert same_colour(img.getpixel((SIZE // 2, SIZE // 2)), (*RAIN_HEAVY, 254))
    assert img.getpixel((5, 5)) == (0, 0, 0, 0)


def test_light_rain_patch() -> None:
    x, y = HOME_PIXEL
    data = precip_png([((x - 40, y - 50, x - 20, y - 30), 1)])
    img = open_png(render_frame(data, BOX, SIZE))
    left, top, right, bottom = BOX
    px = round((x - 30 - left) / (right - left) * SIZE)
    py = round((y - 40 - top) / (bottom - top) * SIZE)
    assert same_colour(img.getpixel((px, py)), (*RAIN_LIGHT, 254))
    assert img.getpixel((SIZE // 2, SIZE // 2))[3] == 0


def test_outside_the_model_extent_is_transparent() -> None:
    box = FrameGeometry(UK, 800, 800).crop_box(62.9, -24.9, 150)
    data = precip_png([((0, 0, 800, 800), 1)])  # rain everywhere on the image
    img = open_png(render_frame(data, box, SIZE))
    assert img.getpixel((2, 2)) == (0, 0, 0, 0)  # off the image, north-west
    assert same_colour(img.getpixel((SIZE - 2, SIZE - 2)), (*RAIN_LIGHT, 254))


def test_rain_edges_are_smoothed_not_stepped() -> None:
    """A rain patch fades over a few pixels at its edge instead of a hard step."""
    x, y = HOME_PIXEL
    data = precip_png([((x - 30, y - 30, x + 30, y + 30), 2)])
    rain = scale_rain(data, BOX, SIZE)
    row = [rain.getpixel((px, SIZE // 2))[3] for px in range(SIZE)]
    partial = [a for a in row if 0 < a < 250]
    assert len(partial) >= 4  # a soft edge on each side
    assert max(row) >= 253


def test_no_softening_when_the_frame_is_smaller_than_the_crop() -> None:
    x, y = HOME_PIXEL
    data = precip_png([((x - 30, y - 30, x + 30, y + 30), 2)])
    rain = scale_rain(data, BOX, 40)
    assert rain.size == (40, 40)
    assert same_colour(rain.getpixel((20, 20)), (*RAIN_HEAVY, 254))


def east_of(lon: float) -> tuple[Polygon, ...]:
    """A land square from the view's west edge to `lon`, with sea to the east."""
    ring = [(-10.0, 40.0), (lon, 40.0), (lon, 60.0), (-10.0, 60.0), (-10.0, 40.0)]
    return (Polygon([ring], [ring], (-10.0, 40.0, lon, 60.0)),)


def test_frame_layers_coastline_over_rain_and_marker_on_top() -> None:
    x, y = HOME_PIXEL
    view = FrameGeometry(UK, 800, 800).box_extent(BOX)
    left, _, right, _ = BOX
    # The coast runs north-south 40 source pixels east of home, inside the rain patch.
    coast_x = round((x + 40 - left) / (right - left) * SIZE)
    coast_lon = view.west + coast_x / SIZE * (view.east - view.west)
    data = precip_png([((x + 20, y - 60, x + 80, y + 60), 2)])  # rain over the coast
    layers = coast_layers(east_of(coast_lon), view, SIZE)
    img = open_png(render_frame(data, BOX, SIZE, layers, (SIZE / 2, SIZE / 2)))
    row = SIZE // 2 + 30
    edge = [
        px
        for px in range(coast_x - 3, coast_x + 4)
        if not same_colour(img.getpixel((px, row))[:3], RAIN_HEAVY)
    ]
    assert edge  # the outline shows over the rain
    assert img.getpixel((5, row))[3] == LAND_TINT[3]  # dry land is tinted
    # Home marker: a white ring with a dark edge around the centre.
    ring = img.getpixel((SIZE // 2 + 6, SIZE // 2))
    assert ring == (255, 255, 255, 255)
    assert img.getpixel((SIZE // 2 + 7, SIZE // 2))[:3] == (20, 20, 20)
