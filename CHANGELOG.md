# Changelog

## 1.1.0 — fix the "connection error" that stops every sensor

Yorkshire Water's smart meter `daily-consumption` endpoint answers **HTTP 400**
unless the request also carries the account's `moveInDate` and `moveOutDate`
alongside `meterReference`, `startDate`, `endDate` and `timePeriod`. The portal
itself always sends them (see the `GET_DAILY_CONSUMPTION` call in the
customer portal bundle), so an integration that omits them never gets data —
the config entry stays in `setup_retry` and no entity is created.

Changes:

- **`client.py`** — resolve the account's move-in / move-out dates from
  `/api/account/properties` (`accountStartDate` / `accountEndDate`), falling
  back to the meter details (`startDate` / `currentDate`), and send them with
  every `daily-consumption` request. The requested range is clamped to the
  account's active window, and to the earliest date Yorkshire Water still
  serves data for (2025-10-01).
- **`client.py`** — API errors now include the response body, so the log shows
  what Yorkshire Water actually complained about.
- **`config_flow.py`** — the account reference is tried as given, then as its
  first 15 digits, then its first 8, which fixes the `cannot_discover` error
  for account numbers that carry a suffix on the bill.
- **`coordinator.py`** — tolerant of unexpected payload shapes, and the
  update error messages carry the underlying reason.

## 1.0.0 — upstream release

Unmodified upstream `ussy1995/home-assistant-yorkshire-water` v1.0.0.
