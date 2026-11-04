"""Sensors: the published forecast and the requests made today."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import PLAN_DAILY_LIMIT
from .entity import MetOfficeMapsEntity
from .http import frames_payload

if TYPE_CHECKING:
    from . import MetOfficeMapsConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MetOfficeMapsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [ForecastSensor(coordinator, "forecast"), RequestsSensor(coordinator, "requests_today")]
    )


class ForecastSensor(MetOfficeMapsEntity, SensorEntity):
    """The model run on show; attributes list each frame with a signed URL."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # Signed URLs change on every update: keep them out of the recorder.
    _unrecorded_attributes = frozenset({"frames"})

    @property
    def native_value(self) -> datetime | None:
        """Return the run time of the published frames."""
        return self.coordinator.data.run

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the frames and the last check."""
        data = self.coordinator.data
        return {
            "frames": frames_payload(self.hass, self.coordinator)["frames"],
            "last_checked": data.last_checked.isoformat() if data.last_checked else None,
            "last_error": data.last_error,
        }


class RequestsSensor(MetOfficeMapsEntity, SensorEntity):
    """Requests made today (UTC) against the daily cap."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "requests"
    _attr_icon = "mdi:counter"

    @property
    def native_value(self) -> int:
        """Return the requests made today."""
        return self.coordinator.budget.used

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the cap and what is left."""
        budget = self.coordinator.budget
        return {
            "cap": budget.cap,
            "plan_limit": PLAN_DAILY_LIMIT,
            "remaining": budget.remaining,
            "budget_exhausted": budget.exhausted,
        }
