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

Mileage ramps up at a capped percentage per week (not a fixed end date to
hit), with every 4th week a lighter cutback whose reduction carries
forward into the next week's baseline rather than rebounding back to the
pre-cutback trajectory. Once it reaches peak mileage it holds there until
the taper, it does not force an overshoot.
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
    pace: str = ""
    duration: str = ""
    explanation: str = ""


@dataclass
class Week:
    index: int  # weeks out from race, counting down; None for base-building weeks
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

_RACE_PREP_START_WEEKS_OUT = 6  # from here the long/MP run carries marathon-pace miles
_TAPER_START_WEEKS_OUT = 2  # the book only really tapers the last 2 weeks

# The book's actual weekly totals (km) for weeks_out 11 down to 0, read
# directly from its chapter 9 tables ("Up to 55 Miles per Week", 18-week
# schedule) rather than approximated. weeks_out 0 (race week) is 6 days
# pre-race per the book, i.e. excludes the race itself. _BOOK_PEAK_KM is
# the book's own peak (55 mi/wk), used to scale this table if peak_km in
# config differs from it.
_BOOK_WEEKLY_KM = {11: 56, 10: 63, 9: 69, 8: 77, 7: 68, 6: 77, 5: 89,
                   4: 82, 3: 84, 2: 70, 1: 51, 0: 35}
_BOOK_PEAK_KM = 89

WORKOUT_EXPLANATIONS = {
    "Rest or cross-train": "Full rest, or easy cross-training (swim, bike, "
        "elliptical) if you'd rather stay active. Nothing is lost by resting here.",
    "General aerobic": "Comfortable, conversational effort. This is the bulk of "
        "your aerobic base-building, not a workout to push.",
    "Medium-long run": "A longer run slipped into the middle of the week. Builds "
        "endurance without the fatigue cost of the weekend long run.",
    "Recovery": "Short and deliberately slow, the day after a harder session. "
        "The point is recovery, not fitness.",
    "Recovery + optional strides": "Easy run; finish with 6-8 x 100m relaxed, "
        "fast-feeling strides if your legs want it. Strides are optional, skip "
        "them anytime without consequence.",
    "Long run": "The week's most important session. Builds the endurance and "
        "fatigue resistance marathon day demands.",
    "Easy run (flexible day)": "Comfortable aerobic running. Move it to "
        "whichever day suits you this week.",
    "Long run (flexible day)": "The week's longest run, still at an easy, "
        "conversational effort. This is about time on feet, not pace.",
    "Goal marathon": "Race day. Hold your planned pace, especially through the "
        "first 10K; it's easy to go out too fast.",
}

# Pace for each workout, as (fast, slow) fractions SLOWER than goal
# marathon pace, per "Advanced Marathoning" chapter 1. The book states
# this explicitly, as a direct rule, only for long/medium-long runs
# (table 1.1: "10 to 20 percent slower than your goal marathon race
# pace," the book also states medium-long runs use this same range).
# General aerobic and recovery aren't given exact percentages in the
# book, only a relative heart-rate-zone ordering (general aerobic sits
# below long-run effort, recovery below that) — their ranges here extend
# the book's own 10-20% step in that same spirit, not lifted from a table.
_PACE_PCT_SLOWER = {
    "Long run": (0.10, 0.20),
    "Long run (flexible day)": (0.10, 0.20),
    "Medium-long run": (0.10, 0.20),
    "General aerobic": (0.15, 0.25),
    "Easy run (flexible day)": (0.15, 0.25),
    "Recovery": (0.25, 0.35),
    "Recovery + optional strides": (0.25, 0.35),
}


def _phase_for_week(weeks_out: int) -> str:
    if weeks_out <= _TAPER_START_WEEKS_OUT:
        return "Taper"
    if weeks_out <= _RACE_PREP_START_WEEKS_OUT:
        return "Race preparation"
    if weeks_out <= 12:
        return "LT+endurance (adapted: general aerobic)"
    return "Endurance"


def _skeleton_for_week(total_km: float, peak_km: float) -> dict:
    ratio = total_km / peak_km if peak_km else 0
    if ratio >= HIGH_MILEAGE_RATIO:
        return _SKELETON_5
    if ratio >= MID_MILEAGE_RATIO:
        return _SKELETON_4
    return _SKELETON_3


def generate_mileage_ramp(start_km: float, peak_km: float, n_weeks: int,
                           growth_cap: float = 0.10, recovery_every: int = 4,
                           recovery_factor: float = 0.85) -> list[float]:
    """Weekly totals growing by at most `growth_cap` per week (the standard
    "no more than ~10%" safety guideline), capped at peak_km, with a
    lighter cutback every `recovery_every`th week. A cutback week is a
    pure reduction relative to the week before it (no growth attempted
    that week), and growth resumes from that reduced level afterwards —
    so there's no rebound spike back to an un-cut trajectory.

    Note this is intentionally conservative: if start_km is far below
    peak_km relative to n_weeks, this will not reach peak_km in time, and
    will simply end lower. That's a feature, not a bug, it means the
    ramp never exceeds a safe weekly growth rate to hit an arbitrary
    deadline. Check the return value's last entries against peak_km;
    `generate-schedule` prints a warning if they're not close.
    """
    totals = []
    ramp = float(start_km)
    for i in range(n_weeks):
        if i > 0:
            if (i + 1) % recovery_every == 0:
                ramp = ramp * recovery_factor
            else:
                ramp = min(ramp * (1 + growth_cap), peak_km)
        totals.append(round(ramp))
    return totals


# Clean duration buckets for non-long runs: 35, 45, then every 15
# minutes. Rather than keeping a run's original distance and inflating
# its duration (and therefore its pace) up to the next bucket, which can
# distort pace well past the book's intended range, _bucket_fit instead
# finds the whole-km distance that lands close to a bucket at the
# CORRECT pace, so pace stays accurate and only the distance moves a
# little. Each week's long run then absorbs the sum of those small
# distance adjustments, so the week's total volume is unchanged overall.
_DURATION_BUCKETS = [35, 45] + list(range(60, 240, 15))


def _round_duration_up(raw_minutes: float) -> int:
    import math

    if raw_minutes <= _DURATION_BUCKETS[0]:
        return max(1, math.ceil(raw_minutes))
    for b in _DURATION_BUCKETS:
        if raw_minutes <= b:
            return b
    b = _DURATION_BUCKETS[-1]
    while b < raw_minutes:
        b += 15
    return b


def _ref_pace(workout: str, mp_pace: float) -> float | None:
    pcts = _PACE_PCT_SLOWER.get(workout)
    if not pcts:
        return None
    return mp_pace * (1 + pcts[1])  # slower end of the range, biased slower


def _bucket_fit(original_km: float, pace: float) -> tuple[int, int]:
    """(adjusted_km, bucketed_minutes): the whole-km distance whose
    duration at `pace` lands on a clean bucket, kept close to
    original_km. Pace stays exact; only distance (and only by a km or
    two) moves to make the duration clean."""
    raw_duration = original_km * pace
    bucketed = _round_duration_up(raw_duration)
    adjusted_km = max(1, round(bucketed / pace))
    return adjusted_km, bucketed


def _pace_and_duration(workout: str, distance_km: float | None,
                        mp_pace: float) -> tuple[int | None, str, str]:
    """For workouts that AREN'T the week's long run: bucket-fit distance
    (see _bucket_fit) so pace stays accurate to the book's percentages."""
    from training import predict

    if not distance_km:
        return None, "", ""
    if workout == "Goal marathon":
        return round(distance_km, 1), predict.format_pace_bare(mp_pace), ""

    pace = _ref_pace(workout, mp_pace)
    if pace is None:
        return max(1, round(distance_km)), "", ""

    adjusted_km, bucketed = _bucket_fit(distance_km, pace)
    actual_pace = bucketed / adjusted_km
    return adjusted_km, predict.format_pace_bare(actual_pace), f"{bucketed}m"


def _long_run_pace_and_duration(final_km: int, mp_km: int, mp_pace: float) -> tuple[str, str]:
    """The week's long run absorbs whatever distance adjustment the other
    runs needed to keep the week's total volume right, so it doesn't get
    bucket-fit itself — duration is computed directly from its final
    distance and the correct pace(s) (blended with marathon pace for the
    mp_km portion, if any), then just rounded to the nearest 5 minutes
    for a tidy number, without forcing a specific bucket."""
    from training import predict

    easy_pace = mp_pace * (1 + _PACE_PCT_SLOWER["Long run"][1])
    mp_km = min(mp_km, final_km)
    easy_km = final_km - mp_km
    raw_duration = mp_km * mp_pace + easy_km * easy_pace
    duration = max(5, round(raw_duration / 5) * 5)
    actual_pace = duration / final_km
    return predict.format_pace_bare(actual_pace), f"{duration}m"


def generate_18wk_plan(plan_start: datetime.date, weekly_totals: list[float],
                        peak_km: float, mp_pace: float) -> list[Week]:
    from training import predict

    n_weeks = len(weekly_totals)
    weeks: list[Week] = []
    for w in range(n_weeks):
        week_start = plan_start + datetime.timedelta(weeks=w)
        weeks_out = n_weeks - w - 1
        phase = _phase_for_week(weeks_out)
        total_km = weekly_totals[w]
        week = Week(index=weeks_out, phase=phase, start_date=week_start)
        skeleton = _skeleton_for_week(total_km, peak_km)

        workouts = {o: skeleton.get(o, ("Rest or cross-train", 0.0))[0] for o in range(7)}
        raw_dists = {o: (total_km * skeleton[o][1] if o in skeleton else None) for o in range(7)}
        long_offset = next(o for o, wk in workouts.items() if wk == "Long run")

        results: dict[int, tuple] = {}
        delta = 0
        for offset, workout in workouts.items():
            raw_dist = raw_dists[offset]
            if workout == "Long run" or raw_dist is None:
                continue
            adjusted_km, pace_str, duration_str = _pace_and_duration(workout, raw_dist, mp_pace)
            delta += adjusted_km - max(1, round(raw_dist))
            notes = ("strides are relaxed and quick, not a sprint, not required"
                     if workout == "Recovery + optional strides" else "")
            results[offset] = (adjusted_km, pace_str, duration_str, notes)
        for offset, raw_dist in raw_dists.items():
            if raw_dist is None:
                results[offset] = (None, "", "", "")

        max_other_km = max((v[0] for k, v in results.items() if v[0]), default=0)
        final_long_km = max(1, round(raw_dists[long_offset]) - delta, max_other_km + 1)
        notes = ""
        mp_km = 0
        if weeks_out <= _RACE_PREP_START_WEEKS_OUT and weeks_out > 0:
            mp_km = round(final_long_km * 0.55)
            notes = f"include ~{mp_km} km at marathon pace ({_fmt_pace(mp_pace)}), rest easy"
        pace_str, duration_str = _long_run_pace_and_duration(final_long_km, mp_km, mp_pace)
        results[long_offset] = (final_long_km, pace_str, duration_str, notes)

        if weeks_out == 0:
            workouts[6] = "Goal marathon"
            results[6] = (42.2, predict.format_pace_bare(mp_pace), "", "race day")

        for offset in range(7):
            date = week_start + datetime.timedelta(days=offset)
            dist, pace, duration, notes = results[offset]
            workout = workouts[offset]
            week.days.append(Day(date=date, workout=workout, distance_km=dist, notes=notes,
                                  pace=pace, duration=duration,
                                  explanation=WORKOUT_EXPLANATIONS.get(workout, "")))
        weeks.append(week)
    return weeks


def generate_base_building(start_date: datetime.date, weekly_totals: list[float],
                            weekly_long_runs: list[float], peak_km: float,
                            mp_pace: float) -> list[Week]:
    """Flexible, easy-only base-building weeks before the structured block.
    No fixed workout days: just a weekly mileage target split across 3-4
    easy runs plus one slightly longer run, left flexible day-to-day.

    weekly_long_runs is a separate ramp (not just a fixed fraction of the
    week's total) so the long run can be pushed toward the book's own
    prerequisite (~19 km) by the end of base-building, independent of how
    fast total weekly volume itself is climbing.
    """
    weeks: list[Week] = []
    for w, total_km in enumerate(weekly_totals):
        week_start = start_date + datetime.timedelta(weeks=w)
        week = Week(index=None, phase="Base-building", start_date=week_start)
        n_runs = len(_skeleton_for_week(total_km, peak_km))
        n_easy = n_runs - 1
        # Long run can't exceed most of the week's volume, clamp it.
        long_run = round(min(weekly_long_runs[w], total_km * 0.55), 1)
        per_run = (total_km - long_run) / n_easy

        delta = 0
        easy_results = []
        for _ in range(n_easy):
            adjusted_km, pace_str, duration_str = _pace_and_duration(
                "Easy run (flexible day)", per_run, mp_pace)
            delta += adjusted_km - max(1, round(per_run))
            easy_results.append((adjusted_km, pace_str, duration_str))

        # The long run absorbs the easy runs' rounding delta, but must stay
        # the week's biggest run regardless of which way that delta goes.
        max_easy_km = max((r[0] for r in easy_results), default=0)
        final_long_km = max(1, round(long_run) - delta, max_easy_km + 1)
        pace_str, duration_str = _long_run_pace_and_duration(final_long_km, 0, mp_pace)

        plan = [("Easy run (flexible day)", r) for r in easy_results]
        plan.append(("Long run (flexible day)", (final_long_km, pace_str, duration_str)))
        for offset, (workout, (dist, pace, duration)) in enumerate(plan):
            date = week_start + datetime.timedelta(days=offset)
            week.days.append(Day(date=date, workout=workout, distance_km=dist,
                                  notes="move to whichever day suits you this week",
                                  pace=pace, duration=duration,
                                  explanation=WORKOUT_EXPLANATIONS.get(workout, "")))
        weeks.append(week)
    return weeks


def generate_book_progression(start_km: float, peak_km: float, n_weeks: int) -> list[float]:
    """The 18-week block's own mileage curve, taken from the book's actual
    published numbers (_BOOK_WEEKLY_KM, scaled if peak_km differs from the
    book's own 55 mi/wk) for the weeks it covers (weeks_out 11 down to 0),
    with the earlier, unpublished weeks (weeks_out above 11) filled in by
    a gentle interpolation from start_km up to the book's own weeks_out=11
    value, since the book describes this stretch as a slow start, not a
    steep climb.
    """
    scale = peak_km / _BOOK_PEAK_KM
    tail_keys = sorted(_BOOK_WEEKLY_KM, reverse=True)  # 11, 10, ..., 0
    tail = [round(_BOOK_WEEKLY_KM[k] * scale) for k in tail_keys]

    n_head = n_weeks - len(tail)
    if n_head <= 0:
        return tail[-n_weeks:]
    head_target = tail[0]  # the book's value at weeks_out=11 (scaled)
    head = []
    for i in range(n_head):
        progress = i / max(n_head - 1, 1)
        head.append(round(start_km + (head_target - start_km) * progress))
    return head + tail


def _fmt_pace(min_per_km: float) -> str:
    from training import predict
    return predict.format_pace(min_per_km)


def write_schedule_csv(path: str, weeks: list[Week]) -> None:
    import csv

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "phase", "weeks_out", "workout", "distance_km",
                          "pace_per_km", "duration", "notes", "explanation"])
        for week in weeks:
            for day in week.days:
                writer.writerow([day.date.isoformat(), week.phase,
                                  week.index if week.index is not None else "",
                                  day.workout, day.distance_km or "",
                                  day.pace, day.duration, day.notes, day.explanation])
