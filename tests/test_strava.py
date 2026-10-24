"""Strava client: OAuth parsing, token refresh, and the CI sync guardrails."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from training import strava

ROOT = Path(__file__).resolve().parents[1]


class AuthTests(unittest.TestCase):
    def test_authorize_url_asks_for_private_runs(self) -> None:
        url = strava.authorize_url("12345")
        self.assertIn("client_id=12345", url)
        self.assertIn("activity%3Aread_all", url)
        self.assertIn("localhost", url)

    def test_parse_redirect_reads_the_code_and_rejects_denial(self) -> None:
        pasted = "http://localhost/exchange_token?state=&code=abc123&scope=read"
        self.assertEqual(strava.parse_redirect(pasted), "abc123")
        self.assertEqual(strava.parse_redirect("abc123"), "abc123")
        with self.assertRaises(strava.StravaError):
            strava.parse_redirect("http://localhost/exchange_token?error=access_denied")
        with self.assertRaises(strava.StravaError):
            strava.parse_redirect("  ")

    def test_refresh_persists_the_rotated_token_and_skips_when_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "auth.json")
            expired = {
                "client_id": "1", "client_secret": "secret", "refresh_token": "old",
                "access_token": "stale", "expires_at": 0,
            }
            response = MagicMock()
            response.json.return_value = {
                "access_token": "fresh", "refresh_token": "rotated", "expires_at": 9_999_999_999,
            }
            response.status_code = 200
            response.text = ""
            with patch.object(strava.requests, "post", return_value=response) as post:
                updated = strava.ensure_access_token(expired, persist_path=path)
            self.assertEqual(updated["refresh_token"], "rotated")
            with open(path) as handle:
                self.assertEqual(json.load(handle)["client_secret"], "secret")
            post.assert_called_once()
            with patch.object(strava.requests, "post", side_effect=AssertionError("should not refresh")):
                again = strava.ensure_access_token(updated, persist_path=path)
            self.assertEqual(again["access_token"], "fresh")

    def test_cache_wins_until_reset(self) -> None:
        cached = {"refresh_token": "rotated"}
        self.assertEqual(strava.resolve_refresh_token(cached, "from-secret", False), "rotated")
        self.assertEqual(strava.resolve_refresh_token(cached, "from-secret", True), "from-secret")
        self.assertEqual(strava.resolve_refresh_token(None, "from-secret", False), "from-secret")

    def test_missing_secrets(self) -> None:
        self.assertEqual(
            strava.env_secrets_missing({"STRAVA_CLIENT_ID": "1", "STRAVA_CLIENT_SECRET": "", "STRAVA_REFRESH_TOKEN": "x"}),
            ["STRAVA_CLIENT_SECRET"],
        )


class FetchTests(unittest.TestCase):
    def test_fetch_keeps_runs_and_stops_on_a_short_page(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.text = ""
        response.json.return_value = [
            {"type": "Run", "id": 1},
            {"type": "Ride", "id": 2},
            {"sport_type": "VirtualRun", "type": "VirtualRun", "id": 3},
        ]
        with patch.object(strava.requests, "get", return_value=response) as get:
            activities = strava.fetch_runs({"access_token": "token"}, 100)
        self.assertEqual([a["id"] for a in activities], [1, 3])
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer token")
        self.assertEqual(get.call_args.kwargs["params"]["after"], 100)

    def test_api_errors_do_not_include_the_token(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.text = "Authorization Error"
        response.raise_for_status.side_effect = __import__("requests").HTTPError("nope")
        with patch.object(strava.requests, "get", return_value=response):
            with self.assertRaises(strava.StravaError) as caught:
                strava.fetch_runs({"access_token": "super-secret-token"}, 0)
        self.assertNotIn("super-secret-token", str(caught.exception))
        self.assertIn("401", str(caught.exception))


class RepoGuardTests(unittest.TestCase):
    def test_secrets_are_gitignored_and_the_run_log_is_not(self) -> None:
        text = (ROOT / ".gitignore").read_text()
        self.assertIn("data/strava_auth.json", text)
        self.assertIn("data/runs.csv", text)
        self.assertIn("books/", text)
        ignored = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
        self.assertNotIn("data/strava_runs.csv", ignored)
        header = (ROOT / "data" / "strava_runs.csv").read_text().splitlines()[0]
        self.assertEqual(header, "date,name,distance_km,moving_time,strava_activity_id")

    def test_regenerate_workflow_commits_outputs_only(self) -> None:
        text = (ROOT / ".github" / "workflows" / "regenerate-site.yml").read_text()
        loaded = yaml.safe_load(text)
        push = loaded[True]["push"]  # YAML 1.1 parses "on" as true
        self.assertEqual(push["branches"], ["main"])
        self.assertEqual(push["paths"], ["data/strava_runs.csv"])
        self.assertIn("workflow_dispatch", loaded[True])
        self.assertEqual(loaded["permissions"]["contents"], "write")
        self.assertEqual(loaded["permissions"]["pages"], "write")
        self.assertEqual(loaded["permissions"]["id-token"], "write")
        self.assertIn("python cli.py sync-site", text)
        self.assertIn("actions/upload-pages-artifact@v3", text)
        self.assertIn("actions/deploy-pages@v4", text)
        self.assertIn("git add -- data/weekly_status.csv docs/index.html docs/.nojekyll", text)
        self.assertNotIn("git add -A", text)
        self.assertNotIn("git add .", text)
        deploy = loaded["jobs"]["deploy"]
        self.assertEqual(deploy["needs"], "regenerate")
        self.assertEqual(deploy["environment"]["name"], "github-pages")
        self.assertNotIn("STRAVA_CLIENT_SECRET", text)
        self.assertNotIn("STRAVA_REFRESH_TOKEN", text)
        pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text()
        self.assertIn("python cli.py sync-site", pages)

    def test_generator_does_not_import_the_api_client(self) -> None:
        source = (ROOT / "cli.py").read_text()
        self.assertNotIn("import strava", source)
        self.assertNotIn("strava-auth", source)
        self.assertNotIn("sync-strava", source)
        self.assertFalse((ROOT / ".github" / "workflows" / "strava-sync.yml").exists())


if __name__ == "__main__":
    unittest.main()
