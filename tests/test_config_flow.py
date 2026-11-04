"""Config, options and re-auth flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.metoffice_maps.budget import async_get_budget
from custom_components.metoffice_maps.const import DOMAIN

from .helpers import API_KEY, ORDER_ID, FakeDataHub, make_entry, setup_entry


async def start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_happy_path_uses_exactly_one_call(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        # The portal shows the ID with a capital O; the API needs lower case.
        {"api_key": f" {API_KEY} ", "order_id": " O000000000001 "},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Met Office Maps o000000000001"
    assert result["data"] == {"api_key": API_KEY, "order_id": ORDER_ID}
    assert result["options"]["daily_cap"] == 800
    assert result["result"].unique_id == ORDER_ID
    assert datahub.requests[0] == "listing"
    await hass.async_block_till_done(wait_background_tasks=True)
    # The validation call counted against the same budget the entry then used.
    assert (await async_get_budget(hass, ORDER_ID)).used == len(datahub.requests)


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (401, "invalid_auth"),
        (403, "invalid_auth"),
        (404, "order_not_found"),
        (TimeoutError(), "cannot_connect"),
        (500, "cannot_connect"),
    ],
)
async def test_errors(hass: HomeAssistant, datahub: FakeDataHub, failure, error: str) -> None:
    datahub.fail_next = [failure]
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "wrong", "order_id": ORDER_ID}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert datahub.requests == ["listing"]


async def test_budget_exhausted(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    budget = await async_get_budget(hass, ORDER_ID)
    budget.cap = 0
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": API_KEY, "order_id": ORDER_ID}
    )
    assert result["errors"] == {"base": "budget_exhausted"}
    assert datahub.requests == []


async def test_duplicate_order_is_aborted(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    make_entry().add_to_hass(hass)
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": API_KEY, "order_id": ORDER_ID.upper()}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert datahub.requests == []


async def test_options(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    defaults = {str(key): key.description["suggested_value"] for key in schema}
    assert defaults["latitude"] == 51.9
    assert defaults["radius_km"] == 150
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "latitude": 52.2,
            "longitude": 0.12,
            "radius_km": 200.0,
            "frames": 4.0,
            "daily_cap": 600.0,
            "poll_minutes": 20.0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "latitude": 52.2,
        "longitude": 0.12,
        "radius_km": 200,
        "frames": 4,
        "daily_cap": 600,
        "poll_minutes": 20,
    }
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data.coordinator
    assert coordinator.frame_count == 4
    assert coordinator.budget.cap == 600
    assert coordinator.latitude == 52.2


async def test_reauth(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    entry = make_entry()
    await setup_entry(hass, entry)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    datahub.fail_next = [401]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "still-wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_key"] == "new-key"
    # The entry reloads in the background; let it finish inside the test.
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.coordinator.client._api_key == "new-key"
