"""Sensors for Yorkshire Water integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_NAME
from .coordinator import YorkshireWaterDataUpdateCoordinator

# (key, name, unit, state_class, icon, device_class)
SENSOR_DESCRIPTIONS = [
    # Last reading
    ("last_reading_date",        "Last Reading Date",              None,                None,                             "mdi:calendar", None),
    ("last_reading_litres",      "Last Reading Litres",            UnitOfVolume.LITERS, SensorStateClass.MEASUREMENT,     "mdi:water",    None),
    ("last_reading_cost",        "Last Reading Cost",              "GBP",               SensorStateClass.MEASUREMENT,     "mdi:currency-gbp", None),
    # This month
    ("this_month_litres",        "This Month Litres",              UnitOfVolume.LITERS, SensorStateClass.MEASUREMENT,     "mdi:water",    None),
    ("this_month_cost",          "This Month Cost",                "GBP",               SensorStateClass.MEASUREMENT,     "mdi:currency-gbp", None),
    # Last month
    ("last_month_litres",        "Last Month Litres",              UnitOfVolume.LITERS, SensorStateClass.MEASUREMENT,     "mdi:water",    None),
    ("last_month_cost",          "Last Month Cost",                "GBP",               SensorStateClass.MEASUREMENT,     "mdi:currency-gbp", None),
    # Weekly
    ("weekly_litres",            "Weekly Litres",                  UnitOfVolume.LITERS, SensorStateClass.MEASUREMENT,     "mdi:water",    None),
    ("weekly_cost",              "Weekly Cost",                    "GBP",               SensorStateClass.MEASUREMENT,     "mdi:currency-gbp", None),
    ("weekly_daily_avg_litres",  "Weekly Daily Average Litres",    UnitOfVolume.LITERS, SensorStateClass.MEASUREMENT,     "mdi:water-percent", None),
    # MTD averages
    ("daily_avg_litres_mtd",     "Daily Average Litres (MTD)",     UnitOfVolume.LITERS, SensorStateClass.MEASUREMENT,     "mdi:water-percent", None),
    ("daily_avg_cost_mtd",       "Daily Average Cost (MTD)",       "GBP",               SensorStateClass.MEASUREMENT,     "mdi:currency-gbp", None),
    # Lifetime totals - these carry the device classes the Home Assistant
    # Energy dashboard needs (water consumption and its cost).
    ("total_litres",             "Total Consumption",              UnitOfVolume.LITERS, SensorStateClass.TOTAL_INCREASING, "mdi:water",    SensorDeviceClass.WATER),
    ("total_cost",               "Total Cost",                     "GBP",               SensorStateClass.TOTAL_INCREASING, "mdi:currency-gbp", SensorDeviceClass.MONETARY),
]


def _f(value: object) -> float | None:
    """Coerce API string/numeric value to float, return None if not possible."""
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        YorkshireWaterSensor(coordinator, entry, *d) for d in SENSOR_DESCRIPTIONS
    )


class YorkshireWaterSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator: YorkshireWaterDataUpdateCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        unit: str | None,
        state_class: SensorStateClass | None,
        icon: str,
        device_class: SensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_has_entity_name = True
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer="Yorkshire Water",
            model="Smart Meter",
        )

    @property
    def native_value(self) -> StateType | None:
        data = self.coordinator.data
        if not data:
            return None

        # ── Last reading (from pre-processed last_complete_day dict) ──────────
        if self._key in ("last_reading_date", "last_reading_litres", "last_reading_cost"):
            last_day = data.get("last_complete_day")
            if not last_day:
                return None
            if self._key == "last_reading_date":
                return last_day.get("date")
            if self._key == "last_reading_litres":
                return _f(last_day.get("totalConsumptionLitres"))
            if self._key == "last_reading_cost":
                return _f(last_day.get("totalCostIncludingSewerage"))

        # ── All other sensors map directly to coordinator data keys ───────────
        key_map = {
            "this_month_litres":       "this_month_litres",
            "this_month_cost":         "this_month_cost_inc_sewerage",
            "last_month_litres":       "last_month_litres",
            "last_month_cost":         "last_month_cost_inc_sewerage",
            "weekly_litres":           "weekly_litres",
            "weekly_cost":             "weekly_cost",
            "weekly_daily_avg_litres": "weekly_daily_avg_litres",
            "daily_avg_litres_mtd":    "mtd_daily_litres_average",
            "daily_avg_cost_mtd":      "mtd_daily_cost_average",
            "total_litres":            "total_litres",
            "total_cost":              "total_cost",
        }
        coord_key = key_map.get(self._key)
        if coord_key:
            return _f(data.get(coord_key))

        return None