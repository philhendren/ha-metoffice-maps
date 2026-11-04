"""The Map Images client."""

from __future__ import annotations

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest

from custom_components.metoffice_maps.api import (
    ApiError,
    AuthError,
    MapImagesClient,
    NotFound,
    RateLimited,
)
from custom_components.metoffice_maps.budget import Budget, BudgetExhausted

from .helpers import API_KEY, ORDER_ID, FakeDataHub


async def client(hass: HomeAssistant, cap: int = 800, order: str = ORDER_ID) -> MapImagesClient:
    budget = Budget(hass, order, cap)
    await budget.async_load()
    return MapImagesClient(async_get_clientsession(hass), API_KEY, order, budget)


async def test_calls_and_headers(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    api = await client(hass)
    listing = await api.latest()
    assert listing["orderDetails"]["files"]
    meta = await api.file_meta("land_cover_ts0_+00")
    assert meta["fileDetails"]["file"]["region"]["name"] == "UK model extent"
    data = await api.file_data("total_precipitation_rate_ts1_2026110400")
    assert data.startswith(b"\x89PNG")
    assert datahub.requests == [
        "listing",
        "meta:land_cover_ts0_+00",
        "data:total_precipitation_rate_ts1_2026110400",
    ]
    headers = datahub.headers()
    assert all(h["apikey"] == API_KEY for h in headers)
    assert [h["Accept"] for h in headers] == [
        "application/json",
        "application/json",
        "application/octet-stream",
    ]
    # `+` in a fileId is percent-encoded, as Phase 0 confirmed the API needs.
    assert "land_cover_ts0_%2B00" in str(datahub.mock.mock_calls[1][1])
    assert api.budget.used == 3


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (401, AuthError),
        (403, AuthError),
        (404, NotFound),
        (429, RateLimited),
        (500, ApiError),
        (503, ApiError),
        (400, ApiError),
        (TimeoutError(), ApiError),
        (aiohttp.ClientConnectionError(), ApiError),
    ],
)
async def test_errors_are_typed_and_counted(
    hass: HomeAssistant, datahub: FakeDataHub, failure, error
) -> None:
    api = await client(hass)
    datahub.fail_next = [failure]
    with pytest.raises(error) as raised:
        await api.latest()
    assert type(raised.value) is error
    assert api.budget.used == 1


async def test_unknown_order_is_not_found(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    api = await client(hass, order="o999")
    with pytest.raises(NotFound, match="listing: 404"):
        await api.latest()


async def test_no_call_past_the_cap(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    api = await client(hass, cap=1)
    await api.latest()
    with pytest.raises(BudgetExhausted):
        await api.latest()
    assert datahub.listings == 1


async def test_network_error_message(hass: HomeAssistant, datahub: FakeDataHub) -> None:
    api = await client(hass)
    datahub.fail_next = [TimeoutError()]
    with pytest.raises(ApiError, match="listing: no response") as raised:
        await api.latest()
    assert raised.value.status is None
