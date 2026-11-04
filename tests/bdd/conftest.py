"""Shared BDD steps.

pytest-bdd steps are synchronous, so each step drives Home Assistant's event
loop with `run(...)`. All HTTP goes to the fake DataHub; time is frozen at
10:05 UTC on 4 November 2026, when the newest run is midnight (00:00 UTC).
"""

from __future__ import annotations

from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_bdd import given, parsers, then, when
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.metoffice_maps.budget import async_get_budget

from ..helpers import ORDER_ID, FakeDataHub, frame_ids, make_entry, setup_entry

FORECAST = "sensor.met_office_maps_o000000000001_rain_forecast"
REQUESTS = "sensor.met_office_maps_o000000000001_requests_today"
RUN_06 = datetime(2026, 11, 4, 6, tzinfo=UTC)


def run(hass: HomeAssistant, coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine on Home Assistant's loop from a synchronous step."""
    return hass.loop.run_until_complete(coro)


def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    """Move the clock on and let due polls run."""
    freezer.tick(delta + timedelta(seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    run(hass, hass.async_block_till_done(wait_background_tasks=True))


@pytest.fixture
def ctx() -> dict[str, Any]:
    """Scenario state shared between steps."""
    return {}


def coordinator(ctx: dict[str, Any]):
    return ctx["entry"].runtime_data.coordinator


@given("the forecast is showing the midnight run")
def showing_midnight(hass: HomeAssistant, ctx: dict[str, Any], datahub: FakeDataHub) -> None:
    ctx["entry"] = make_entry(**ctx.get("options", {}))
    run(hass, setup_entry(hass, ctx["entry"]))
    assert [frame.file_id for frame in coordinator(ctx).data.frames] == frame_ids()
    datahub.requests.clear()


@given(parsers.parse("the daily cap is {cap:d} requests"))
def daily_cap(hass: HomeAssistant, ctx: dict[str, Any], cap: int) -> None:
    coordinator(ctx).budget.cap = cap


@given(parsers.parse("{count:d} requests have been made today"))
def requests_made(hass: HomeAssistant, ctx: dict[str, Any], count: int) -> None:
    budget = run(hass, async_get_budget(hass, ORDER_ID))
    budget._count = count
    assert budget.used == count


@when("a new run appears")
def new_run(hass: HomeAssistant, now: FrozenDateTimeFactory, datahub: FakeDataHub) -> None:
    if RUN_06 not in datahub.runs:
        datahub.runs.append(RUN_06)
    advance(hass, now, timedelta(minutes=15))


@when("a quarter of an hour passes")
def quarter_hour(hass: HomeAssistant, now: FrozenDateTimeFactory) -> None:
    advance(hass, now, timedelta(minutes=15))


@when("an hour passes")
def an_hour(hass: HomeAssistant, now: FrozenDateTimeFactory) -> None:
    for _ in range(4):
        advance(hass, now, timedelta(minutes=15))


@when("four hours pass")
def four_hours(hass: HomeAssistant, now: FrozenDateTimeFactory) -> None:
    for _ in range(2):
        advance(hass, now, timedelta(hours=2))


@when("the clock passes midnight UTC")
def past_midnight(hass: HomeAssistant, now: FrozenDateTimeFactory) -> None:
    now.move_to(datetime(2026, 11, 5, 0, 1, tzinfo=UTC))


@when("the next check is due")
def next_check(hass: HomeAssistant, ctx: dict[str, Any], now: FrozenDateTimeFactory) -> None:
    advance(hass, now, coordinator(ctx).update_interval)


@then("no frames are downloaded")
def no_downloads(datahub: FakeDataHub) -> None:
    assert datahub.downloads == []


@then("six frames are downloaded")
def six_downloads(datahub: FakeDataHub) -> None:
    assert len(datahub.downloads) == 6


@then("no requests are made")
def no_requests(datahub: FakeDataHub) -> None:
    assert datahub.requests == []


@then(parsers.parse("exactly {count:d} request is made"))
def exactly(datahub: FakeDataHub, count: int) -> None:
    assert len(datahub.requests) == count


@then(parsers.parse("{count:d} requests have been made today"))
def made_today(hass: HomeAssistant, count: int) -> None:
    assert run(hass, async_get_budget(hass, ORDER_ID)).used == count


@then("the midnight run's frames stay on show")
def midnight_frames(ctx: dict[str, Any]) -> None:
    assert [frame.file_id for frame in coordinator(ctx).data.frames] == frame_ids()


@then("the requests sensor says the budget is exhausted")
def exhausted(hass: HomeAssistant) -> None:
    assert hass.states.get(REQUESTS).attributes["budget_exhausted"] is True


@then(parsers.parse("the forecast sensor shows the {hour} run"))
def forecast_run(hass: HomeAssistant, hour: str) -> None:
    assert hass.states.get(FORECAST).state == f"2026-11-04T{hour}:00+00:00"
