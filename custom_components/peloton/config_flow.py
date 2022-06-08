"""Config flow for Home Assistant Peloton Sensor integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from pylotoncycle import PylotonCycle
from pylotoncycle.pylotoncycle import PelotonLoginException
from requests.exceptions import Timeout
import voluptuous as vol

from .const import DOMAIN
from .const import INTEGRATION_NAME

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)


async def async_validate_input(
    hass: HomeAssistant, data: dict[str, Any]
) -> PylotonCycle:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    _LOGGER.debug("Logging in and setting up session to the Peloton API")
    try:
        api = await hass.async_add_executor_job(
            PylotonCycle, data[CONF_USERNAME], data[CONF_PASSWORD]
        )
        await hass.async_add_executor_job(api.GetMe)
    except PelotonLoginException as err:
        _LOGGER.warning("Username or password incorrect")
        raise InvalidAuth from err
    except (ConnectionError, Timeout) as err:
        raise CannotConnect("Could not connect to Peloton.") from err

    return api


class PelotonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore
    """Handle a config flow for Home Assistant Peloton Sensor integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        _LOGGER.debug("Loading Peloton configuration flow")

        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}
        if user_input is not None:
            try:
                api = await async_validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"{INTEGRATION_NAME}: {api.username}", data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):  # type: ignore
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):  # type: ignore
    """Error to indicate there is invalid auth."""
