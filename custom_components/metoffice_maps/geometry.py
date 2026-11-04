"""Where a map image sits on the Earth, and the box to crop around home.

Phase 0 (4 November 2026) settled the geometry of the "UK model extent" images:

- Bounds come from the file metadata, `fileDetails.file.region.extent`: x is
  longitude and y is latitude, both in degrees (-25 to 15 and 45 to 63).
- The projection is equirectangular (plate carrée): pixels are evenly spaced in
  longitude and latitude. Checked against the land_cover image: 12 known land
  and sea points (Leighton Buzzard, Birmingham, Paris, Oslo, the Irish Sea, the
  Wash and others) all fall on the right side of the coast.
- Images are 800 x 800 pixels, read from each PNG rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .const import KM_PER_DEGREE


class GeometryError(Exception):
    """The metadata does not describe a longitude/latitude extent."""


@dataclass(slots=True, frozen=True)
class Extent:
    """Geographic bounds of an image, in degrees."""

    west: float
    east: float
    south: float
    north: float

    @classmethod
    def from_metadata(cls, meta: dict[str, Any]) -> Extent:
        """Read the extent from file metadata."""
        try:
            extent = meta["fileDetails"]["file"]["region"]["extent"]
            x, y = extent["x"], extent["y"]
            if (x["label"], y["label"]) != ("longitude", "latitude"):
                raise GeometryError(f"unexpected axes {x['label']}, {y['label']}")
            if (x.get("uomLabel"), y.get("uomLabel")) != ("degree", "degree"):
                raise GeometryError("extent is not in degrees")
            result = cls(
                west=float(x["lowerBound"]),
                east=float(x["upperBound"]),
                south=float(y["lowerBound"]),
                north=float(y["upperBound"]),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise GeometryError(f"no usable extent: {err!r}") from None
        if result.west >= result.east or result.south >= result.north:
            raise GeometryError("empty extent")
        return result

    def as_dict(self) -> dict[str, float]:
        """Return the extent as a dict for storage."""
        return {"west": self.west, "east": self.east, "south": self.south, "north": self.north}


@dataclass(slots=True, frozen=True)
class FrameGeometry:
    """An equirectangular image of a known extent and size."""

    extent: Extent
    width: int
    height: int

    def to_pixel(self, lat: float, lon: float) -> tuple[float, float]:
        """Return the (x, y) pixel position of a point."""
        e = self.extent
        x = (lon - e.west) / (e.east - e.west) * self.width
        y = (e.north - lat) / (e.north - e.south) * self.height
        return x, y

    def crop_box(self, lat: float, lon: float, radius_km: float) -> tuple[int, int, int, int]:
        """Return the (left, top, right, bottom) box `radius_km` around a point.

        The box covers the same distance east-west as north-south, so it is
        not square in pixels. It is not clamped: parts outside the image come
        out transparent, which keeps home in the middle of every frame.
        """
        e = self.extent
        dlat = radius_km / KM_PER_DEGREE
        dlon = radius_km / (KM_PER_DEGREE * max(math.cos(math.radians(lat)), 0.01))
        half_w = dlon / (e.east - e.west) * self.width
        half_h = dlat / (e.north - e.south) * self.height
        x, y = self.to_pixel(lat, lon)
        return (
            round(x - half_w),
            round(y - half_h),
            max(round(x + half_w), round(x - half_w) + 1),
            max(round(y + half_h), round(y - half_h) + 1),
        )
