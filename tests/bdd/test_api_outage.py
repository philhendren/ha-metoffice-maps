"""BDD: riding out a Met Office outage."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from pytest_bdd import given, parsers, scenarios, then

from ..helpers import FakeDataHub
from .conftest import coordinator

scenarios("api_outage.feature")


@given(parsers.parse("the Met Office answers every request with {status:d}"))
def failing(datahub: FakeDataHub, status: int) -> None:
    datahub.fail_always = status


@given("the Met Office is working again")
def working(datahub: FakeDataHub) -> None:
    datahub.fail_always = None


@given("the Met Office rejects the API key")
def rejected(datahub: FakeDataHub) -> None:
    datahub.fail_always = 401


@then(parsers.parse("the next check is in {minutes:d} minutes"))
def next_in(ctx: dict[str, Any], minutes: int) -> None:
    assert coordinator(ctx).update_interval == timedelta(minutes=minutes)


@then("Home Assistant asks for a new API key")
def asks_for_key(hass: HomeAssistant) -> None:
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
