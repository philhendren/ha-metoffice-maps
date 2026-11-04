"""Met Office Maps services."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import ATTR_CONFIG_ENTRY_ID, DOMAIN, SERVICE_REFRESH

REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the services once."""

    async def refresh(call: ServiceCall) -> None:
        """Check for new frames now. Uses the budget like any other poll."""
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if (entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID)) is not None:
            entries = [entry for entry in entries if entry.entry_id == entry_id]
            if not entries:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="entry_not_loaded"
                )
        for entry in entries:
            await entry.runtime_data.coordinator.async_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh, schema=REFRESH_SCHEMA)
