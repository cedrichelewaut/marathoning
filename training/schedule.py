"""Generate a week-by-week marathon schedule.

Structure is adapted from "Advanced Marathoning" (Pfitzinger & Douglas),
chapter 9 ("Marathon Training on Up to 55 Miles per Week"): a progressive
mileage build across four blocks (endurance, LT+endurance, race prep,
taper), one long run and one medium-long run per week, rest/cross-train
on the lightest days.

Per the user's preference, every LT/VO2max-interval/hill-sprint session
from the book is replaced with a general-aerobic or marathon-pace (MP)
session instead, since those are the book's two genuinely "hard" workout
types and the fast-running ones. Short strides are kept but marked
optional. Everything before the 18-week block is unstructured, flexible
base-building.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass
class Day:
    date: datetime.date
    workout: str
    distance_km: float | None
    notes: str = ""


@dataclass
class Week:
    index: int  # 1 = race week, counting down; None for base-building weeks
    phase: str
    start_date: datetime.date
    days: list[Day] = field(default_factory=list)

    @property
    def total_km(self) -> float:
        return sum(d.distance_km or 0 for d in self.days)


# Monday-indexed weekly skeleton for the 18-week race-specific block.
# (workout, fraction of weekly MP/long-run emphasis) — distances are derived
# from the week's total target mileage using these fixed fractions, which
# mirror the book's day-to-day balance.
_SKELETON = {
    0: ("Rest or cross-train", 0.0),       # Monday
    1: ("General aerobic", 0.16),          # Tuesday
    2: ("Medium-long run", 0.22),          # Wednesday
    3: ("Rest or cross-train", 0.0),       # Thursday
    4: ("Recovery + optional strides", 0.11),  # Friday
    5: ("Recovery", 0.11),                 # Saturday
    6: ("Long run", 0.40),                 # Sunday (MP segment added in race-prep block)
}

_RACE_PREP_START_WEEKS_OUT = 6  # from here the long/MP run carries marathon-pace miles
_TAPER_START_WEEKS_OUT = 3


def _phase_for_week(weeks_out: int) -> str:
    if weeks_out <= _TAPER_START_WEEKS_OUT:
        return "Taper"
    if weeks_out <= _RACE_PREP_START_WEEKS_OUT:
        return "Race preparation"
    if weeks_out <= 12:
        return "LT+endurance (adapted: general aerobic)"
    return "Endurance"


def _peak_week_index(start_km: float, peak_km: float, n_weeks: int) -> list[float]:
    """Weekly total-km targets, ramping start->peak with every 4th week a
    lighter recovery week, then tapering the final 3 weeks."""
    totals = []
    taper_fracs = {3: 0.75, 2: 0.60, 1: 0.45, 0: 0.35}  # weeks_out: fraction of peak (0=race week)
    build_weeks = n_weeks - len(taper_fracs)
    for i in range(build_weeks):
        progress = i / max(build_weeks - 2, 1)
        target = start_km + (peak_km - start_km) * min(progress, 1.0)
        if (i + 1) % 4 == 0:
            target *= 0.80  # recovery week
        totals.append(round(target))
    for weeks_out in (3, 2, 1, 0):
        totals.append(round(peak_km * taper_fracs[weeks_out]))
    return totals


def generate_18wk_plan(plan_start: datetime.date, race_date: datetime.date,
                        start_km: float, peak_km: float) -> list[Week]:
    n_weeks = ((race_date - plan_start).days // 7) + 1
    weekly_totals = _peak_week_index(start_km, peak_km, n_weeks)
    weeks: list[Week] = []
    for w in range(n_weeks):
        week_start = plan_start + datetime.timedelta(weeks=w)
        weeks_out = n_weeks - w - 1
        phase = _phase_for_week(weeks_out)
        total_km = weekly_totals[w]
        week = Week(index=weeks_out, phase=phase, start_date=week_start)
        for offset, (workout, frac) in _SKELETON.items():
            date = week_start + datetime.timedelta(days=offset)
            dist = round(total_km * frac, 1) if frac else None
            notes = ""
            if workout == "Long run" and weeks_out <= _RACE_PREP_START_WEEKS_OUT and weeks_out > 0:
                mp_km = round((dist or 0) * 0.55, 1)
                notes = f"include ~{mp_km} km at marathon pace, rest easy"
            if workout == "Recovery + optional strides":
                notes = "6-8 x 100m relaxed strides optional, not required"
            if weeks_out == 0:
                workout = "Goal marathon" if offset == 6 else workout
                if offset == 6:
                    dist, notes = 42.2, "race day"
            week.days.append(Day(date=date, workout=workout, distance_km=dist, notes=notes))
        weeks.append(week)
    return weeks


def generate_base_building(start_date: datetime.date, end_before: datetime.date,
                            start_km: float, target_km: float) -> list[Week]:
    """Flexible, easy-only base-building weeks before the structured block.
    No fixed workout days: just a weekly mileage target split across 4-5
    easy runs plus one slightly longer run, left flexible day-to-day."""
    n_weeks = max(0, (end_before - start_date).days // 7)
    weeks: list[Week] = []
    for w in range(n_weeks):
        week_start = start_date + datetime.timedelta(weeks=w)
        progress = w / max(n_weeks - 1, 1)
        total_km = round(start_km + (target_km - start_km) * progress)
        if (w + 1) % 4 == 0:
            total_km = round(total_km * 0.80)
        week = Week(index=None, phase="Base-building", start_date=week_start)
        long_run = round(total_km * 0.28, 1)
        remaining = total_km - long_run
        per_run = round(remaining / 4, 1)
        plan = [("Easy run (flexible day)", per_run)] * 4 + [("Long run (flexible day)", long_run)]
        for offset, (workout, dist) in enumerate(plan):
            date = week_start + datetime.timedelta(days=offset)
            week.days.append(Day(date=date, workout=workout, distance_km=dist,
                                  notes="move to whichever day suits you this week"))
        weeks.append(week)
    return weeks


def write_schedule_csv(path: str, weeks: list[Week]) -> None:
    import csv

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "phase", "weeks_out", "workout", "distance_km", "notes"])
        for week in weeks:
            for day in week.days:
                writer.writerow([day.date.isoformat(), week.phase,
                                  week.index if week.index is not None else "",
                                  day.workout, day.distance_km or "", day.notes])
