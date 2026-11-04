"""Config, options and re-auth flows for Met Office Maps."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import ApiError, AuthError, MapImagesClient, NotFound
from .budget import BudgetExhausted, async_get_budget
from .const import (
    CAP_RANGE,
    CONF_DAILY_CAP,
    CONF_FRAMES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_ORDER_ID,
    CONF_POLL_MINUTES,
    CONF_RADIUS_KM,
    DEFAULT_OPTIONS,
    DOMAIN,
    FRAMES_RANGE,
    NAME,
    POLL_RANGE,
    RADIUS_RANGE,
)

DATAHUB_URL = "https://datahub.metoffice.gov.uk/"


def normalise_order_id(value: str) -> str:
    """The portal shows the order ID capitalised; the API only accepts lower case."""
    return value.strip().lower()


async def async_validate(hass: HomeAssistant, api_key: str, order_id: str) -> str | None:
    """List the order once (counted against today's budget); return an error key."""
    budget = await async_get_budget(hass, order_id)
    client = MapImagesClient(async_get_clientsession(hass), api_key, order_id, budget)
    try:
        await client.latest()
    except AuthError:
        return "invalid_auth"
    except NotFound:
        return "order_not_found"
    except BudgetExhausted:
        return "budget_exhausted"
    except ApiError:
        return "cannot_connect"
    finally:
        await budget.async_save()
    return None


def _key_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_API_KEY): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            )
        }
    )


class MetOfficeMapsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one Map Images order."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the key and the order ID."""
        errors: dict[str, str] = {}
        if user_input is not None:
            order_id = normalise_order_id(user_input[CONF_ORDER_ID])
            await self.async_set_unique_id(order_id)
            self._abort_if_unique_id_configured()
            api_key = user_input[CONF_API_KEY].strip()
            if (error := await async_validate(self.hass, api_key, order_id)) is None:
                return self.async_create_entry(
                    title=f"{NAME} {order_id}",
                    data={CONF_API_KEY: api_key, CONF_ORDER_ID: order_id},
                    options=dict(DEFAULT_OPTIONS),
                )
            errors["base"] = error
        schema = _key_schema().extend({vol.Required(CONF_ORDER_ID): TextSelector()})
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
            description_placeholders={"datahub_url": DATAHUB_URL},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start re-auth after the Met Office rejected the key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new key."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            order_id = entry.data[CONF_ORDER_ID]
            if (error := await async_validate(self.hass, api_key, order_id)) is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_key_schema(),
            errors=errors,
            description_placeholders={"order_id": entry.data[CONF_ORDER_ID]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MetOfficeMapsOptionsFlow:
        """Return the options flow."""
        return MetOfficeMapsOptionsFlow()


def _number(low: float, high: float, step: float | str, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=low, max=high, step=step, mode=NumberSelectorMode.BOX, unit_of_measurement=unit
        )
    )


class MetOfficeMapsOptionsFlow(OptionsFlowWithReload):
    """Area, frames, budget and polling."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    key: int(value) if key not in (CONF_LATITUDE, CONF_LONGITUDE) else value
                    for key, value in user_input.items()
                }
            )
        current = {**DEFAULT_OPTIONS, **self.config_entry.options}
        current.setdefault(CONF_LATITUDE, self.hass.config.latitude)
        current.setdefault(CONF_LONGITUDE, self.hass.config.longitude)
        schema = vol.Schema(
            {
                vol.Required(CONF_LATITUDE): _number(45, 63, "any", "°"),
                vol.Required(CONF_LONGITUDE): _number(-25, 15, "any", "°"),
                vol.Required(CONF_RADIUS_KM): _number(*RADIUS_RANGE, 5, "km"),
                vol.Required(CONF_FRAMES): _number(*FRAMES_RANGE, 1, "frames"),
                vol.Required(CONF_DAILY_CAP): _number(*CAP_RANGE, 10, "requests"),
                vol.Required(CONF_POLL_MINUTES): _number(*POLL_RANGE, 1, "min"),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=self.add_suggested_values_to_schema(schema, current)
        )
