"""Yorkshire Water API client."""
from __future__ import annotations

import logging
from datetime import date, datetime

import aiohttp
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .auth import YorkshireWaterAuth
from .const import (
    API_DAILY,
    API_YOUR_USAGE,
    API_PROPERTY,
    API_PROPERTIES,
    CONF_METER_REFERENCE,
    CONF_ACCOUNT_REFERENCE,
    DATA_FLOOR_DATE,
    PORTAL_BASE,
)

_LOGGER = logging.getLogger(__name__)

API_METER_DETAILS = f"{PORTAL_BASE}/api/account/smartmeter/meter-details"


def _parse_date(value: object) -> date | None:
    """Parse an API date string (ISO or US style) into a date."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


class YorkshireWaterAuthError(Exception):
    pass


class YorkshireWaterClient:
    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass = hass
        self._email = config[CONF_EMAIL]
        self._password = config[CONF_PASSWORD]
        self._account_reference = config[CONF_ACCOUNT_REFERENCE]
        self._meter_reference = config.get(CONF_METER_REFERENCE)
        self._auth = YorkshireWaterAuth()
        self._session: aiohttp.ClientSession | None = None
        # Account move-in / move-out dates, required by the daily-consumption
        # endpoint (see _fetch_account_dates).
        self._move_in_date: date | None = None
        self._move_out_date: date | None = None
        self._meter_details: dict | None = None
        self._dates_fetched = False
        self._in_ensure_token = False

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _ensure_token(self) -> None:
        """Login if no token, then ensure meter reference and dates are known."""
        if self._in_ensure_token:
            return
        self._in_ensure_token = True
        try:
            if not self._auth.access_token:
                try:
                    await self._auth.async_login(self._email, self._password)
                except PermissionError as err:
                    raise YorkshireWaterAuthError(str(err)) from err

            if not self._meter_reference:
                await self._fetch_meter_reference()

            if not self._dates_fetched:
                await self._fetch_account_dates()
        finally:
            self._in_ensure_token = False

    async def _fetch_meter_reference(self) -> None:
        """Call meter-details with account reference to get meter reference."""
        try:
            data = await self._get(
                API_METER_DETAILS,
                {"accountReference": self._account_reference},
            )
        except Exception as err:
            _LOGGER.warning("Could not retrieve meter reference: %s", err)
            return
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return
        self._meter_details = data
        self._meter_reference = data.get("meterReference") or self._meter_reference

    async def _fetch_account_dates(self) -> None:
        """Resolve the account move-in / move-out dates.

        Yorkshire Water's daily-consumption endpoint requires `moveInDate` and
        `moveOutDate` alongside the requested range. The portal itself takes
        them from the property record (`accountStartDate` / `accountEndDate`),
        falling back to the meter details for accounts with no property list.
        """
        move_in: date | None = None
        move_out: date | None = None

        properties = self._iter_properties(await self._safe_get(API_PROPERTIES))
        prop = self._pick_property(properties)
        if prop:
            move_in = _parse_date(prop.get("accountStartDate"))
            move_out = _parse_date(prop.get("accountEndDate"))

        details = self._meter_details
        if details is None:
            details = await self._safe_get(
                API_METER_DETAILS, {"accountReference": self._account_reference}
            )
            if isinstance(details, list):
                details = details[0] if details else {}
            if isinstance(details, dict):
                self._meter_details = details

        if isinstance(details, dict):
            move_in = move_in or _parse_date(details.get("startDate"))
            move_out = move_out or _parse_date(details.get("currentDate"))
            if not self._meter_reference:
                self._meter_reference = details.get("meterReference")

        self._move_in_date = move_in
        self._move_out_date = move_out
        self._dates_fetched = True
        _LOGGER.debug(
            "Yorkshire Water account dates: move_in=%s, move_out=%s",
            self._move_in_date,
            self._move_out_date,
        )

    def _pick_property(self, properties: list) -> dict | None:
        """Pick the property this account reference belongs to."""
        candidates = [p for p in properties if isinstance(p, dict)]
        if not candidates:
            return None
        for prop in candidates:
            if str(prop.get("accountReference", "")) == str(self._account_reference):
                return prop
        if len(candidates) == 1:
            return candidates[0]
        return None

    @staticmethod
    def _iter_properties(payload: object) -> list:
        """Return the property records from a properties/properties-detail payload."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for value in payload.values():
                if isinstance(value, list):
                    return value
            if payload.get("accountReference") or payload.get("accountStartDate"):
                return [payload]
        return []

    async def _safe_get(self, url: str, params: dict | None = None) -> object:
        """GET that returns None instead of raising."""
        try:
            return await self._get(url, params or {})
        except Exception as err:  # noqa: BLE001 - dates are best effort
            _LOGGER.debug("Optional request to %s failed: %s", url, err)
            return None

    async def _get(self, url: str, params: dict) -> dict | list:
        """Authenticated GET with single token refresh retry on 401."""
        session = self._get_session()
        headers = {
            "Authorization": f"Bearer {self._auth.access_token}",
            "Accept": "application/json",
        }
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 401:
                try:
                    await self._auth.async_refresh()
                except PermissionError:
                    self._auth.access_token = None
                    await self._ensure_token()
                headers["Authorization"] = f"Bearer {self._auth.access_token}"
                async with session.get(url, headers=headers, params=params) as r2:
                    if r2.status != 200:
                        raise ConnectionError(await self._error_detail(url, r2))
                    return await r2.json()
            if resp.status != 200:
                raise ConnectionError(await self._error_detail(url, resp))
            return await resp.json()

    @staticmethod
    async def _error_detail(url: str, resp: aiohttp.ClientResponse) -> str:
        """Build an error message including the API's own response body."""
        try:
            body = await resp.text()
        except Exception:  # noqa: BLE001
            body = ""
        detail = f"API error {resp.status} for {url}"
        if body:
            detail += f": {body[:300]}"
        return detail

    async def async_get_daily_consumption(
        self, start: date, end: date, time_period: int = 1
    ) -> dict:
        """Fetch daily consumption for a date range.

        time_period=1 for month view, 0 for week view.

        The endpoint also requires moveInDate and moveOutDate — the account's
        move-in and move-out dates. Omitting them makes Yorkshire Water answer
        HTTP 400.
        """
        await self._ensure_token()

        move_in = self._move_in_date or DATA_FLOOR_DATE
        if move_in < DATA_FLOOR_DATE:
            move_in = DATA_FLOOR_DATE
        move_out = self._move_out_date or date.today()
        if move_out < move_in:
            move_out = move_in

        # The portal never asks for data outside the account's active window.
        if start < move_in:
            start = move_in
        if end > move_out:
            end = move_out
        if end < move_in:
            end = move_in

        params = {
            "meterReference": self._meter_reference,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "moveInDate": move_in.isoformat(),
            "moveOutDate": move_out.isoformat(),
            "timePeriod": time_period,
        }
        data = await self._get(API_DAILY, params)
        if isinstance(data, list):
            return {"dailyUsageData": data}
        if not isinstance(data, dict):
            raise ConnectionError(f"Unexpected response from {API_DAILY}")
        return data

    async def async_get_your_usage(self) -> list:
        """Fetch monthly summary — [0] this month, [1] last month."""
        await self._ensure_token()
        params = {"meterReference": self._meter_reference}
        data = await self._get(API_YOUR_USAGE, params)
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list):
                    return value
            return []
        return data

    async def async_close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        await self._auth.async_close()
