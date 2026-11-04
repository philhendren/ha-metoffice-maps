"""Frames on disk and the order's state in `.storage`.

Raw downloads and rendered frames live under
`/config/.storage/metoffice_maps/<entry_id>/`, which is not public (unlike
`www/`). They are served only through the integration's authenticated view.
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STATE_KEY, STORAGE_VERSION

LAND_FILE = "land_cover.png"


def frame_root(hass: HomeAssistant) -> Path:
    """Return the directory that holds every order's frames."""
    return Path(hass.config.path(".storage", DOMAIN))


def _safe(file_id: str) -> str:
    return file_id.replace("/", "_").replace("+", "plus") + ".png"


class FrameFiles:
    """Raw and rendered PNGs for one order. Blocking: call in the executor."""

    def __init__(self, root: Path) -> None:
        """Initialise the directories."""
        self.root = root
        self.raw = root / "raw"
        self.frames = root / "frames"

    @classmethod
    def for_entry(cls, hass: HomeAssistant, entry_id: str) -> FrameFiles:
        """Return the files of one config entry."""
        return cls(frame_root(hass) / entry_id)

    def ensure(self) -> None:
        """Create the directories."""
        self.raw.mkdir(parents=True, exist_ok=True)
        self.frames.mkdir(parents=True, exist_ok=True)

    def has_raw(self, file_id: str) -> bool:
        """Return True if the download is on disk."""
        return (self.raw / _safe(file_id)).is_file()

    def read_raw(self, file_id: str) -> bytes:
        """Return a download."""
        return (self.raw / _safe(file_id)).read_bytes()

    def write_raw(self, file_id: str, data: bytes) -> None:
        """Save a download."""
        (self.raw / _safe(file_id)).write_bytes(data)

    def read_land(self) -> bytes | None:
        """Return the land cover image, if downloaded."""
        path = self.root / LAND_FILE
        return path.read_bytes() if path.is_file() else None

    def write_land(self, data: bytes) -> None:
        """Save the land cover image."""
        (self.root / LAND_FILE).write_bytes(data)

    def has_frame(self, file_id: str) -> bool:
        """Return True if the rendered frame is on disk."""
        return (self.frames / _safe(file_id)).is_file()

    def read_frame(self, file_id: str) -> bytes | None:
        """Return a rendered frame, or None if it is missing."""
        path = self.frames / _safe(file_id)
        return path.read_bytes() if path.is_file() else None

    def write_frame(self, file_id: str, data: bytes) -> None:
        """Save a rendered frame."""
        (self.frames / _safe(file_id)).write_bytes(data)

    def clear_frames(self) -> None:
        """Delete every rendered frame (the raw downloads stay)."""
        for path in self.frames.glob("*.png"):
            path.unlink()

    def prune(self, keep: set[str]) -> None:
        """Delete raw and rendered files not in `keep`."""
        wanted = {_safe(file_id) for file_id in keep}
        for directory in (self.raw, self.frames):
            for path in directory.glob("*.png"):
                if path.name not in wanted:
                    path.unlink()

    def remove(self) -> None:
        """Delete everything for this order."""
        shutil.rmtree(self.root, ignore_errors=True)


class OrderState:
    """What is published and what the renderer needs, kept in `.storage`."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialise the state."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{STATE_KEY}.{entry_id}")
        self.data: dict[str, Any] = {}

    async def async_load(self) -> None:
        """Load the state."""
        self.data = await self._store.async_load() or {}

    async def async_save(self) -> None:
        """Save the state now."""
        await self._store.async_save(self.data)

    async def async_remove(self) -> None:
        """Delete the state."""
        await self._store.async_remove()
