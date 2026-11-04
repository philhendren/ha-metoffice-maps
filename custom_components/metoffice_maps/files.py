"""Parse fileIds from an order listing and pick the frames to show.

A fileId looks like `total_precipitation_rate_ts3_2026110400`: the parameter,
the forecast step in hours, and the model run time (UTC, YYYYMMDDHH). The
listing also carries aliases such as `total_precipitation_rate_ts3_+00` that
name the same file by run hour only; those are ignored.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any

from .const import PARAM_PRECIP

FILE_ID = re.compile(r"^(?P<parameter>[a-z0-9_]+?)_ts(?P<step>\d+)_(?P<run>\d{10})$")


@dataclass(slots=True, frozen=True)
class MapFile:
    """One file in an order."""

    file_id: str
    parameter: str
    step: int
    run: datetime

    @property
    def valid_time(self) -> datetime:
        """Return when this frame is valid: run time plus step."""
        return self.run + timedelta(hours=self.step)


@dataclass(slots=True, frozen=True)
class Selection:
    """The frames to show."""

    run: datetime
    frames: list[MapFile]


def parse_file_id(file_id: str) -> MapFile | None:
    """Return the parsed fileId, or None for aliases and unknown shapes."""
    if not (match := FILE_ID.match(file_id)):
        return None
    try:
        run = datetime.strptime(match["run"], "%Y%m%d%H").replace(tzinfo=UTC)
    except ValueError:
        return None
    return MapFile(file_id, match["parameter"], int(match["step"]), run)


def parse_listing(listing: dict[str, Any]) -> list[MapFile]:
    """Return every parseable file in a listing."""
    files = listing.get("orderDetails", {}).get("files", [])
    parsed = (parse_file_id(str(entry.get("fileId", ""))) for entry in files)
    return [item for item in parsed if item is not None]


def select_frames(files: list[MapFile], now: datetime, count: int) -> Selection | None:
    """Pick the next `count` precipitation frames after `now`.

    The newest run that covers all of them wins; if it is missing any (for
    example while it is still being published), an older complete run is used.
    """
    runs: dict[datetime, list[MapFile]] = defaultdict(list)
    for item in files:
        if item.parameter == PARAM_PRECIP:
            runs[item.run].append(item)
    for run in sorted(runs, reverse=True):
        upcoming = sorted(
            (item for item in runs[run] if item.valid_time > now), key=lambda item: item.step
        )
        if len(upcoming) >= count:
            return Selection(run, upcoming[:count])
    return None


def listing_summary(listing: dict[str, Any]) -> dict[str, Any]:
    """Return a short description of a listing, for diagnostics."""
    files = parse_listing(listing)
    return {
        "files": len(listing.get("orderDetails", {}).get("files", [])),
        "parameters": sorted({item.parameter for item in files}),
        "runs": sorted({item.run.isoformat() for item in files}),
    }
