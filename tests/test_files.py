"""Parsing fileIds and choosing frames."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.metoffice_maps.files import (
    MapFile,
    listing_summary,
    parse_file_id,
    parse_listing,
    select_frames,
)

from .helpers import NOW, RUN_NOW, RUN_PREV, file_id, load_fixture


def test_parse_dated_file_id() -> None:
    item = parse_file_id("total_precipitation_rate_ts3_2026110400")
    assert item == MapFile(
        "total_precipitation_rate_ts3_2026110400",
        "total_precipitation_rate",
        3,
        datetime(2026, 11, 4, 0, tzinfo=UTC),
    )
    assert item.valid_time == datetime(2026, 11, 4, 3, tzinfo=UTC)


def test_valid_time_crosses_midnight_in_utc() -> None:
    item = parse_file_id("total_precipitation_rate_ts14_2026110312")
    assert item is not None
    assert item.valid_time == datetime(2026, 11, 4, 2, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [
        "total_precipitation_rate_ts3_+00",  # alias by run hour
        "land_cover_ts0_+12",
        "total_precipitation_rate_ts3_2026139900",  # not a date
        "total_precipitation_rate_2026110400",
        "",
    ],
)
def test_parse_ignores_aliases_and_junk(value: str) -> None:
    assert parse_file_id(value) is None


def test_parse_real_listing_fixture() -> None:
    listing = load_fixture("latest.json")
    files = parse_listing(listing)
    # Half the entries are `+00` / `+12` aliases.
    assert len(files) == len(listing["orderDetails"]["files"]) // 2
    assert {item.parameter for item in files} == {
        "total_precipitation_rate",
        "land_cover",
        "cloud_amount_total",
    }
    summary = listing_summary(listing)
    assert summary["files"] == 208
    assert summary["runs"] == ["2026-11-03T12:00:00+00:00", "2026-11-04T00:00:00+00:00"]


def test_parse_empty_listing() -> None:
    assert parse_listing({}) == []
    assert listing_summary({}) == {"files": 0, "parameters": [], "runs": []}


def files_for(run: datetime, steps: range, parameter: str = "total_precipitation_rate"):
    return [MapFile(file_id(parameter, s, run), parameter, s, run) for s in steps]


def test_select_next_hours_from_newest_run() -> None:
    files = files_for(RUN_PREV, range(25)) + files_for(RUN_NOW, range(25))
    files += files_for(RUN_NOW, range(25), "land_cover") + files_for(RUN_NOW, range(3), "cloud")
    selection = select_frames(files, NOW, 6)
    assert selection is not None
    assert selection.run == RUN_NOW
    # 10:05 now: the next six whole hours are 11:00 to 16:00, steps 11 to 16.
    assert [item.step for item in selection.frames] == [11, 12, 13, 14, 15, 16]


def test_select_falls_back_to_older_complete_run() -> None:
    """The newest run stops at step 13 (still publishing): use the 12Z run."""
    files = files_for(RUN_PREV, range(37)) + files_for(RUN_NOW, range(14))
    selection = select_frames(files, NOW, 6)
    assert selection is not None
    assert selection.run == RUN_PREV
    assert [item.step for item in selection.frames] == [23, 24, 25, 26, 27, 28]
    assert [item.valid_time.hour for item in selection.frames] == [11, 12, 13, 14, 15, 16]


def test_select_none_when_no_run_covers_the_hours() -> None:
    assert select_frames(files_for(RUN_NOW, range(14)), NOW, 6) is None
    assert select_frames([], NOW, 6) is None
