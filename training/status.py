"""Compare logged actual runs against the generated schedule, week by week."""

from __future__ import annotations

import csv
import datetime
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
