"""A thin async client for the DataHub Map Images API.

The key is sent only in the `apikey` header and never logged. Every call is
counted against the daily budget before it is made, so failures count too.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import aiohttp

from .budget import Budget
from .const import API_BASE, HTTP_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class ApiError(Exception):
    """A failed call that is worth retrying later, with backoff."""

    def __init__(self, status: int | None, what: str) -> None:
        """Record the status code (None for a network failure)."""
        super().__init__(f"{what}: {status if status is not None else 'no response'}")
        self.status = status


class RateLimited(ApiError):
    """HTTP 429."""


class AuthError(ApiError):
    """HTTP 401 or 403: the key is wrong or lacks access."""


class NotFound(ApiError):
    """HTTP 404: the order or file does not exist."""


class MapImagesClient:
    """Calls for one order."""

    def __init__(
        self, session: aiohttp.ClientSession, api_key: str, order_id: str, budget: Budget
    ) -> None:
        """Initialise the client."""
        self._session = session
        self._api_key = api_key
        self._base = f"{API_BASE}/orders/{quote(order_id, safe='')}/latest"
        self.budget = budget

    async def _get(self, path: str, accept: str, what: str) -> aiohttp.ClientResponse:
        self.budget.spend()
        try:
            resp = await self._session.get(
                self._base + path,
                headers={"apikey": self._api_key, "Accept": accept},
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("%s failed: %s", what, type(err).__name__)
            raise ApiError(None, what) from None
        _LOGGER.debug("%s: %s", what, resp.status)
        if resp.status == 200:
            return resp
        resp.release()
        if resp.status in (401, 403):
            raise AuthError(resp.status, what)
        if resp.status == 404:
            raise NotFound(resp.status, what)
        if resp.status == 429:
            raise RateLimited(resp.status, what)
        raise ApiError(resp.status, what)

    async def latest(self) -> dict[str, Any]:
        """List the files of the order's latest runs."""
        resp = await self._get("", "application/json", "listing")
        return await resp.json(content_type=None)

    async def file_meta(self, file_id: str) -> dict[str, Any]:
        """Return a file's metadata."""
        resp = await self._get(f"/{quote(file_id, safe='')}", "application/json", file_id)
        return await resp.json(content_type=None)

    async def file_data(self, file_id: str) -> bytes:
        """Return a file's PNG data."""
        resp = await self._get(
            f"/{quote(file_id, safe='')}/data", "application/octet-stream", file_id
        )
        return await resp.read()
