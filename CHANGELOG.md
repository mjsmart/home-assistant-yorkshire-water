# Changelog

## 1.3.0 - sensors for the Home Assistant Energy dashboard

The Energy dashboard's water section only offers sensors that measure a
*cumulative* amount and carry the matching device classes - the integration's
sensors were per-period values with no device class, so none of them showed up
in the picker ("Pick a sensor which measures water consumption in either of
CCF, ft3, gal, L, MCF, m3").

- **`sensor.py`** - two new sensors:
  - `sensor.yorkshire_water_total_consumption` - litres consumed since the
    account opened, `device_class: water`, `state_class: total_increasing`.
  - `sensor.yorkshire_water_total_cost` - the matching cost,
    `device_class: monetary`, `state_class: total_increasing`.
- **`client.py`** - the lifetime totals are read from the `yearly-consumption`
  endpoint (one call per calendar year, summed) with a fallback to the daily
  series, and both envelopes the API uses are handled.
- **`coordinator.py`** - the totals never decrease, so the Energy dashboard
  does not see a negative delta when Yorkshire Water revises a past reading.

Add them in *Settings -> Dashboards -> Energy -> Water*: the consumption
sensor and, if you want the cost breakdown, the cost sensor.

## 1.2.0 - clean entity names

The entities were named twice over: the device was called "Yorkshire Water
Smart Meter" and each entity carried its own "Yorkshire Water ..." prefix, so
Home Assistant showed *Yorkshire Water Smart Meter Yorkshire Water Last Reading
Litres* and the entity ids ran to
`sensor.yorkshire_water_smart_meter_yorkshire_water_last_reading_litres`.

- **`sensor.py` / `binary_sensor.py`** - the entities now set
  `has_entity_name`, so their name is relative to the device, and the device
  is called "Yorkshire Water". The entity ids are now the ones the README
  documents: `sensor.yorkshire_water_last_reading_litres`,
  `sensor.yorkshire_water_this_month_cost`,
  `binary_sensor.yorkshire_water_continuous_flow_alarm` and so on.

The unique ids are unchanged, so no entity is duplicated - the existing
entities are renamed in place. Anything that referenced the old, doubled entity
ids (dashboards, automations, recorder history) needs updating.

## 1.1.0 - fix the "connection error" that stops every sensor

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
