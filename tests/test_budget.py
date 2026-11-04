"""The daily request budget."""

from __future__ import annotations

from datetime import UTC, datetime

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest

from custom_components.metoffice_maps.budget import Budget, BudgetExhausted, async_get_budget

from .helpers import ORDER_ID


async def test_counts_and_refuses_at_cap(hass: HomeAssistant, now) -> None:
    budget = Budget(hass, ORDER_ID, 3)
    await budget.async_load()
    assert (budget.used, budget.remaining, budget.exhausted) == (0, 3, False)
    budget.spend()
    budget.spend()
    assert budget.can_spend(1)
    assert not budget.can_spend(2)
    budget.spend()
    assert budget.exhausted
    with pytest.raises(BudgetExhausted):
        budget.spend()
    assert budget.used == 3


async def test_persists_across_reload(hass: HomeAssistant, hass_storage, now) -> None:
    budget = Budget(hass, ORDER_ID, 800)
    await budget.async_load()
    budget.spend()
    budget.spend()
    await budget.async_save()
    again = Budget(hass, ORDER_ID, 800)
    await again.async_load()
    assert again.used == 2
    assert hass_storage[f"metoffice_maps.budget.{ORDER_ID}"]["data"]["count"] == 2
    await again.async_remove()
    assert f"metoffice_maps.budget.{ORDER_ID}" not in hass_storage


async def test_resets_at_utc_midnight_not_local_midnight(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """In British Summer Time, local midnight is 23:00 UTC: that must not reset."""
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(datetime(2026, 6, 15, 22, 59, tzinfo=UTC))  # 23:59 BST
    budget = Budget(hass, ORDER_ID, 800)
    await budget.async_load()
    budget.spend()
    freezer.move_to(datetime(2026, 6, 15, 23, 1, tzinfo=UTC))  # 00:01 BST, next local day
    assert budget.used == 1
    freezer.move_to(datetime(2026, 6, 15, 23, 59, tzinfo=UTC))
    budget.spend()
    assert budget.used == 2
    freezer.move_to(datetime(2026, 6, 16, 0, 1, tzinfo=UTC))  # 00:01 UTC
    assert budget.used == 0
    assert budget.remaining == 800


async def test_stale_count_from_yesterday_is_ignored(
    hass: HomeAssistant, hass_storage, now
) -> None:
    hass_storage[f"metoffice_maps.budget.{ORDER_ID}"] = {
        "version": 1,
        "key": f"metoffice_maps.budget.{ORDER_ID}",
        "data": {"date": "2026-11-03", "count": 790},
    }
    budget = Budget(hass, ORDER_ID, 800)
    await budget.async_load()
    assert budget.used == 0


async def test_shared_budget(hass: HomeAssistant, now) -> None:
    first = await async_get_budget(hass, ORDER_ID)
    assert await async_get_budget(hass, ORDER_ID) is first
    assert await async_get_budget(hass, "o2") is not first
