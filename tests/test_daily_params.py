#!/usr/bin/env python3
"""Offline check of the daily-consumption request the client builds.

Stubs out aiohttp and homeassistant so the module can be imported without the
Home Assistant runtime, then asserts the query parameters Yorkshire Water
needs are present and correctly clamped.

Run: python3 tests/test_daily_params.py
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "yorkshire_water"


def stub_modules() -> None:
    """Provide the few imports the client module needs."""
    aiohttp = types.ModuleType("aiohttp")

    class ClientSession:  # noqa: D401 - stub
        closed = True

    class ClientResponse:  # noqa: D401 - stub
        status = 200

    aiohttp.ClientSession = ClientSession
    aiohttp.ClientResponse = ClientResponse
    aiohttp.CookieJar = lambda *a, **k: object()
    sys.modules.setdefault("aiohttp", aiohttp)

    ha = types.ModuleType("homeassistant")
    const = types.ModuleType("homeassistant.const")
    const.CONF_EMAIL = "email"
    const.CONF_PASSWORD = "password"
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    ha.const = const
    ha.core = core
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.const", const)
    sys.modules.setdefault("homeassistant.core", core)


def load_package():
    """Import the integration's client and const modules."""
    stub_modules()
    pkg = types.ModuleType("yorkshire_water")
    pkg.__path__ = [str(PKG)]
    sys.modules["yorkshire_water"] = pkg

    for name in ("const", "auth", "client"):
        spec = importlib.util.spec_from_file_location(
            f"yorkshire_water.{name}", PKG / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"yorkshire_water.{name}"] = module
        spec.loader.exec_module(module)
    return sys.modules["yorkshire_water.client"]


def main() -> int:
    client_mod = load_package()
    client = client_mod.YorkshireWaterClient(
        None,
        {
            "email": "a@b.c",
            "password": "pw",
            "account_reference": "5364581401",
            "meter_reference": "5364581401",
        },
    )

    captured: dict = {}

    async def fake_get(url, params):
        captured["url"] = url
        captured["params"] = params
        return {"dailyUsageData": []}

    client._get = fake_get
    client._auth.access_token = "test-token"  # skip the login flow

    async def run():
        # Account opened in 2019, so the API's data floor applies.
        client._move_in_date = date(2019, 3, 1)
        client._move_out_date = None
        await client.async_get_daily_consumption(date(2026, 11, 1), date(2026, 11, 5))

    import asyncio

    asyncio.run(run())

    params = captured["params"]
    print("request params:", params)

    failures = []

    def check(name: str, ok: bool) -> None:
        print(("  PASS " if ok else "  FAIL ") + name)
        if not ok:
            failures.append(name)

    check("moveInDate present", "moveInDate" in params)
    check("moveOutDate present", "moveOutDate" in params)
    check(
        "moveInDate clamped to the API data floor",
        params.get("moveInDate") == "2025-10-01",
    )
    check("moveOutDate is today", params.get("moveOutDate") == date.today().isoformat())
    check("startDate kept", params.get("startDate") == "2026-11-01")
    check("endDate kept", params.get("endDate") == "2026-11-05")
    check("timePeriod present", params.get("timePeriod") == 1)

    # A request that starts before the account was opened is pulled forward.
    captured.clear()

    async def run2():
        client._move_in_date = date(2026, 10, 20)
        await client.async_get_daily_consumption(date(2026, 10, 1), date(2026, 10, 25))

    asyncio.run(run2())
    params2 = captured["params"]
    print("clamped params:", params2)
    check("startDate pulled to moveInDate", params2.get("startDate") == "2026-10-20")

    # Lifetime totals: summed from the yearly endpoint, one call per year.
    yearly_calls = []

    async def fake_yearly(url, params):
        yearly_calls.append(params)
        year = params["year"]
        if year == str(date.today().year):
            return {"totalConsumption": 1779.0, "totalCost": 8.31}
        return {"totalConsumption": 13175.0, "totalCost": 61.53}

    client._get = fake_yearly
    client._move_in_date = date(2025, 10, 1)

    async def run3():
        return await client.async_get_lifetime_totals()

    litres, cost = asyncio.run(run3())
    print("lifetime totals:", litres, cost, "yearly calls:", len(yearly_calls))
    check("yearly endpoint called once per year", len(yearly_calls) == 2)
    check("total litres summed across years", litres == 14954.0)
    check("total cost summed across years", cost == 69.84)
    check("yearly call carries moveInDate", "moveInDate" in yearly_calls[0])
    check("yearly call carries moveOutDate", "moveOutDate" in yearly_calls[0])

    # A wrapped {"data": {...}} envelope is unwrapped too.
    async def fake_yearly_wrapped(url, params):
        return {"data": {"totalConsumption": 100.0, "totalCost": 1.0}, "statusCode": 200}

    client._get = fake_yearly_wrapped

    async def run4():
        return await client.async_get_lifetime_totals()

    litres2, cost2 = asyncio.run(run4())
    print("wrapped envelope totals:", litres2, cost2)
    check("wrapped envelope unwrapped", litres2 == 200.0)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
