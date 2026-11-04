"""BDD: showing a new forecast run."""

from __future__ import annotations

from datetime import timedelta
import re
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_bdd import parsers, scenarios, then, when

from ..helpers import FakeDataHub, frame_ids
from .conftest import RUN_06, advance, coordinator

scenarios("new_forecast_run.feature")


@then(parsers.parse("the frames on show are valid at {times}"))
def valid_at(ctx: dict[str, Any], times: str) -> None:
    expected = re.findall(r"\d\d:\d\d", times)
    shown = [frame.valid_time.strftime("%H:%M") for frame in coordinator(ctx).data.frames]
    assert shown == expected


@when("a new run appears with its 14:00 frame missing")
def new_run_missing(hass: HomeAssistant, now: FrozenDateTimeFactory, datahub: FakeDataHub) -> None:
    datahub.runs.append(RUN_06)
    datahub.missing = {frame_ids(RUN_06, 5)[3]}  # step 8, valid 14:00
    advance(hass, now, timedelta(minutes=15))
    assert len(datahub.downloads) == 4


@when("the missing frame is published")
def published(hass: HomeAssistant, now: FrozenDateTimeFactory, datahub: FakeDataHub) -> None:
    datahub.missing = set()
    datahub.requests.clear()
    advance(hass, now, timedelta(minutes=15))


@then("only the missing frames are downloaded")
def only_missing(datahub: FakeDataHub) -> None:
    assert datahub.downloads == frame_ids(RUN_06, 5)[3:]
