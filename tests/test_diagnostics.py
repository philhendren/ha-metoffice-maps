"""Diagnostics, and keeping the API key private."""

from __future__ import annotations

import json
import logging

from homeassistant.core import HomeAssistant
import pytest

from custom_components.metoffice_maps.diagnostics import async_get_config_entry_diagnostics

from .helpers import API_KEY, FakeDataHub, make_entry, setup_entry


async def test_diagnostics_redact_the_key(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"]["api_key"] == "**REDACTED**"
    assert diag["entry"]["data"]["order_id"] == "o000000000001"
    assert diag["budget"] == {"used": 8, "cap": 800, "remaining": 792, "exhausted": False}
    coordinator = diag["coordinator"]
    assert coordinator["listing"]["runs"] == [
        "2026-11-03T12:00:00+00:00",
        "2026-11-04T00:00:00+00:00",
    ]
    assert coordinator["extent"] == {"west": -25.0, "east": 15.0, "south": 45.0, "north": 63.0}
    assert len(coordinator["frames"]) == 6
    assert coordinator["halted"] is False
    assert API_KEY not in json.dumps(diag, default=str)


async def test_key_never_appears_in_logs_attributes_or_diagnostics(
    hass: HomeAssistant, datahub: FakeDataHub, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    entry = make_entry()
    await setup_entry(hass, entry)
    datahub.fail_always = 500
    await entry.runtime_data.coordinator.async_refresh()
    datahub.fail_always = TimeoutError()
    await entry.runtime_data.coordinator.async_refresh()
    datahub.fail_always = 401
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "listing: 500" in caplog.text
    assert API_KEY not in caplog.text
    for state in hass.states.async_all():
        assert API_KEY not in json.dumps(state.as_dict(), default=str)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert API_KEY not in json.dumps(diag, default=str)
