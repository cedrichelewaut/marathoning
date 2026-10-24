"""Optional Strava API client. The site does not use this module.

Strava has required a subscription for API apps since June 2026, so the
published schedule does not call the API and does not need tokens.
Actual kilometres come from the tracked file data/strava_runs.csv
(`python cli.py sync-site`). This module stays in the tree for anyone
who later has API access; nothing in the generator imports it.
"""

from __future__ import annotations

import datetime
import json
import os
import time
import urllib.parse

import requests

AUTH_PATH = "data/strava_auth.json"
TOKEN_CACHE_PATH = "data/.strava_token_cache.json"
REDIRECT_URI = "http://localhost/exchange_token"
TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
_TIMEOUT = 30
_MAX_PAGES = 20


class StravaError(RuntimeError):
    """Strava rejected a request. The message is safe to print; it has no tokens."""


def authorize_url(client_id: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "activity:read_all",
    }
    return "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode(params)


def load_auth(path: str = AUTH_PATH) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_auth(auth: dict, path: str = AUTH_PATH) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w") as f:
        json.dump(auth, f, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def parse_redirect(redirected: str) -> str:
    """Pull the OAuth code out of a pasted redirect URL, or return the raw code."""
    redirected = redirected.strip()
    if not redirected:
        raise StravaError("No authorization code provided.")
    if "error=" in redirected:
        query = urllib.parse.urlparse(redirected).query
        message = urllib.parse.parse_qs(query).get("error", ["access_denied"])[0]
        raise StravaError(f"Strava authorization was not granted ({message}).")
    if "code=" in redirected:
        query = urllib.parse.urlparse(redirected).query
        codes = urllib.parse.parse_qs(query).get("code")
        if codes and codes[0]:
            return codes[0]
        # The pasted page can be a 404 whose query isn't on the usual position.
        code = redirected.split("code=")[1].split("&")[0]
        return urllib.parse.unquote(code)
    return redirected


def _check(resp: requests.Response) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        body = (resp.text or "").strip().replace("\n", " ")
        if len(body) > 300:
            body = body[:300] + "…"
        raise StravaError(f"Strava API returned {resp.status_code}: {body}") from exc


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret,
        "code": code, "grant_type": "authorization_code",
    }, timeout=_TIMEOUT)
    _check(resp)
    data = resp.json()
    if "refresh_token" not in data or "access_token" not in data:
        raise StravaError("Strava did not return a token. Check the client id, secret, and code.")
    return {
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": data["refresh_token"],
        "access_token": data["access_token"],
        "expires_at": data.get("expires_at", 0),
        "last_sync_epoch": None,
    }


def ensure_access_token(auth: dict, persist_path: str | None = AUTH_PATH) -> dict:
    """Refreshes the access token if expired, returns the (possibly
    updated) auth dict. Strava access tokens last 6 hours; refresh tokens
    don't expire on a clock but Strava rotates them on every refresh, so
    the new refresh token is written to persist_path when one is given.
    """
    if auth.get("access_token") and auth.get("expires_at", 0) > time.time() + 60:
        return auth
    resp = requests.post(TOKEN_URL, data={
        "client_id": auth["client_id"], "client_secret": auth["client_secret"],
        "refresh_token": auth["refresh_token"], "grant_type": "refresh_token",
    }, timeout=_TIMEOUT)
    _check(resp)
    data = resp.json()
    if "access_token" not in data:
        raise StravaError("Strava did not return an access token. Authorize again.")
    auth = {
        **auth,
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", auth["refresh_token"]),
        "expires_at": data.get("expires_at", 0),
    }
    if persist_path:
        save_auth(auth, persist_path)
    return auth


def env_secrets_missing(environ: dict | None = None) -> list[str]:
    source = os.environ if environ is None else environ
    required = ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")
    return [key for key in required if not str(source.get(key, "")).strip()]


def resolve_refresh_token(cached: dict | None, env_token: str, ignore_cache: bool) -> str:
    """Prefer the cached (possibly rotated) refresh token, unless asked not to."""
    if not ignore_cache and cached and cached.get("refresh_token"):
        return str(cached["refresh_token"])
    return env_token


def is_run(activity: dict) -> bool:
    """Runs, including treadmill / virtual runs. Rides and walks are not."""
    for key in ("sport_type", "type"):
        if "run" in str(activity.get(key) or "").lower():
            return True
    return False


def fetch_runs(auth: dict, after_epoch: int) -> list[dict]:
    """Fetches activities after after_epoch, paginated, filtered to runs."""
    runs = []
    page = 1
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    while page <= _MAX_PAGES:
        resp = requests.get(ACTIVITIES_URL, headers=headers, timeout=_TIMEOUT,
                             params={"after": after_epoch, "per_page": 100, "page": page})
        _check(resp)
        batch = resp.json()
        if not isinstance(batch, list):
            raise StravaError("Strava returned an unexpected activities payload.")
        if not batch:
            break
        runs.extend(a for a in batch if is_run(a))
        if len(batch) < 100:
            break
        page += 1
    return runs


def to_run_records(activities: list[dict]) -> list:
    from training.importers import RunRecord

    records = []
    for activity in activities:
        if not is_run(activity):
            continue
        raw_date = activity.get("start_date_local") or activity.get("start_date")
        distance = activity.get("distance")
        if not raw_date or distance is None:
            continue
        # Strava puts a trailing Z on start_date_local even though the clock
        # time is already local. The first 10 characters are that local date.
        try:
            date = datetime.date.fromisoformat(str(raw_date)[:10])
            distance_m = float(distance)
        except ValueError:
            continue
        moving = activity.get("moving_time")
        if moving is None:
            moving = activity.get("elapsed_time") or 0
        records.append(RunRecord(
            date=date, distance_km=distance_m / 1000,
            duration_min=float(moving) / 60, source="strava",
        ))
    return records
