"""Integration setup."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.metoffice_maps.const import DOMAIN


async def test_setup_component(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
