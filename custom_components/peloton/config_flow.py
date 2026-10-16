"""Config flow for Peloton."""

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
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

from .api import (
    PelotonAuthError,
    PelotonClient,
    PelotonConnectionError,
    PelotonError,
    PelotonMfaRequiredError,
    PelotonRateLimitError,
    PelotonTokens,
    async_login_and_identify,
    async_revoke,
)
from .const import (
    ACTIVE_INTERVAL_RANGE,
    CONF_ACTIVE_INTERVAL,
    CONF_IDLE_INTERVAL,
    CONF_MAX_WORKOUT_MINUTES,
    DEFAULT_ACTIVE_INTERVAL,
    DEFAULT_IDLE_INTERVAL,
    DEFAULT_MAX_WORKOUT_MINUTES,
    DOMAIN,
    IDLE_INTERVAL_RANGE,
    INTEGRATION_NAME,
    MAX_WORKOUT_MINUTES_RANGE,
)

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
USERNAME_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
)
CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): USERNAME_SELECTOR,
        vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR})


def _whole_number(bounds: tuple[int, int], unit: str) -> vol.All:
    """Return a validator for a whole number within bounds."""
    return vol.All(
        NumberSelector(
            NumberSelectorConfig(
                min=bounds[0],
                max=bounds[1],
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement=unit,
            )
        ),
        vol.Coerce(int),
    )


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IDLE_INTERVAL): _whole_number(IDLE_INTERVAL_RANGE, "s"),
        vol.Required(CONF_ACTIVE_INTERVAL): _whole_number(ACTIVE_INTERVAL_RANGE, "s"),
        vol.Required(CONF_MAX_WORKOUT_MINUTES): _whole_number(
            MAX_WORKOUT_MINUTES_RANGE, "min"
        ),
    }
)
DEFAULT_OPTIONS = {
    CONF_IDLE_INTERVAL: DEFAULT_IDLE_INTERVAL,
    CONF_ACTIVE_INTERVAL: DEFAULT_ACTIVE_INTERVAL,
    CONF_MAX_WORKOUT_MINUTES: DEFAULT_MAX_WORKOUT_MINUTES,
}


class PelotonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in to Peloton and store the resulting tokens (never the password)."""

    VERSION = 3

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PelotonOptionsFlow:
        """Return the options flow."""
        return PelotonOptionsFlow()

    async def _async_login(
        self, username: str, password: str
    ) -> tuple[PelotonTokens | None, dict[str, str]]:
        """Log in once. Return tokens that carry the user id, or form errors."""
        try:
            tokens = await async_login_and_identify(
                async_get_clientsession(self.hass), username, password
            )
        except PelotonMfaRequiredError:
            return None, {"base": "mfa_required"}
        except PelotonAuthError:
            return None, {"base": "invalid_auth"}
        except PelotonError as err:
            _LOGGER.debug("Login failed: %s", err)
            return None, {"base": _error_for(err)}
        return tokens, {}

    async def _async_revoke(self, refresh_token: str | None) -> None:
        """Revoke a refresh token this flow will not keep (best effort)."""
        if not refresh_token:
            return
        try:
            await async_revoke(async_get_clientsession(self.hass), refresh_token)
        except PelotonError as err:
            _LOGGER.debug("Could not revoke a refresh token: %s", err)

    async def _async_title(self, tokens: PelotonTokens, username: str) -> str:
        """Return the entry title, using the Peloton username when available."""
        client = PelotonClient(async_get_clientsession(self.hass), tokens)
        try:
            user = await client.async_get_me()
        except PelotonError as err:
            _LOGGER.debug("Could not read the profile for the title: %s", err)
            return f"{INTEGRATION_NAME}: {username}"
        return f"{INTEGRATION_NAME}: {user.username or username}"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Peloton username (or email) and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            # Entries from before version 3 may still be keyed by the login
            # name; catch those before spending a password login.
            for entry in self._async_current_entries(include_ignore=False):
                if _same_login(username, entry.unique_id) or _same_login(
                    username, entry.data.get(CONF_USERNAME)
                ):
                    return self.async_abort(reason="already_configured")
            tokens, errors = await self._async_login(
                username, user_input[CONF_PASSWORD]
            )
            if tokens is not None:
                try:
                    await self.async_set_unique_id(tokens.user_id)
                    self._abort_if_unique_id_configured()
                except AbortFlow:
                    await self._async_revoke(tokens.refresh_token)
                    raise
                return self.async_create_entry(
                    title=await self._async_title(tokens, username),
                    data={CONF_USERNAME: username, CONF_TOKEN: tokens.as_dict()},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA, _without_password(user_input)
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication when the stored tokens stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password of the same account again."""
        entry = self._get_reauth_entry()
        username = entry.data.get(CONF_USERNAME, "")
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, errors = await self._async_login(
                username, user_input[CONF_PASSWORD]
            )
            if tokens is not None:
                return await self._async_update_existing(entry, username, tokens)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={CONF_USERNAME: username},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Log in again, for example after changing the Peloton password."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            tokens, errors = await self._async_login(
                username, user_input[CONF_PASSWORD]
            )
            if tokens is not None:
                return await self._async_update_existing(entry, username, tokens)
        suggested = {CONF_USERNAME: entry.data.get(CONF_USERNAME)}
        suggested |= _without_password(user_input) or {}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA, suggested
            ),
            errors=errors,
        )

    async def _async_update_existing(
        self, entry: ConfigEntry, username: str, tokens: PelotonTokens
    ) -> ConfigFlowResult:
        """Store new tokens on the entry being reauthenticated or reconfigured.

        An entry whose unique_id is its Peloton user id only accepts the same
        account. Entries from before version 3 whose migration login failed
        are still keyed by the login name; they accept the same login name and
        take the user id as unique_id, unless another entry already has it.
        """
        stored_user_id = (entry.data.get(CONF_TOKEN) or {}).get("user_id")
        if stored_user_id is not None and entry.unique_id == stored_user_id:
            abort_reason = (
                None if tokens.user_id == entry.unique_id else "wrong_account"
            )
        elif not _same_login(username, entry.data.get(CONF_USERNAME)):
            # Nothing to check the account against except the login name.
            abort_reason = "wrong_account"
        elif any(
            other.unique_id == tokens.user_id
            for other in self._async_current_entries(include_ignore=False)
            if other.entry_id != entry.entry_id
        ):
            abort_reason = "already_configured"
        else:
            abort_reason = None
        if abort_reason is not None:
            await self._async_revoke(tokens.refresh_token)
            return self.async_abort(reason=abort_reason)

        old_refresh_token = (entry.data.get(CONF_TOKEN) or {}).get("refresh_token")
        if old_refresh_token != tokens.refresh_token:
            await self._async_revoke(old_refresh_token)
        return self.async_update_reload_and_abort(
            entry,
            unique_id=tokens.user_id,
            data={CONF_USERNAME: username, CONF_TOKEN: tokens.as_dict()},
        )


class PelotonOptionsFlow(OptionsFlow):
    """Polling intervals and the abandoned-workout limit.

    The coordinator reads the options on every poll, so changes apply from
    the next poll without a reload.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, DEFAULT_OPTIONS | dict(self.config_entry.options)
            ),
        )


def _same_login(login: str, other: Any) -> bool:
    """Return True if two login names are the same, ignoring case."""
    return isinstance(other, str) and login.casefold() == other.strip().casefold()


def _without_password(user_input: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return form input without the password, to prefill a redisplayed form."""
    if user_input is None:
        return None
    return {key: value for key, value in user_input.items() if key != CONF_PASSWORD}


def _error_for(err: PelotonError) -> str:
    """Return the form error for a failed login that is not an auth error."""
    if isinstance(err, PelotonRateLimitError):
        return "rate_limited"
    if isinstance(err, PelotonConnectionError):
        return "cannot_connect"
    return "unknown"
