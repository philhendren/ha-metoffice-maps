"""Sensors and the refresh service."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest

from .helpers import FakeDataHub, make_entry, setup_entry

FORECAST = "sensor.met_office_maps_o000000000001_rain_forecast"
REQUESTS = "sensor.met_office_maps_o000000000001_requests_today"


async def test_sensor_attributes(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    entry = make_entry(daily_cap=800)
    await setup_entry(hass, entry)
    forecast = hass.states.get(FORECAST)
    assert forecast.attributes["last_checked"] == "2026-11-04T10:05:00+00:00"
    assert forecast.attributes["last_error"] is None
    assert forecast.attributes["device_class"] == "timestamp"
    requests = hass.states.get(REQUESTS)
    assert requests.state == "9"
    assert requests.attributes == {
        "cap": 800,
        "plan_limit": 1000,
        "remaining": 791,
        "budget_exhausted": False,
        "unit_of_measurement": "requests",
        "icon": "mdi:counter",
        "friendly_name": "Met Office Maps o000000000001 Requests today",
    }


async def test_sensor_before_any_check(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    datahub.fail_next = [500]
    await setup_entry(hass, make_entry())
    assert hass.states.get(FORECAST).attributes["last_checked"] is None


async def test_refresh_service_respects_the_budget(
    hass: HomeAssistant, datahub: FakeDataHub
) -> None:
    entry = make_entry(daily_cap=10)
    await setup_entry(hass, entry)
    datahub.requests.clear()
    await hass.services.async_call("metoffice_maps", "refresh", {}, blocking=True)
    assert datahub.requests == ["listing"]
    await hass.services.async_call(
        "metoffice_maps", "refresh", {"config_entry_id": entry.entry_id}, blocking=True
    )
    assert datahub.requests == ["listing"]  # the cap of 10 is reached
    assert hass.states.get(REQUESTS).attributes["budget_exhausted"] is True


async def test_refresh_service_unknown_entry(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    await setup_entry(hass, make_entry())
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "metoffice_maps", "refresh", {"config_entry_id": "nope"}, blocking=True
        )
