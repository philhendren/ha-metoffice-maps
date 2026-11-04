"""Polling within the budget, run changes, errors and restarts (all HTTP mocked)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.metoffice_maps.budget import BudgetExhausted
from custom_components.metoffice_maps.const import DOMAIN, PARAM_PRECIP
from custom_components.metoffice_maps.storage import FrameFiles

from .helpers import (
    PARAM_LAND,
    RUN_NOW,
    FakeDataHub,
    file_id,
    frame_ids,
    make_entry,
    precip_png,
    setup_entry,
)

FORECAST = "sensor.met_office_maps_o000000000001_rain_forecast"
REQUESTS = "sensor.met_office_maps_o000000000001_requests_today"
RUN_06 = datetime(2026, 11, 4, 6, tzinfo=UTC)


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float) -> None:
    freezer.tick(timedelta(minutes=minutes, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def shown(hass: HomeAssistant, entry) -> list[str]:
    return [frame.file_id for frame in entry.runtime_data.coordinator.data.frames]


def last_error(entry) -> str | None:
    return entry.runtime_data.coordinator.data.last_error


async def test_first_setup_downloads_one_run(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    # 1 listing + 1 metadata (for the extent) + 6 frames. The coastline is bundled,
    # so the order's land cover is never downloaded.
    assert datahub.requests == [
        "listing",
        f"meta:{frame_ids()[0]}",
        *(f"data:{fid}" for fid in frame_ids()),
    ]
    assert shown(hass, entry) == frame_ids()
    state = hass.states.get(FORECAST)
    assert state.state == "2026-11-04T00:00:00+00:00"
    frames = state.attributes["frames"]
    assert [f["step"] for f in frames] == [11, 12, 13, 14, 15, 16]
    assert frames[0]["valid_time"] == "2026-11-04T11:00:00+00:00"
    assert frames[0]["url"].startswith(
        f"/api/metoffice_maps/{entry.entry_id}/frame/11.png?authSig="
    )
    assert hass.states.get(REQUESTS).state == "8"
    files = FrameFiles.for_entry(hass, entry.entry_id)
    assert all(files.has_frame(fid) for fid in frame_ids())


async def test_unchanged_run_costs_one_call_per_tick(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    datahub.requests.clear()
    await tick(hass, now, 15)  # 10:20
    await tick(hass, now, 15)  # 10:35
    assert datahub.requests == ["listing", "listing"]
    assert shown(hass, entry) == frame_ids()


async def test_next_hour_downloads_one_frame(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    datahub.requests.clear()
    await tick(hass, now, 60)  # 11:05: 11:00 has passed, 17:00 joins
    assert datahub.requests == ["listing", f"data:{file_id(PARAM_PRECIP, 17, RUN_NOW)}"]
    assert shown(hass, entry) == frame_ids(first=12)


async def test_new_run_costs_one_plus_six(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    datahub.requests.clear()
    datahub.runs.append(RUN_06)
    await tick(hass, now, 15)
    assert datahub.requests == ["listing", *(f"data:{fid}" for fid in frame_ids(RUN_06, 5))]
    assert shown(hass, entry) == frame_ids(RUN_06, 5)
    assert hass.states.get(FORECAST).state == "2026-11-04T06:00:00+00:00"
    # The previous run's frames are kept; nothing older.
    files = FrameFiles.for_entry(hass, entry.entry_id)
    assert all(files.has_raw(fid) for fid in frame_ids())


async def test_partial_run_keeps_old_frames_and_refetches_only_missing(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    datahub.runs.append(RUN_06)
    new = frame_ids(RUN_06, 5)
    datahub.missing = {new[3]}
    datahub.requests.clear()
    await tick(hass, now, 15)
    # Stops at the missing step; the old run stays on show.
    assert datahub.requests == ["listing", *(f"data:{fid}" for fid in new[:4])]
    assert shown(hass, entry) == frame_ids()
    assert last_error(entry) == "incomplete_run"
    datahub.missing = set()
    datahub.requests.clear()
    await tick(hass, now, 15)
    assert datahub.requests == ["listing", *(f"data:{fid}" for fid in new[3:])]
    assert shown(hass, entry) == new
    assert last_error(entry) is None


async def test_rate_limit_backs_off_to_two_hours_then_recovers(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    coordinator = entry.runtime_data.coordinator
    datahub.fail_always = 429
    intervals = []
    for _ in range(4):
        await tick(hass, now, coordinator.update_interval.total_seconds() / 60)
        intervals.append(coordinator.update_interval)
    assert intervals == [timedelta(minutes=m) for m in (30, 60, 120, 120)]
    assert last_error(entry) == "rate_limited"
    assert shown(hass, entry) == frame_ids()  # still serving
    datahub.fail_always = None
    await tick(hass, now, 120)
    assert coordinator.update_interval == timedelta(minutes=15)
    assert last_error(entry) is None


async def test_server_error_backs_off(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    datahub.fail_next = [503]
    await tick(hass, now, 15)
    assert entry.runtime_data.coordinator.update_interval == timedelta(minutes=30)
    assert last_error(entry) == "api_error"


async def test_auth_failure_stops_polling_and_starts_reauth(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    datahub.fail_always = 401
    datahub.requests.clear()
    await tick(hass, now, 15)
    assert datahub.requests == ["listing"]
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    await tick(hass, now, 120)
    await tick(hass, now, 120)
    assert datahub.requests == ["listing"]  # no retries


async def test_auth_failure_at_setup_starts_reauth(
    hass: HomeAssistant, datahub: FakeDataHub
) -> None:
    datahub.fail_always = 403
    entry = make_entry()
    await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert [f["context"]["source"] for f in hass.config_entries.flow.async_progress()] == [
        SOURCE_REAUTH
    ]


async def test_missing_order_at_setup_is_an_entry_error(
    hass: HomeAssistant, datahub: FakeDataHub
) -> None:
    datahub.fail_next = [404]
    entry = make_entry()
    await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert datahub.requests == ["listing"]


async def test_missing_order_later_raises_a_repair_and_stops(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    datahub.fail_always = 404
    datahub.requests.clear()
    await tick(hass, now, 15)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"order_not_found_{entry.entry_id}")
    assert issue is not None
    assert last_error(entry) == "order_not_found"
    await entry.runtime_data.coordinator.async_refresh()
    await tick(hass, now, 120)
    assert datahub.requests == ["listing"]
    assert shown(hass, entry) == frame_ids()
    # Reloading clears the issue and tries again.
    datahub.fail_always = None
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"order_not_found_{entry.entry_id}") is None


async def test_cap_stops_calls_and_keeps_frames(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry(daily_cap=9)
    await setup_entry(hass, entry)
    await tick(hass, now, 15)  # 9th request
    datahub.requests.clear()
    await tick(hass, now, 15)
    await tick(hass, now, 15)
    assert datahub.requests == []
    assert last_error(entry) == "budget_exhausted"
    state = hass.states.get(REQUESTS)
    assert state.state == "9"
    assert state.attributes["budget_exhausted"] is True
    assert state.attributes["remaining"] == 0
    assert shown(hass, entry) == frame_ids()
    # 00:00 UTC resets the count and polling resumes.
    now.move_to(datetime(2026, 11, 5, 0, 1, tzinfo=UTC))
    datahub.runs.append(datetime(2026, 11, 4, 18, tzinfo=UTC))
    await tick(hass, now, 15)
    assert datahub.requests[0] == "listing"
    assert hass.states.get(REQUESTS).attributes["budget_exhausted"] is False


async def test_run_that_would_cross_the_cap_is_skipped(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry(daily_cap=14)
    await setup_entry(hass, entry)  # 9 used
    datahub.runs.append(RUN_06)
    datahub.requests.clear()
    await tick(hass, now, 15)  # listing (10), then 6 frames would make 16 > 14
    assert datahub.requests == ["listing"]
    assert last_error(entry) == "budget_reserved"
    assert shown(hass, entry) == frame_ids()


async def test_budget_exhausted_mid_poll(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    coordinator = entry.runtime_data.coordinator
    with patch.object(coordinator.client, "latest", side_effect=BudgetExhausted):
        await coordinator.async_refresh()
    assert last_error(entry) == "budget_exhausted"


async def test_no_usable_run(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    datahub.runs = [datetime(2026, 11, 3, 0, tzinfo=UTC)]  # all frames in the past
    entry = make_entry()
    await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert last_error(entry) == "no_frames"
    assert hass.states.get(FORECAST).state == "unknown"
    assert hass.states.get(FORECAST).attributes["frames"] == []


async def test_network_error_at_first_setup_still_loads(
    hass: HomeAssistant, datahub: FakeDataHub
) -> None:
    datahub.fail_next = [TimeoutError()]
    entry = make_entry()
    await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert datahub.requests == ["listing"]  # no rapid retries
    assert last_error(entry) == "api_error"


async def test_bad_metadata(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    datahub.meta = {"fileDetails": {}}
    entry = make_entry()
    await setup_entry(hass, entry)
    assert last_error(entry) == "geometry"
    assert shown(hass, entry) == []


async def test_land_cover_is_never_downloaded(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    await tick(hass, now, 15)
    assert not any(path.startswith(f"data:{PARAM_LAND}") for path in datahub.requests)
    assert file_id(PARAM_LAND, 0, RUN_NOW) in str(datahub.listing())
    assert shown(hass, entry) == frame_ids()


async def test_restart_serves_frames_on_disk_then_polls_after_jitter(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    datahub.requests.clear()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert datahub.requests == []
    assert shown(hass, entry) == frame_ids()
    assert hass.states.get(FORECAST).state == "2026-11-04T00:00:00+00:00"
    await tick(hass, now, 0.6)  # 36 s: the jittered first poll (30 s in tests)
    assert datahub.requests == ["listing"]


async def test_changed_options_rerender_without_calls(
    hass: HomeAssistant, datahub: FakeDataHub
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    files = FrameFiles.for_entry(hass, entry.entry_id)
    before = files.read_frame(frame_ids()[0])
    datahub.requests.clear()
    hass.config_entries.async_update_entry(entry, options={**entry.options, "radius_km": 300})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert datahub.requests == []
    assert files.read_frame(frame_ids()[0]) != before
    assert shown(hass, entry) == frame_ids()


async def test_new_render_version_redraws_frames_without_calls(
    hass: HomeAssistant, datahub: FakeDataHub
) -> None:
    """After an update that changes how frames look, frames on disk are drawn again."""
    entry = make_entry()
    await setup_entry(hass, entry)
    files = FrameFiles.for_entry(hass, entry.entry_id)
    before = files.read_frame(frame_ids()[0])
    datahub.requests.clear()
    with patch("custom_components.metoffice_maps.coordinator.RENDER_VERSION", 99):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        coordinator = entry.runtime_data.coordinator
        assert coordinator.render_key.endswith(",v99")
        assert coordinator.state.data["render_key"] == coordinator.render_key
    assert datahub.requests == []
    assert files.read_frame(frame_ids()[0]) is not None
    assert before is not None
    assert shown(hass, entry) == frame_ids()


async def test_changed_options_with_missing_downloads_fetch_again(
    hass: HomeAssistant, datahub: FakeDataHub
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    files = FrameFiles.for_entry(hass, entry.entry_id)
    (files.raw / f"{frame_ids()[0]}.png").unlink()
    datahub.requests.clear()
    hass.config_entries.async_update_entry(entry, options={**entry.options, "radius_km": 300})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert datahub.requests == ["listing", f"data:{frame_ids()[0]}"]
    assert shown(hass, entry) == frame_ids()


async def test_remove_entry_deletes_frames(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    files = FrameFiles.for_entry(hass, entry.entry_id)
    assert files.root.exists()
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not files.root.exists()


async def test_rain_frame_is_rendered(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    datahub.precip = precip_png()
    entry = make_entry()
    await setup_entry(hass, entry)
    body = FrameFiles.for_entry(hass, entry.entry_id).read_frame(frame_ids()[0])
    assert body is not None
    assert body.startswith(b"\x89PNG")


async def test_only_the_current_and_previous_sets_are_kept(
    hass: HomeAssistant, datahub: FakeDataHub, now: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    files = FrameFiles.for_entry(hass, entry.entry_id)
    await tick(hass, now, 60)  # 11:05: shows 12-17, keeps 11-16 as the previous set
    assert files.has_raw(frame_ids()[0])
    await tick(hass, now, 60)  # 12:05: shows 13-18, previous is 12-17, so 11 goes
    assert not files.has_raw(frame_ids()[0])
    assert not files.has_frame(frame_ids()[0])
    assert all(files.has_raw(fid) for fid in frame_ids(first=12, count=7))
