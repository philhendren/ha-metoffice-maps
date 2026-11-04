"""Base entity for Met Office Maps."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PROJECT_URL, VERSION
from .coordinator import MetOfficeMapsCoordinator


class MetOfficeMapsEntity(CoordinatorEntity[MetOfficeMapsCoordinator]):
    """An entity that belongs to an order's device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MetOfficeMapsCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Met Office (DataHub)",
            model="Map Images order",
            sw_version=VERSION,
            configuration_url=PROJECT_URL,
            entry_type=DeviceEntryType.SERVICE,
        )
