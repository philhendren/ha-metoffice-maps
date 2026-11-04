"""Constants for the Met Office Maps integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "metoffice_maps"
NAME: Final = "Met Office Maps"
VERSION: Final = "0.1.0"
PROJECT_URL: Final = "https://github.com/philhendren/ha-metoffice-maps"

# DataHub Map Images API. Paths from the open-source bolster client, confirmed
# by Phase 0 discovery on 4 November 2026.
API_BASE: Final = "https://data.hub.api.metoffice.gov.uk/map-images/1.0.0"
HTTP_TIMEOUT: Final = 30

# Parameters as they appear in fileIds.
PARAM_PRECIP: Final = "total_precipitation_rate"
PARAM_LAND: Final = "land_cover"

# Config entry data
CONF_ORDER_ID: Final = "order_id"

# Options
CONF_LATITUDE: Final = "latitude"
CONF_LONGITUDE: Final = "longitude"
CONF_RADIUS_KM: Final = "radius_km"
CONF_FRAMES: Final = "frames"
CONF_DAILY_CAP: Final = "daily_cap"
CONF_POLL_MINUTES: Final = "poll_minutes"

DEFAULT_RADIUS_KM: Final = 150
DEFAULT_FRAMES: Final = 6
DEFAULT_DAILY_CAP: Final = 800
DEFAULT_POLL_MINUTES: Final = 15

RADIUS_RANGE: Final = (25, 600)
FRAMES_RANGE: Final = (1, 12)
CAP_RANGE: Final = (50, 950)
POLL_RANGE: Final = (5, 120)

DEFAULT_OPTIONS: Final = {
    CONF_RADIUS_KM: DEFAULT_RADIUS_KM,
    CONF_FRAMES: DEFAULT_FRAMES,
    CONF_DAILY_CAP: DEFAULT_DAILY_CAP,
    CONF_POLL_MINUTES: DEFAULT_POLL_MINUTES,
}

# The free plan allows 1,000 requests a day, reset at 00:00 UTC.
PLAN_DAILY_LIMIT: Final = 1000
MAX_BACKOFF: Final = timedelta(hours=2)
STARTUP_JITTER_SECONDS: Final = 60

# Rendering
FRAME_SIZE: Final = 480
KM_PER_DEGREE: Final = 111.32

# Storage
STORAGE_VERSION: Final = 1
BUDGET_KEY: Final = f"{DOMAIN}.budget"
STATE_KEY: Final = f"{DOMAIN}.state"

# HTTP views
FRAME_URL: Final = "/api/metoffice_maps/{entry_id}/frame/{step}.png"
FRAMES_JSON_URL: Final = "/api/metoffice_maps/{entry_id}/frames.json"
SIGNED_URL_LIFETIME: Final = timedelta(hours=24)

# Services
SERVICE_REFRESH: Final = "refresh"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"

# Errors recorded on the forecast data
ERROR_RATE_LIMITED: Final = "rate_limited"
ERROR_API: Final = "api_error"
ERROR_BUDGET: Final = "budget_exhausted"
ERROR_BUDGET_RESERVED: Final = "budget_reserved"
ERROR_NO_FRAMES: Final = "no_frames"
ERROR_INCOMPLETE: Final = "incomplete_run"
ERROR_ORDER_NOT_FOUND: Final = "order_not_found"
ERROR_GEOMETRY: Final = "geometry"
