"""Config flow for Yorkshire Water."""
from __future__ import annotations

import logging

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .auth import YorkshireWaterAuth
from .client import YorkshireWaterClient, YorkshireWaterAuthError, API_METER_DETAILS
from .const import DOMAIN, CONF_METER_REFERENCE, CONF_ACCOUNT_REFERENCE

_LOGGER = logging.getLogger(__name__)


class YorkshireWaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yorkshire Water."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    def _account_reference_candidates(reference: str) -> list[str]:
        """Account reference variants to try, most specific first.

        Yorkshire Water bills show a long customer reference number while the
        API expects the first 15 digits of it. Try the value as given first,
        then the truncated form.
        """
        candidates = [reference]
        if len(reference) > 15:
            candidates.append(reference[:15])
        if len(reference) > 8 and reference[:8] not in candidates:
            candidates.append(reference[:8])
        return candidates

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            account_ref_clean = user_input[CONF_ACCOUNT_REFERENCE].replace(" ", "").strip()
            auth = YorkshireWaterAuth()
            try:
                await auth.async_login(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )

                meter_reference = None
                used_reference = None
                for candidate in self._account_reference_candidates(account_ref_clean):
                    session = auth._get_session()
                    headers = {
                        "Authorization": f"Bearer {auth.access_token}",
                        "Accept": "application/json",
                    }
                    async with session.get(
                        API_METER_DETAILS,
                        headers=headers,
                        params={"accountReference": candidate},
                    ) as resp:
                        if resp.status != 200:
                            _LOGGER.warning(
                                "Yorkshire Water meter-details returned status %d for %s",
                                resp.status,
                                candidate,
                            )
                            continue
                        data = await resp.json()
                        if isinstance(data, list):
                            data = data[0] if data else {}
                        found = (data or {}).get("meterReference")
                        if found:
                            meter_reference = found
                            used_reference = candidate
                            break

                if not meter_reference:
                    errors["base"] = "cannot_discover"
                else:
                    await self.async_set_unique_id(meter_reference)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Yorkshire Water ({meter_reference})",
                        data={
                            CONF_EMAIL:             user_input[CONF_EMAIL],
                            CONF_PASSWORD:          user_input[CONF_PASSWORD],
                            CONF_ACCOUNT_REFERENCE: used_reference,
                            CONF_METER_REFERENCE:   meter_reference,
                        },
                    )

            except PermissionError:
                errors["base"] = "auth_error"
            except Exception:
                _LOGGER.exception("Unexpected error during Yorkshire Water setup")
                errors["base"] = "network_error"
            finally:
                await auth.async_close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.EMAIL
                        )
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    vol.Required(CONF_ACCOUNT_REFERENCE): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT
                        )
                    ),
                }
            ),
            errors=errors,
        )