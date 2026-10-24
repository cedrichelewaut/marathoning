"""Strava API connector: OAuth setup plus pulling recent runs.

Credentials and tokens live in data/strava_auth.json, which is gitignored
(it holds your API client secret and refresh token, never commit it).

One-time setup (see README): create an API app at
https://www.strava.com/settings/api, then run `python cli.py strava-auth`.
After that, `python cli.py sync-strava` pulls new runs any time.
"""

from __future__ import annotations

import datetime
import json
import os
import time
import urllib.parse

import requests

AUTH_PATH = "data/strava_auth.json"
REDIRECT_URI = "http://localhost/exchange_token"
TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"


def authorize_url(client_id: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "activity:read_all",
    }
    return "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode(params)


def load_auth() -> dict | None:
    try:
        with open(AUTH_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_auth(auth: dict) -> None:
    os.makedirs(os.path.dirname(AUTH_PATH), exist_ok=True)
    with open(AUTH_PATH, "w") as f:
        json.dump(auth, f, indent=2)


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret,
        "code": code, "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    data = resp.json()
    return {
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": data["refresh_token"],
        "access_token": data["access_token"],
        "expires_at": data["expires_at"],
        "last_sync_epoch": None,
    }


def ensure_access_token(auth: dict) -> dict:
    """Refreshes the access token if expired, returns the (possibly
    updated) auth dict. Strava access tokens last 6 hours; refresh tokens
    don't expire but Strava may rotate them on refresh."""
    if auth.get("expires_at", 0) > time.time() + 60:
        return auth
    resp = requests.post(TOKEN_URL, data={
        "client_id": auth["client_id"], "client_secret": auth["client_secret"],
        "refresh_token": auth["refresh_token"], "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    data = resp.json()
    auth = {**auth, "access_token": data["access_token"],
            "refresh_token": data["refresh_token"], "expires_at": data["expires_at"]}
    save_auth(auth)
    return auth


def fetch_runs(auth: dict, after_epoch: int) -> list[dict]:
    """Fetches activities after after_epoch, paginated, filtered to runs."""
    runs = []
    page = 1
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    while True:
        resp = requests.get(ACTIVITIES_URL, headers=headers,
                             params={"after": after_epoch, "per_page": 100, "page": page})
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        runs.extend(a for a in batch if a.get("type") == "Run")
        if len(batch) < 100:
            break
        page += 1
    return runs


def to_run_records(activities: list[dict]) -> list:
    from training.importers import RunRecord

    records = []
    for a in activities:
        date = datetime.datetime.fromisoformat(a["start_date_local"].replace("Z", "+00:00")).date()
        records.append(RunRecord(date=date, distance_km=a["distance"] / 1000,
                                  duration_min=a["moving_time"] / 60, source="strava"))
    return records
