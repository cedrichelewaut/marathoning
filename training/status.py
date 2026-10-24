"""Compare logged actual runs against the generated schedule, week by week."""

from __future__ import annotations

import csv
import datetime
import re
from dataclasses import dataclass


@dataclass
class WeekStatus:
    week_start: datetime.date
    planned_km: float
    actual_km: float
    long_run_planned_km: float
    long_run_actual_km: float

    @property
    def pct(self) -> float:
        return (self.actual_km / self.planned_km * 100) if self.planned_km else 0.0

    @property
    def verdict(self) -> str:
        if self.pct >= 110:
            return "ahead"
        if self.pct >= 85:
            return "on track"
        return "behind"


def load_schedule(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_runs(path: str) -> list[dict]:
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


# Tracked run log. No tokens. strava_activity_id is the dedupe key.
STRAVA_RUN_COLUMNS = ("date", "name", "distance_km", "moving_time", "strava_activity_id")
_MOVING_TIME = re.compile(r"^\d+:[0-5]\d:[0-5]\d$")


def load_strava_runs(path: str) -> tuple[list[dict], int]:
    """Read data/strava_runs.csv for week totals.

    Returns (run rows for week_status, number of duplicate activity ids skipped).
    A repeated strava_activity_id counts once, first row wins. The file is the
    only actual-km input the site needs; private exports and API tokens are not.
    """
    try:
        handle = open(path, newline="", encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Missing {path}. The site reads actual km from that tracked CSV."
        ) from exc
    runs: list[dict] = []
    seen: set[str] = set()
    skipped = 0
    with handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        missing = [col for col in STRAVA_RUN_COLUMNS if col not in header]
        if missing:
            raise ValueError(
                f"{path} is missing columns {missing}. "
                f"Expected {', '.join(STRAVA_RUN_COLUMNS)}."
            )
        for line_no, row in enumerate(reader, start=2):
            if not any((row.get(col) or "").strip() for col in STRAVA_RUN_COLUMNS):
                continue
            activity_id = (row.get("strava_activity_id") or "").strip()
            if not activity_id:
                raise ValueError(f"{path}:{line_no}: strava_activity_id is required (it dedupes runs).")
            if activity_id in seen:
                skipped += 1
                continue
            seen.add(activity_id)
            date_text = (row.get("date") or "").strip()
            try:
                datetime.date.fromisoformat(date_text)
            except ValueError as exc:
                raise ValueError(f"{path}:{line_no}: date must be YYYY-MM-DD, got {date_text!r}.") from exc
            try:
                distance = float((row.get("distance_km") or "").strip())
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{line_no}: distance_km must be a number, got {row.get('distance_km')!r}."
                ) from exc
            if distance < 0:
                raise ValueError(f"{path}:{line_no}: distance_km cannot be negative.")
            moving = (row.get("moving_time") or "").strip()
            if not _MOVING_TIME.match(moving):
                raise ValueError(
                    f"{path}:{line_no}: moving_time must be h:mm:ss, got {moving!r}."
                )
            runs.append({"date": date_text, "distance_km": f"{distance:.4f}"})
    return runs, skipped


def week_status(schedule_rows: list[dict], run_rows: list[dict],
                 week_start: datetime.date) -> WeekStatus:
    week_end = week_start + datetime.timedelta(days=6)

    def in_week(d: str) -> bool:
        date = datetime.date.fromisoformat(d)
        return week_start <= date <= week_end

    planned = [r for r in schedule_rows if in_week(r["date"])]
    actual = [r for r in run_rows if in_week(r["date"])]

    planned_km = sum(float(r["distance_km"]) for r in planned if r["distance_km"])
    actual_km = sum(float(r["distance_km"]) for r in actual)

    long_planned = max((float(r["distance_km"]) for r in planned if r["distance_km"]), default=0.0)
    long_actual = max((float(r["distance_km"]) for r in actual), default=0.0)

    return WeekStatus(week_start=week_start, planned_km=planned_km, actual_km=actual_km,
                       long_run_planned_km=long_planned, long_run_actual_km=long_actual)


def current_week_start(today: datetime.date) -> datetime.date:
    return today - datetime.timedelta(days=today.weekday())


def all_week_starts(schedule_rows: list[dict]) -> list[datetime.date]:
    starts = set()
    for r in schedule_rows:
        d = datetime.date.fromisoformat(r["date"])
        starts.add(d - datetime.timedelta(days=d.weekday()))
    return sorted(starts)


def all_weeks_status(schedule_rows: list[dict], run_rows: list[dict]) -> list[WeekStatus]:
    return [week_status(schedule_rows, run_rows, ws) for ws in all_week_starts(schedule_rows)]


def write_weekly_status_csv(path: str, weeks: list[WeekStatus]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["week_start", "planned_km", "actual_km", "pct", "verdict",
                          "long_run_planned_km", "long_run_actual_km"])
        for w in weeks:
            writer.writerow([w.week_start.isoformat(), f"{w.planned_km:.1f}",
                              f"{w.actual_km:.1f}", f"{w.pct:.0f}", w.verdict,
                              f"{w.long_run_planned_km:.1f}", f"{w.long_run_actual_km:.1f}"])


def load_weekly_status(path: str) -> dict[str, dict]:
    try:
        with open(path, newline="") as f:
            return {row["week_start"]: row for row in csv.DictReader(f)}
    except FileNotFoundError:
        return {}
