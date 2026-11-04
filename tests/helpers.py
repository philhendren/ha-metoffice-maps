"""Test helpers: a fake DataHub, synthetic map images and config entries.

Nothing here touches the network: every HTTP call goes through Home
Assistant's AiohttpClientMocker, and pytest-socket blocks real sockets.
The PNGs are generated here, in the same format Phase 0 found (800 x 800,
palette mode with per-entry transparency); no real Met Office image is used.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from PIL import Image
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.metoffice_maps.const import (
    API_BASE,
    CONF_ORDER_ID,
    DEFAULT_OPTIONS,
    DOMAIN,
    PARAM_PRECIP,
)

FIXTURES = Path(__file__).parent / "fixtures"
API_KEY = "test-key"
ORDER_ID = "o000000000001"
HOME = (52.48, -1.90)  # central Birmingham
HOME_PIXEL = (462, 468)  # where HOME falls on an 800 x 800 image of the UK extent
SIZE = (800, 800)
RUN_PREV = datetime(2026, 11, 3, 12, tzinfo=UTC)
RUN_NOW = datetime(2026, 11, 4, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 4, 10, 5, tzinfo=UTC)
# Real orders also list the model's land cover; the integration no longer downloads it.
PARAM_LAND = "land_cover"

# Rain palette: index 0 is "no rain" (fully transparent), like the real images.
RAIN_LIGHT = (153, 254, 255)
RAIN_HEAVY = (0, 86, 255)


def load_fixture(name: str) -> Any:
    """Return a JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


def file_id(parameter: str, step: int, run: datetime) -> str:
    """Return a dated fileId."""
    return f"{parameter}_ts{step}_{run:%Y%m%d%H}"


def png_bytes(img: Image.Image) -> bytes:
    """Encode an image as PNG."""
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def precip_png(
    patches: list[tuple[tuple[int, int, int, int], int]] | None = None,
    size: tuple[int, int] = SIZE,
) -> bytes:
    """Return a palette rain image; `patches` are (box, palette index) pairs."""
    img = Image.new("P", size, 0)
    palette = [0, 0, 0, *RAIN_LIGHT, *RAIN_HEAVY] + [0] * (256 - 3) * 3
    img.putpalette(palette)
    img.info["transparency"] = bytes([0, 254, 254])
    for box, index in patches or [
        ((HOME_PIXEL[0] - 10, HOME_PIXEL[1] - 10, HOME_PIXEL[0] + 10, HOME_PIXEL[1] + 10), 2)
    ]:
        img.paste(index, box)
    out = io.BytesIO()
    img.save(out, format="PNG", transparency=img.info["transparency"])
    return out.getvalue()


class FakeDataHub:
    """A scripted DataHub Map Images API behind AiohttpClientMocker.

    `runs` lists the model runs the listing offers. `fail_next` is a queue of
    HTTP statuses or exceptions applied to the next requests, in order;
    `fail_always` applies to every request while set. `missing` holds fileIds
    that answer 404. Every request is recorded in `requests`.
    """

    def __init__(self, aioclient_mock: AiohttpClientMocker) -> None:
        """Register the fake endpoints."""
        self.mock = aioclient_mock
        self.runs = [RUN_PREV, RUN_NOW]
        self.steps = list(range(25))
        self.missing: set[str] = set()
        self.fail_next: list[int | BaseException] = []
        self.fail_always: int | BaseException | None = None
        self.requests: list[str] = []
        self.precip = precip_png()
        self.meta = load_fixture("precip_meta.json")
        aioclient_mock.get(re.compile(re.escape(API_BASE)), side_effect=self._handle)

    # What the client asked for ----------------------------------------------
    @property
    def listings(self) -> int:
        """Return how many listing calls were made."""
        return sum(1 for path in self.requests if path == "listing")

    @property
    def downloads(self) -> list[str]:
        """Return the fileIds whose data was downloaded."""
        return [path[5:] for path in self.requests if path.startswith("data:")]

    def headers(self) -> list[dict[str, str]]:
        """Return the headers of every request."""
        return [dict(call[3] or {}) for call in self.mock.mock_calls]

    # Responses ------------------------------------------------------------------
    def listing(self) -> dict[str, Any]:
        """Return a listing in the shape Phase 0 recorded."""
        files = []
        for run in self.runs:
            for parameter in (PARAM_PRECIP, "cloud_amount_total", PARAM_LAND):
                for step in self.steps:
                    for fid in (file_id(parameter, step, run), f"{parameter}_ts{step}_+{run:%H}"):
                        files.append(
                            {
                                "fileId": fid,
                                "run": f"{run:%H}",
                                "runDateTime": run.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            }
                        )
        order = load_fixture("latest.json")["orderDetails"]["order"]
        return {"orderDetails": {"order": order, "files": files}}

    async def _handle(self, method: str, url: URL, data: Any) -> AiohttpClientMockResponse:
        prefix = URL(API_BASE).path + "/orders/"
        parts = url.raw_path[len(prefix) :].split("/")
        order, rest = parts[0], [unquote(part) for part in parts[2:]]
        kind = "listing" if not rest else ("data:" if rest[1:] == ["data"] else "meta:") + rest[0]
        self.requests.append(kind)
        failure = self.fail_next.pop(0) if self.fail_next else self.fail_always
        if isinstance(failure, BaseException):
            return AiohttpClientMockResponse(method, url, exc=failure)
        if failure is not None:
            return AiohttpClientMockResponse(method, url, status=failure, text="error")
        if order != ORDER_ID or (rest and rest[0] in self.missing):
            return AiohttpClientMockResponse(method, url, status=404, json={"message": "Not found"})
        if not rest:
            return AiohttpClientMockResponse(method, url, json=self.listing())
        if rest[1:] != ["data"]:
            return AiohttpClientMockResponse(method, url, json=self.meta)
        return AiohttpClientMockResponse(
            method, url, response=self.precip, headers={"Content-Type": "image/png"}
        )


def frame_ids(run: datetime = RUN_NOW, first: int = 11, count: int = 6) -> list[str]:
    """Return the precipitation fileIds expected on show."""
    return [file_id(PARAM_PRECIP, step, run) for step in range(first, first + count)]


def make_entry(**options: Any) -> MockConfigEntry:
    """Return a config entry for the test order."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Met Office Maps {ORDER_ID}",
        unique_id=ORDER_ID,
        data={CONF_API_KEY: API_KEY, CONF_ORDER_ID: ORDER_ID},
        options={**DEFAULT_OPTIONS, **options},
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up an entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


def later(minutes: float) -> timedelta:
    """Return a timedelta in minutes."""
    return timedelta(minutes=minutes)
