"""Finish-time prediction using Jack Daniels' VDOT formula and the Riegel formula.

Daniels' equations (from Daniels' Running Formula / Oxygen Power):
    VO2 (demand at velocity v, m/min)   = -4.60 + 0.182258*v + 0.000104*v^2
    %VO2max sustainable for t minutes   = 0.8 + 0.1894393*e^(-0.012778*t)
                                                + 0.2989558*e^(-0.1932605*t)
    VDOT = VO2(v) / %VO2max(t)

Riegel's formula (Runner's World, 1977):
    T2 = T1 * (D2 / D1) ** 1.06
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _vo2(velocity_m_per_min: float) -> float:
    v = velocity_m_per_min
    return -4.60 + 0.182258 * v + 0.000104 * v**2


def _pct_vo2max(time_minutes: float) -> float:
    t = time_minutes
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)


def vdot_from_result(distance_km: float, time_minutes: float) -> float:
    """VDOT implied by a race/time-trial result."""
    velocity = distance_km * 1000 / time_minutes
    return _vo2(velocity) / _pct_vo2max(time_minutes)


def time_for_distance(vdot: float, distance_km: float) -> float:
    """Minutes predicted for distance_km at a given VDOT.

    Solves VO2(v)/%VO2max(t) = vdot for t, where v = distance*1000/t, via
    bisection (the equations have no closed-form inverse).
    """

    def f(t_minutes: float) -> float:
        velocity = distance_km * 1000 / t_minutes
        return _vo2(velocity) / _pct_vo2max(t_minutes) - vdot

    lo, hi = 1.0, 24 * 60.0
    # f is decreasing in t for fixed distance (slower implied VDOT the longer
    # it takes), so a sign-change bracket is guaranteed in this range.
    for _ in range(100):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def riegel_predict(time1_minutes: float, dist1_km: float, dist2_km: float) -> float:
    return time1_minutes * (dist2_km / dist1_km) ** 1.06


@dataclass
class TrainingPaces:
    easy_min_per_km: tuple[float, float]
    marathon_min_per_km: float


def training_paces(vdot: float) -> TrainingPaces:
    """Easy and marathon-pace ranges for a VDOT, per Daniels' %VO2max bands.

    Easy running sits at roughly 59-74% of VDOT-velocity; marathon pace at
    roughly 84-88% (we use the middle of that band, ~86%). Only these two
    are computed since the plan avoids LT/VO2max/interval work.
    """
    # Velocity (m/min) at a given %VO2max: invert VO2(v) = pct*vdot for v.
    def velocity_for_pct(pct: float) -> float:
        target_vo2 = pct * vdot
        # -4.60 + 0.182258 v + 0.000104 v^2 = target_vo2
        a, b, c = 0.000104, 0.182258, -4.60 - target_vo2
        return (-b + math.sqrt(b**2 - 4 * a * c)) / (2 * a)

    def pace_min_per_km(velocity_m_per_min: float) -> float:
        return 1000 / velocity_m_per_min

    easy_fast = pace_min_per_km(velocity_for_pct(0.74))
    easy_slow = pace_min_per_km(velocity_for_pct(0.59))
    marathon = pace_min_per_km(velocity_for_pct(0.86))
    return TrainingPaces(easy_min_per_km=(easy_fast, easy_slow), marathon_min_per_km=marathon)


def format_pace(min_per_km: float) -> str:
    minutes = int(min_per_km)
    seconds = round((min_per_km - minutes) * 60)
    if seconds == 60:
        minutes, seconds = minutes + 1, 0
    return f"{minutes}:{seconds:02d}/km"


def format_time(minutes: float) -> str:
    total_seconds = round(minutes * 60)
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_pace_to_min_per_km(pace: str) -> float:
    m, s = pace.split(":")
    return int(m) + int(s) / 60


def parse_time_to_minutes(t: str) -> float:
    parts = [int(p) for p in t.split(":")]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, (m, s) = 0, (parts[0], parts[1])
    else:
        raise ValueError(f"Unrecognized time format: {t!r}")
    return h * 60 + m + s / 60
