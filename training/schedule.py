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


# Monday-indexed weekly skeletons, keyed by how many days a week you
# actually run. Only weeks within HIGH_MILEAGE_RATIO of peak mileage use
# the 5-run skeleton; everything else runs 3-4x/week with bigger individual
# runs to still hit the weekly target, since 5 runs/week isn't sustainable
# except in the heaviest weeks.
_SKELETON_3 = {
    2: ("Medium-long run", 0.32),   # Wednesday
    4: ("General aerobic", 0.28),   # Friday
    6: ("Long run", 0.40),          # Sunday
}
_SKELETON_4 = {
    1: ("General aerobic", 0.18),   # Tuesday
    2: ("Medium-long run", 0.22),   # Wednesday
    4: ("General aerobic", 0.18),   # Friday
    6: ("Long run", 0.42),          # Sunday
}
_SKELETON_5 = {
    1: ("General aerobic", 0.16),          # Tuesday
    2: ("Medium-long run", 0.22),           # Wednesday
    4: ("Recovery + optional strides", 0.11),  # Friday
    5: ("Recovery", 0.11),                  # Saturday
    6: ("Long run", 0.40),                  # Sunday
}

HIGH_MILEAGE_RATIO = 0.85  # only weeks at/above this fraction of peak get 5 runs
MID_MILEAGE_RATIO = 0.55   # above this, 4 runs; below, 3 runs


def _skeleton_for_week(total_km: float, peak_km: float) -> dict:
    ratio = total_km / peak_km if peak_km else 0
    if ratio >= HIGH_MILEAGE_RATIO:
        return _SKELETON_5
    if ratio >= MID_MILEAGE_RATIO:
        return _SKELETON_4
    return _SKELETON_3


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
        skeleton = _skeleton_for_week(total_km, peak_km)
        for offset in range(7):
            workout, frac = skeleton.get(offset, ("Rest or cross-train", 0.0))
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
                            start_km: float, target_km: float, peak_km: float) -> list[Week]:
    """Flexible, easy-only base-building weeks before the structured block.
    No fixed workout days: just a weekly mileage target split across 3-4
    easy runs plus one slightly longer run, left flexible day-to-day. Run
    count follows the same mileage-based thresholds as the race-specific
    block, so this never asks for more than 4 runs (base weeks never reach
    peak mileage, so the 5-run tier never triggers here)."""
    n_weeks = max(0, (end_before - start_date).days // 7)
    weeks: list[Week] = []
    for w in range(n_weeks):
        week_start = start_date + datetime.timedelta(weeks=w)
        progress = w / max(n_weeks - 1, 1)
        total_km = round(start_km + (target_km - start_km) * progress)
        if (w + 1) % 4 == 0:
            total_km = round(total_km * 0.80)
        week = Week(index=None, phase="Base-building", start_date=week_start)
        n_runs = len(_skeleton_for_week(total_km, peak_km))
        n_easy = n_runs - 1
        # Long run must be the biggest single run, so give it a bigger share
        # the fewer easy runs there are to spread the rest across.
        long_frac = 0.42 if n_easy <= 2 else 0.32
        long_run = round(total_km * long_frac, 1)
        per_run = round((total_km - long_run) / n_easy, 1)
        plan = [("Easy run (flexible day)", per_run)] * n_easy + [("Long run (flexible day)", long_run)]
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
