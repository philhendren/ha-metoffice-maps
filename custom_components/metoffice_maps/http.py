"""Serve rendered frames to dashboards.

Both views need Home Assistant auth: a bearer token, or a signed path
(`authSig`) for `<img>` tags. Only rendered PNGs leave this view; the API key
and the raw downloads never do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN, FRAME_URL, FRAMES_JSON_URL, SIGNED_URL_LIFETIME

if TYPE_CHECKING:
    from .coordinator import MetOfficeMapsCoordinator


def frame_path(entry_id: str, step: int) -> str:
    """Return the unsigned path of a frame."""
    return FRAME_URL.format(entry_id=entry_id, step=step)


def signed_frame_url(hass: HomeAssistant, entry_id: str, step: int) -> str:
    """Return a frame path signed for use in an `<img>` tag."""
    return async_sign_path(
        hass, frame_path(entry_id, step), SIGNED_URL_LIFETIME, use_content_user=True
    )


def frames_payload(hass: HomeAssistant, coordinator: MetOfficeMapsCoordinator) -> dict[str, Any]:
    """Return the published frames with signed URLs."""
    data = coordinator.data
    entry_id = coordinator.config_entry.entry_id
    return {
        "run": data.run.isoformat() if data.run else None,
        "frames": [
            {
                "step": frame.step,
                "valid_time": frame.valid_time.isoformat(),
                "url": signed_frame_url(hass, entry_id, frame.step),
            }
            for frame in data.frames
        ],
    }


def _coordinator(hass: HomeAssistant, entry_id: str) -> MetOfficeMapsCoordinator | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        return None
    return entry.runtime_data.coordinator


class FrameView(HomeAssistantView):
    """One rendered frame."""

    url = FRAME_URL
    name = f"api:{DOMAIN}:frame"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the view."""
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str, step: str) -> web.StreamResponse:
        """Return the frame for a step, or 304 if the browser has it."""
        coordinator = _coordinator(self.hass, entry_id)
        if coordinator is None or not step.isdigit():
            return web.Response(status=404)
        if (found := await coordinator.async_frame(int(step))) is None:
            return web.Response(status=404)
        frame, body = found
        etag = f'"{frame.run:%Y%m%d%H}-{frame.step}"'
        headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers=headers)
        return web.Response(body=body, content_type="image/png", headers=headers)


class FramesJsonView(HomeAssistantView):
    """The list of published frames."""

    url = FRAMES_JSON_URL
    name = f"api:{DOMAIN}:frames"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the view."""
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Return the frames with signed URLs."""
        if (coordinator := _coordinator(self.hass, entry_id)) is None:
            return web.Response(status=404)
        return self.json(frames_payload(self.hass, coordinator))
