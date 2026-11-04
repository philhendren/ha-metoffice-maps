"""The update coordinator: poll the order within the daily budget.

Each tick lists the order's latest runs (1 call). Frames are downloaded only
when the selection changes: a new run brings up to N new frames, and as time
passes one new hour rolls in. Frames already on disk are never fetched again.
A new set is published only once every frame in it is on disk and rendered,
so viewers always see a complete loop.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import ApiError, AuthError, MapImagesClient, NotFound, RateLimited
from .budget import BudgetExhausted
from .const import (
    CONF_FRAMES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_POLL_MINUTES,
    CONF_RADIUS_KM,
    DEFAULT_OPTIONS,
    DOMAIN,
    ERROR_API,
    ERROR_BUDGET,
    ERROR_BUDGET_RESERVED,
    ERROR_GEOMETRY,
    ERROR_INCOMPLETE,
    ERROR_NO_FRAMES,
    ERROR_ORDER_NOT_FOUND,
    ERROR_RATE_LIMITED,
    FRAME_SIZE,
    MAX_BACKOFF,
)
from .files import MapFile, Selection, listing_summary, parse_listing, select_frames
from .geometry import Extent, FrameGeometry, GeometryError
from .models import ForecastData, Frame
from .render import image_size, render_frame
from .storage import FrameFiles, OrderState

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class MetOfficeMapsCoordinator(DataUpdateCoordinator[ForecastData]):
    """Keep the published frames for one order up to date."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: MapImagesClient,
        files: FrameFiles,
        state: OrderState,
    ) -> None:
        """Initialise the coordinator."""
        options = {**DEFAULT_OPTIONS, **entry.options}
        self.base_interval = timedelta(minutes=options[CONF_POLL_MINUTES])
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=self.base_interval,
        )
        self.client = client
        self.budget = client.budget
        self.files = files
        self.state = state
        self.frame_count = int(options[CONF_FRAMES])
        self.radius_km = float(options[CONF_RADIUS_KM])
        self.latitude = float(options.get(CONF_LATITUDE, hass.config.latitude))
        self.longitude = float(options.get(CONF_LONGITUDE, hass.config.longitude))
        self.backoff_level = 0
        self.halted = False
        self._last_checked: datetime | None = None
        self._last_error: str | None = None

    # Published data -----------------------------------------------------------
    @property
    def render_key(self) -> str:
        """Return what rendered frames depend on, besides the downloads."""
        return f"{self.latitude:.4f},{self.longitude:.4f},{self.radius_km:g},{FRAME_SIZE}"

    @property
    def issue_id(self) -> str:
        """Return the repair issue id for a missing order."""
        return f"{ERROR_ORDER_NOT_FOUND}_{self.config_entry.entry_id}"

    def _snapshot(self) -> ForecastData:
        frames = [Frame.from_state(item) for item in self.state.data.get("frames", [])]
        return ForecastData(frames, self._last_checked, self._last_error)

    async def async_restore(self) -> bool:
        """Load frames already on disk, re-rendering if the options changed.

        Returns True if there are frames to serve straight away.
        """
        await self.state.async_load()
        await self.hass.async_add_executor_job(self.files.ensure)
        frame_ids = [item["file_id"] for item in self.state.data.get("frames", [])]
        if not frame_ids:
            return False
        if self.state.data.get("render_key") != self.render_key:
            if not await self.hass.async_add_executor_job(self._rerender, frame_ids):
                self.state.data["frames"] = []
                await self.state.async_save()
                return False
            self.state.data["render_key"] = self.render_key
            await self.state.async_save()
        self.data = self._snapshot()
        return True

    async def async_frame(self, step: int) -> tuple[Frame, bytes] | None:
        """Return a published frame and its PNG."""
        if self.data is None or (frame := self.data.frame(step)) is None:
            return None
        body = await self.hass.async_add_executor_job(self.files.read_frame, frame.file_id)
        return None if body is None else (frame, body)

    # Polling ----------------------------------------------------------------
    async def _async_update_data(self) -> ForecastData:
        """Poll once, within the budget."""
        self._last_error = None
        if self.halted:
            return self._snapshot()
        if self.budget.exhausted:
            self._last_error = ERROR_BUDGET
            return self._snapshot()
        try:
            await self._poll()
        except AuthError as err:
            raise ConfigEntryAuthFailed("The Met Office rejected the API key") from err
        except NotFound as err:
            if self.data is None:
                raise ConfigEntryError("The order was not found") from err
            self._halt()
        except BudgetExhausted:
            self._last_error = ERROR_BUDGET
        except GeometryError as err:
            _LOGGER.warning("Map geometry not understood: %s", err)
            self._last_error = ERROR_GEOMETRY
        except ApiError as err:
            self._back_off(err)
        else:
            self._recover()
        return self._snapshot()

    def _halt(self) -> None:
        """Stop polling a missing order until the entry is reloaded."""
        _LOGGER.error("Order not found: polling stopped until the integration is reloaded")
        self.halted = True
        self.update_interval = None
        self._last_error = ERROR_ORDER_NOT_FOUND
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ERROR_ORDER_NOT_FOUND,
            translation_placeholders={"title": self.config_entry.title},
        )

    def _back_off(self, err: ApiError) -> None:
        """Double the poll interval, up to the ceiling."""
        self.backoff_level += 1
        self.update_interval = min(self.base_interval * 2**self.backoff_level, MAX_BACKOFF)
        self._last_error = ERROR_RATE_LIMITED if isinstance(err, RateLimited) else ERROR_API
        _LOGGER.warning(
            "Met Office request failed (%s); next check in %s", err, self.update_interval
        )

    def _recover(self) -> None:
        if self.backoff_level:
            _LOGGER.info("Met Office requests recovered")
        self.backoff_level = 0
        self.update_interval = self.base_interval

    async def _poll(self) -> None:
        listing = await self.client.latest()
        now = dt_util.utcnow()
        self._last_checked = now
        self.state.data["listing"] = listing_summary(listing)
        selection = select_frames(parse_listing(listing), now, self.frame_count)
        if selection is None:
            self._last_error = ERROR_NO_FRAMES
            return
        if not await self._download(selection):
            return
        ids = [item.file_id for item in selection.frames]
        await self.hass.async_add_executor_job(self._render, ids, False)
        await self._publish(selection.frames)

    async def _download(self, selection: Selection) -> bool:
        """Fetch what is missing; return False if the run is not usable yet."""
        has_raw = self.files.has_raw
        missing: list[MapFile] = [
            item
            for item in selection.frames
            if not await self.hass.async_add_executor_job(has_raw, item.file_id)
        ]
        need_extent = "extent" not in self.state.data
        land_on_disk = await self.hass.async_add_executor_job(self.files.read_land)
        need_land = selection.land is not None and (
            land_on_disk is None or self.state.data.get("land_stale", False)
        )
        cost = len(missing) + need_extent + need_land
        if not self.budget.can_spend(cost):
            _LOGGER.info("Skipping run: %s requests would cross the daily cap", cost)
            self._last_error = ERROR_BUDGET_RESERVED
            return False
        if need_extent:
            meta = await self.client.file_meta(selection.frames[0].file_id)
            self.state.data["extent"] = Extent.from_metadata(meta).as_dict()
        for item in missing:
            try:
                data = await self.client.file_data(item.file_id)
            except NotFound:
                _LOGGER.info("%s is not available yet", item.file_id)
                self._last_error = ERROR_INCOMPLETE
                return False
            await self.hass.async_add_executor_job(self.files.write_raw, item.file_id, data)
        if need_land:
            assert selection.land is not None
            land = await self.client.file_data(selection.land.file_id)
            await self.hass.async_add_executor_job(self.files.write_land, land)
            self.state.data["land_stale"] = False
            await self.hass.async_add_executor_job(self.files.clear_frames)
        return True

    async def _publish(self, frames: list[MapFile]) -> None:
        """Swap to the new set of frames in one step."""
        new = [Frame(item.file_id, item.step, item.run) for item in frames]
        old_ids = [item["file_id"] for item in self.state.data.get("frames", [])]
        new_ids = [frame.file_id for frame in new]
        if new_ids != old_ids:
            self.state.data["previous"] = old_ids
        self.state.data["frames"] = [frame.as_state() for frame in new]
        self.state.data["render_key"] = self.render_key
        keep = set(new_ids) | set(self.state.data.get("previous", []))
        await self.hass.async_add_executor_job(self.files.prune, keep)
        await self.state.async_save()

    # Rendering (executor) -----------------------------------------------------
    def _rerender(self, file_ids: list[str]) -> bool:
        """Render every frame again from the downloads; False if any is missing."""
        if "extent" not in self.state.data or not all(map(self.files.has_raw, file_ids)):
            return False
        self.files.clear_frames()
        self._render(file_ids, True)
        return True

    def _render(self, file_ids: list[str], force: bool) -> None:
        extent = Extent(**self.state.data["extent"])
        land = self.files.read_land()
        for file_id in file_ids:
            if not force and self.files.has_frame(file_id):
                continue
            raw = self.files.read_raw(file_id)
            size = image_size(raw)
            geometry = FrameGeometry(extent, *size)
            box = geometry.crop_box(self.latitude, self.longitude, self.radius_km)
            coast = land
            if land is not None and image_size(land) != size:
                # Land cover no longer matches: render without it, fetch it again next time.
                self.state.data["land_stale"] = True
                coast = None
            marker = _marker(geometry, box, self.latitude, self.longitude)
            self.files.write_frame(file_id, render_frame(raw, box, FRAME_SIZE, coast, marker))


def _marker(
    geometry: FrameGeometry, box: tuple[int, int, int, int], lat: float, lon: float
) -> tuple[float, float]:
    """Return home's position in the rendered frame."""
    x, y = geometry.to_pixel(lat, lon)
    left, top, right, bottom = box
    return (x - left) / (right - left) * FRAME_SIZE, (y - top) / (bottom - top) * FRAME_SIZE
