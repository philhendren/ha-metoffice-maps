"""Met Office Maps: a 6-hour UK rain forecast for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
import random

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType

from .api import MapImagesClient
from .budget import async_get_budget
from .const import (
    CONF_DAILY_CAP,
    CONF_ORDER_ID,
    DEFAULT_DAILY_CAP,
    DOMAIN,
    STARTUP_JITTER_SECONDS,
)
from .coordinator import MetOfficeMapsCoordinator
from .http import FramesJsonView, FrameView
from .services import async_register_services
from .storage import FrameFiles, OrderState

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class MetOfficeMapsRuntime:
    """Objects that live as long as a loaded order."""

    coordinator: MetOfficeMapsCoordinator


type MetOfficeMapsConfigEntry = ConfigEntry[MetOfficeMapsRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the parts shared by every order."""
    hass.http.register_view(FrameView(hass))
    hass.http.register_view(FramesJsonView(hass))
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MetOfficeMapsConfigEntry) -> bool:
    """Set up one order: serve frames on disk now, poll after a short jitter."""
    order_id = entry.data[CONF_ORDER_ID]
    budget = await async_get_budget(hass, order_id)
    budget.cap = int(entry.options.get(CONF_DAILY_CAP, DEFAULT_DAILY_CAP))
    client = MapImagesClient(
        async_get_clientsession(hass), entry.data[CONF_API_KEY], order_id, budget
    )
    files = FrameFiles.for_entry(hass, entry.entry_id)
    coordinator = MetOfficeMapsCoordinator(
        hass, entry, client, files, OrderState(hass, entry.entry_id)
    )
    ir.async_delete_issue(hass, DOMAIN, coordinator.issue_id)
    if await coordinator.async_restore():

        @callback
        def _first_poll(_now: object) -> None:
            hass.async_create_task(coordinator.async_refresh())

        # Restarts don't all poll at once; the frames on disk are served meanwhile.
        entry.async_on_unload(
            async_call_later(hass, random.uniform(0, STARTUP_JITTER_SECONDS), _first_poll)
        )
    else:
        await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = MetOfficeMapsRuntime(coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MetOfficeMapsConfigEntry) -> bool:
    """Unload an order, saving the request count."""
    await entry.runtime_data.coordinator.budget.async_save()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the frames and state when an order is removed.

    The request counter stays: the Met Office still counts today's requests.
    """
    await OrderState(hass, entry.entry_id).async_remove()
    await hass.async_add_executor_job(FrameFiles.for_entry(hass, entry.entry_id).remove)
