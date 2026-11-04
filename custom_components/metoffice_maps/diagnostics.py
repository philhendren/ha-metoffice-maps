"""Diagnostics, with the API key redacted."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import MetOfficeMapsConfigEntry

TO_REDACT = {CONF_API_KEY, "apikey"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MetOfficeMapsConfigEntry
) -> dict[str, Any]:
    """Return the entry, the budget and the last listing summary."""
    coordinator = entry.runtime_data.coordinator
    budget = coordinator.budget
    return async_redact_data(
        {
            "entry": entry.as_dict(),
            "budget": {
                "used": budget.used,
                "cap": budget.cap,
                "remaining": budget.remaining,
                "exhausted": budget.exhausted,
            },
            "coordinator": coordinator.diagnostics(),
        },
        TO_REDACT,
    )
