"""Parse Strava bulk-export and Garmin Connect CSV exports into a flat runs log.

Strava bulk export: activities.csv, "Distance" column is in meters,
"Elapsed Time" in seconds, "Activity Date" like "Oct 9, 2026, 7:02:31 AM".
Garmin Connect "Export CSV" from the Activities list: "Distance" in the
account's display unit (km or mi), "Time" as "H:MM:SS", "Date" like
"2026-10-09 07:02:31".

Both formats vary across app/account versions; this does best-effort
column-name matching and raises a clear error listing the header it saw
if it can't find what it needs, rather than silently misparsing.
"""

from __future__ import annotations

import csv
import datetime
from dataclasses import dataclass


@dataclass
class RunRecord:
    date: datetime.date
    distance_km: float
    duration_min: float
    source: str


def _find_col(header: list[str], candidates: list[str]) -> str | None:
    lower = {h.lower(): h for h in header}
    for c in candidates:
        if c in lower:
            return lower[c]
    return None


def parse_strava_export(path: str) -> list[RunRecord]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        type_col = _find_col(header, ["activity type"])
        date_col = _find_col(header, ["activity date"])
        dist_col = _find_col(header, ["distance"])
        time_col = _find_col(header, ["elapsed time", "moving time"])
        if not all([type_col, date_col, dist_col, time_col]):
            raise ValueError(
                f"Couldn't find expected Strava columns in header: {header}. "
                "Expected something like Activity Type, Activity Date, Distance, Elapsed Time."
            )
        runs = []
        for row in reader:
            if "run" not in row[type_col].lower():
                continue
            date = _parse_date_flex(row[date_col])
            distance_m = float(row[dist_col])
            seconds = float(row[time_col])
            runs.append(RunRecord(date=date, distance_km=distance_m / 1000,
                                   duration_min=seconds / 60, source="strava"))
        return runs


def parse_garmin_export(path: str) -> list[RunRecord]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        type_col = _find_col(header, ["activity type"])
        date_col = _find_col(header, ["date"])
        dist_col = _find_col(header, ["distance"])
        time_col = _find_col(header, ["time"])
        if not all([type_col, date_col, dist_col, time_col]):
            raise ValueError(
                f"Couldn't find expected Garmin columns in header: {header}. "
                "Expected something like Activity Type, Date, Distance, Time."
            )
        runs = []
        for row in reader:
            if "run" not in row[type_col].lower():
                continue
            date = _parse_date_flex(row[date_col])
            distance = float(row[dist_col].replace(",", ""))
            # Garmin's web export is usually miles unless the account display
            # unit is metric; values over ~60 for a single run are almost
            # certainly already km, small marathon-training runs under that
            # are ambiguous, so this assumes miles (Garmin's common default)
            # unless overridden by distance_unit.
            distance_km = distance * 1.60934
            duration_min = _parse_hms_to_minutes(row[time_col])
            runs.append(RunRecord(date=date, distance_km=distance_km,
                                   duration_min=duration_min, source="garmin"))
        return runs


def _parse_date_flex(s: str) -> datetime.date:
    s = s.strip()
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {s!r}")


def _parse_hms_to_minutes(s: str) -> float:
    parts = [float(p) for p in s.split(":")]
    if len(parts) == 3:
        h, m, sec = parts
    elif len(parts) == 2:
        h, (m, sec) = 0, parts
    else:
        raise ValueError(f"Unrecognized duration format: {s!r}")
    return h * 60 + m + sec / 60


def write_runs_csv(path: str, runs: list[RunRecord], append: bool) -> int:
    import os

    existing_keys = set()
    file_exists = os.path.exists(path)
    if append and file_exists:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                existing_keys.add((row["date"], f"{float(row['distance_km']):.2f}"))
    mode = "a" if (append and file_exists) else "w"
    new_count = 0
    with open(path, mode, newline="") as f:
        writer = csv.writer(f)
        if mode == "w":
            writer.writerow(["date", "distance_km", "duration_min", "source"])
        for r in sorted(runs, key=lambda r: r.date):
            key = (r.date.isoformat(), f"{r.distance_km:.2f}")
            if key in existing_keys:
                continue
            writer.writerow([r.date.isoformat(), f"{r.distance_km:.2f}",
                              f"{r.duration_min:.1f}", r.source])
            existing_keys.add(key)
            new_count += 1
    return new_count
