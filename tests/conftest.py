"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest

from .helpers import HOME, NOW, FakeDataHub


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/metoffice_maps in every test."""


@pytest.fixture(autouse=True)
def frames_tmp(tmp_path) -> Generator[None]:
    """Keep frame files inside the test's temp dir."""
    with patch("custom_components.metoffice_maps.storage.frame_root", return_value=tmp_path):
        yield


@pytest.fixture(autouse=True)
def home(hass: HomeAssistant) -> None:
    """Put home in Leighton Buzzard."""
    hass.config.latitude, hass.config.longitude = HOME


@pytest.fixture(autouse=True)
def no_jitter() -> Generator[None]:
    """Make the startup jitter predictable: the first poll comes after 30 s."""
    with patch("custom_components.metoffice_maps.random.uniform", return_value=30):
        yield


@pytest.fixture
def now(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time at 10:05 UTC on 4 November 2026."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def datahub(aioclient_mock, now) -> FakeDataHub:
    """A fake DataHub at 10:05 UTC."""
    return FakeDataHub(aioclient_mock)
