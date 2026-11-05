#!/usr/bin/env python3
"""Probe the Yorkshire Water customer API to reproduce and verify the fix.

Uses only the standard library so it can run anywhere Python 3.9+ exists
(including inside the Home Assistant container).

It logs in with the credentials of the account, then calls the smart meter
endpoints the integration uses and prints the HTTP status and a short body
for each, so the required query parameters can be seen directly.

Usage:
    python3 tools/yw_probe.py                 # prompts for email/password
    python3 tools/yw_probe.py --account 12345 # override the account reference
    python3 tools/yw_probe.py --creds /config/.storage/core.config_entries
                                         # read credentials from an HA store
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

AUTH_BASE = "https://login.yorkshirewater.com"
AUTHORIZE_URL = f"{AUTH_BASE}/connect/authorize"
TOKEN_URL = f"{AUTH_BASE}/connect/token"
PORTAL_BASE = "https://my.yorkshirewater.com"
API_BASE = f"{PORTAL_BASE}/api/account/smartmeter"
CLIENT_ID = "css-onlineaccount-fe"
REDIRECT_URI = f"{PORTAL_BASE}/account/callback/response"
SCOPES = "openid user-names css-onlineaccount-api css-registration-api"
DATA_FLOOR = date(2025, 10, 1)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/120.0.0.0 Safari/537.36"
)


def make_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA), ("Accept-Language", "en-GB,en;q=0.9")]
    return opener


def open_url(opener, url, data=None, headers=None, allow_redirects=True):
    """Return (status, body, final_url) for a request."""
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        resp = opener.open(req, timeout=30)
        body = resp.read().decode("utf-8", "replace")
        return resp.status, body, resp.geturl()
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")
        return err.code, body, url


def extract_csrf(html: str) -> str:
    m = re.search(
        r'<input[^>]+name="__RequestVerificationToken"[^>]+value="([^"]+)"', html
    )
    if m:
        return m.group(1)
    m = re.search(
        r'<input[^>]+value="([^"]+)"[^>]+name="__RequestVerificationToken"', html
    )
    return m.group(1) if m else ""


def login(opener, email: str, password: str) -> str:
    """Run the PKCE login flow and return the access token."""
    verifier = base64.urlsafe_b64encode(os.urandom(40)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "response_mode": "query",
    }
    auth_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    status, html, login_url = open_url(opener, auth_url)
    print(f"  authorize -> {status} {login_url}")
    csrf = extract_csrf(html)
    if not csrf:
        raise SystemExit("Could not extract the CSRF token from the login page.")

    payload = urllib.parse.urlencode(
        {
            "Email": email,
            "Password": password,
            "g-recaptcha-response": "",
            "RedirectUrl": f"{PORTAL_BASE}/account",
            "__RequestVerificationToken": csrf,
        }
    ).encode()
    status, body, url = open_url(
        opener,
        login_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    print(f"  login POST -> {status} {url}")
    if status >= 400:
        raise SystemExit("Login POST failed.")

    status, body, final_url = open_url(opener, auth_url)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
    if "code" not in query:
        raise SystemExit(f"No authorisation code in the callback URL: {final_url}")
    code = query["code"][0]

    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
    ).encode()
    status, body, _ = open_url(
        opener,
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if status != 200:
        raise SystemExit(f"Token exchange failed ({status}): {body[:300]}")
    return json.loads(body)["access_token"]


def api_get(opener, token: str, path: str, params: dict) -> tuple[int, str]:
    url = f"{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        resp = opener.open(req, timeout=30)
        return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


def parse_date(value):
    if not value:
        return None
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def read_ha_credentials(path: str) -> tuple[str, str, str | None]:
    """Pull email, password and account reference out of an HA storage file."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for entry in data.get("data", {}).get("entries", []):
        if entry.get("domain") != "yorkshire_water":
            continue
        d = entry.get("data", {})
        return d.get("email", ""), d.get("password", ""), d.get("account_reference")
    raise SystemExit("No yorkshire_water config entry found in that file.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--account")
    ap.add_argument("--creds", help="HA .storage/core.config_entries file")
    args = ap.parse_args()

    email, password, account = args.email, args.password, args.account
    if args.creds:
        c_email, c_password, c_account = read_ha_credentials(args.creds)
        email = email or c_email
        password = password or c_password
        account = account or c_account
    email = email or input("Yorkshire Water email: ").strip()
    password = password or getpass.getpass("Yorkshire Water password: ")
    if not account:
        account = input("Account reference: ").strip()
    account = account.replace(" ", "").strip()

    opener = make_opener()
    print("== login")
    token = login(opener, email, password)
    print("  token acquired")

    print("== meter-details")
    status, body = api_get(
        opener,
        token,
        f"{API_BASE}/meter-details",
        {"accountReference": account},
    )
    print(f"  status {status}")
    print(f"  body   {body[:600]}")
    meter_reference = None
    details = {}
    if status == 200:
        try:
            details = json.loads(body)
            if isinstance(details, list):
                details = details[0] if details else {}
            meter_reference = details.get("meterReference")
        except json.JSONDecodeError:
            pass
    meter_reference = meter_reference or account

    print("== properties")
    status, body = api_get(opener, token, f"{PORTAL_BASE}/api/account/properties", {})
    print(f"  status {status}")
    print(f"  body   {body[:600]}")
    props = []
    if status == 200:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                for value in parsed.values():
                    if isinstance(value, list):
                        parsed = value
                        break
            props = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            props = []

    account_start = None
    account_end = None
    for prop in props:
        if not isinstance(prop, dict):
            continue
        if account and str(prop.get("accountReference", "")) != account:
            continue
        account_start = parse_date(prop.get("accountStartDate"))
        account_end = parse_date(prop.get("accountEndDate"))
        break
    if account_start is None and props and isinstance(props[0], dict):
        account_start = parse_date(props[0].get("accountStartDate"))
        account_end = parse_date(props[0].get("accountEndDate"))

    meter_start = parse_date(details.get("startDate"))
    meter_current = parse_date(details.get("currentDate"))
    today = date.today()
    month_start = today.replace(day=1)

    print("== daily-consumption variants")
    base = {
        "meterReference": meter_reference,
        "startDate": month_start.isoformat(),
        "endDate": today.isoformat(),
        "timePeriod": 1,
    }
    variants = {
        "A: as the integration does it (no moveInDate/moveOutDate)": base,
        "B: + moveInDate=accountStartDate, moveOutDate=today": {
            **base,
            "moveInDate": (account_start or meter_start or DATA_FLOOR).isoformat(),
            "moveOutDate": today.isoformat(),
        },
        "C: + moveInDate=meter startDate, moveOutDate=currentDate": {
            **base,
            "moveInDate": (meter_start or DATA_FLOOR).isoformat(),
            "moveOutDate": (meter_current or today).isoformat(),
        },
        "D: + moveInDate=2025-10-01 floor, moveOutDate=today": {
            **base,
            "moveInDate": DATA_FLOOR.isoformat(),
            "moveOutDate": today.isoformat(),
        },
    }
    for label, params in variants.items():
        status, body = api_get(opener, token, f"{API_BASE}/daily-consumption", params)
        print(f"  {label}\n    -> status {status}  {body[:300]}")

    print("== meter reference sweep (with move dates)")
    move_in = (account_start or meter_start or DATA_FLOOR).isoformat()
    move_out = today.isoformat()
    candidates = []
    for ref in (
        meter_reference,
        account,
        f"{account}01",
        f"{account}00",
        account[:15] if len(account) > 15 else None,
        f"{account[:15]}01" if len(account) > 15 else None,
    ):
        if ref and ref not in candidates:
            candidates.append(ref)
    for ref in candidates:
        params = {
            "meterReference": ref,
            "startDate": month_start.isoformat(),
            "endDate": today.isoformat(),
            "moveInDate": move_in,
            "moveOutDate": move_out,
            "timePeriod": 1,
        }
        status, body = api_get(opener, token, f"{API_BASE}/daily-consumption", params)
        print(f"  meterReference={ref!r} -> status {status}  {body[:200]}")

    print("== your-usage")
    status, body = api_get(
        opener, token, f"{API_BASE}/your-usage", {"meterReference": meter_reference}
    )
    print(f"  status {status}  {body[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
