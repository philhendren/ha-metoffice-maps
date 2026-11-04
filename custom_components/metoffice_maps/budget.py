"""The daily request budget: a persistent counter keyed by UTC date.

Every call to the API, including failures, is counted here before it is made.
The count lives in `.storage`, so a restart cannot reset it, and it rolls over
at 00:00 UTC, when the Met Office resets the plan's limit.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .const import BUDGET_KEY, DEFAULT_DAILY_CAP, DOMAIN, STORAGE_VERSION

SAVE_DELAY = 1
BUDGETS: HassKey[dict[str, Budget]] = HassKey(f"{DOMAIN}_budgets")


class BudgetExhausted(Exception):
    """Raised when a call would cross the daily cap."""


def utc_date() -> str:
    """Return today's date in UTC."""
    return dt_util.utcnow().date().isoformat()


class Budget:
    """Requests made today against a hard cap, for one order."""

    def __init__(self, hass: HomeAssistant, order_id: str, cap: int) -> None:
        """Initialise the budget."""
        self._store: Store[dict[str, object]] = Store(
            hass, STORAGE_VERSION, f"{BUDGET_KEY}.{order_id}"
        )
        self.cap = cap
        self._date = utc_date()
        self._count = 0

    async def async_load(self) -> None:
        """Load today's count."""
        data = await self._store.async_load() or {}
        self._date = str(data.get("date", utc_date()))
        self._count = int(data.get("count", 0))  # type: ignore[call-overload]

    def _data(self) -> dict[str, object]:
        return {"date": self._date, "count": self._count}

    def _roll(self) -> None:
        if (today := utc_date()) != self._date:
            self._date = today
            self._count = 0

    @property
    def used(self) -> int:
        """Return the number of requests made today (UTC)."""
        self._roll()
        return self._count

    @property
    def remaining(self) -> int:
        """Return how many requests are left before the cap."""
        return max(0, self.cap - self.used)

    @property
    def exhausted(self) -> bool:
        """Return True when no further calls are allowed today."""
        return self.remaining == 0

    def can_spend(self, count: int) -> bool:
        """Return True if `count` more calls fit under the cap."""
        return count <= self.remaining

    def spend(self) -> None:
        """Count one call, or raise BudgetExhausted if it would cross the cap."""
        if not self.can_spend(1):
            raise BudgetExhausted
        self._count += 1
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def async_save(self) -> None:
        """Save now."""
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the counter."""
        await self._store.async_remove()


async def async_get_budget(hass: HomeAssistant, order_id: str) -> Budget:
    """Return the one shared budget for an order, loading it on first use.

    The config flow, re-auth and the loaded entry all count against the same
    object, so none of them can overwrite another's count.
    """
    budgets = hass.data.setdefault(BUDGETS, {})
    if (budget := budgets.get(order_id)) is None:
        budget = Budget(hass, order_id, DEFAULT_DAILY_CAP)
        await budget.async_load()
        budgets[order_id] = budget
    return budget
