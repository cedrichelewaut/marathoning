"""Render a static HTML page from the plan and the tracked run log.

Week totals come from data/weekly_status.csv (written by sync-site from
data/strava_runs.csv). When the run log is passed in, those totals are
recomputed from it. Sessions are matched to runs inside the week, not by
calendar date, because the days can move. The log has no tokens.

The page is a monday.com-style board with three groups:

- Completed: weeks that are fully in the past. Collapsed by default.
  The header shows actual vs planned kilometres and how many of those
  weeks reached the on-track bar (see training.status.WeekStatus).
- This week: the week that contains today. Open, with one row per session.
- Coming up: weeks that have not started.
"""

from __future__ import annotations

import csv
import datetime
import html
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

_BRUSSELS = ZoneInfo("Europe/Brussels")


# Same cut as WeekStatus.verdict: "on track" / "ahead" are a completed week.
_ON_TRACK_PCT = 85.0

_GROUP_ORDER = ("completed", "this-week", "upcoming")
_GROUP_TITLE = {
    "completed": "Completed",
    "this-week": "This week",
    "upcoming": "Coming up",
}


@dataclass
class WeekView:
    week_start: datetime.date
    phase: str
    planned_km: float
    actual_km: float
    long_planned_km: float
    long_actual_km: float
    days: list[dict] = field(default_factory=list)
    logged: list[dict] = field(default_factory=list)
    bucket: str = ""
    includes_race: bool = False
    plan_week: int | None = None

    @property
    def pct(self) -> float:
        if self.planned_km <= 0:
            return 100.0 if self.actual_km <= 0 else 0.0
        return self.actual_km / self.planned_km * 100


def fmt_km(value: float) -> str:
    """17.0 -> '17', 67.2 -> '67.2'."""
    text = f"{value:.1f}"
    if text.endswith(".0"):
        return text[:-2]
    return text


# The book block is 18 Mondays ending on race week.
_PLAN_WEEKS = 18


def plan_block_start(race_date: datetime.date) -> datetime.date:
    """Monday of week 1, counting 18 weeks back from the race week."""
    race_week = race_date - datetime.timedelta(days=race_date.weekday())
    return race_week - datetime.timedelta(weeks=_PLAN_WEEKS - 1)


def marathon_week_number(week_start: datetime.date, race_date: datetime.date) -> int | None:
    """1–18 inside the race block, or None for earlier base-building weeks."""
    start = plan_block_start(race_date)
    if week_start < start:
        return None
    number = (week_start - start).days // 7 + 1
    if number > _PLAN_WEEKS:
        return None
    return number


def week_bucket(week_start: datetime.date, today: datetime.date) -> str:
    week_end = week_start + datetime.timedelta(days=6)
    if week_end < today:
        return "completed"
    if week_start <= today <= week_end:
        return "this-week"
    return "upcoming"


def counts_as_done(planned_km: float, actual_km: float) -> bool:
    """A past week counts toward the '4/4 weeks' summary at the on-track bar."""
    if planned_km <= 0:
        return True
    return (actual_km / planned_km * 100) >= _ON_TRACK_PCT


def completed_summary(weeks: list[WeekView]) -> str:
    """'52/54 km completed, 4/4 weeks' from actual vs planned totals."""
    actual = sum(w.actual_km for w in weeks)
    planned = sum(w.planned_km for w in weeks)
    done = sum(1 for w in weeks if counts_as_done(w.planned_km, w.actual_km))
    total = len(weeks)
    unit = "week" if total == 1 else "weeks"
    return f"{fmt_km(actual)}/{fmt_km(planned)} km completed, {done}/{total} {unit}"


# A day can still absorb about this much. More than that, with the days
# that are left, is more than the week can realistically finish.
_DAILY_KM = 20.0


def _days_left(week: WeekView, today: datetime.date) -> int:
    """Days from today through Sunday, counting today. Zero once the week has ended."""
    week_end = week.week_start + datetime.timedelta(days=6)
    if today > week_end:
        return 0
    start = max(today, week.week_start)
    return (week_end - start).days + 1


def _days_elapsed(week: WeekView, today: datetime.date) -> int:
    """Finished days in the week, not counting today."""
    if today <= week.week_start:
        return 0
    week_end = week.week_start + datetime.timedelta(days=6)
    if today > week_end:
        return 7
    return (today - week.week_start).days


def progress_tone(week: WeekView, today: datetime.date) -> str:
    """Bar color: green, yellow, red, or neutral.

    Future weeks stay grey. Green means the week is at the done bar, or
    logged kilometres are keeping up with a straight line through the week.
    Red means the kilometres still to go are more than 20 km for each day
    left, which is what happens with less than two days left and a large
    gap, and for any finished week under the done bar. Yellow is behind
    that line while the remainder can still be run.
    """
    if week.bucket == "upcoming":
        return "neutral"
    if week.planned_km <= 0 or counts_as_done(week.planned_km, week.actual_km):
        return "green"
    remaining = max(0.0, week.planned_km - week.actual_km)
    left = _days_left(week, today)
    if remaining > left * _DAILY_KM:
        return "red"
    expected = week.planned_km * _days_elapsed(week, today) / 7
    if week.actual_km + 0.5 >= expected:
        return "green"
    return "yellow"


def delta_label(actual_km: float, planned_km: float) -> str:
    """'+1 km', '-1 km', or 'on plan' when the gap is within half a kilometre."""
    diff = actual_km - planned_km
    if abs(diff) <= 0.5:
        return "on plan"
    if diff > 0:
        rounded = int(diff + 0.5)
    else:
        rounded = int(diff - 0.5)
    if rounded == 0:
        return "on plan"
    return f"{rounded:+d} km"


@dataclass(frozen=True)
class SessionMatch:
    """One planned session or an extra run, after within-week matching."""

    role: str  # matched, additional, missed, todo
    label: str
    planned: dict | None
    run: dict | None


def _is_long_workout(name: str) -> bool:
    text = name.lower()
    return "long run" in text or text.startswith("long")


def _planned_long(sessions: list[dict]) -> dict:
    """The planned long run, or the longest session when none is named."""
    def key(session: dict) -> tuple:
        named = 1 if _is_long_workout(session.get("workout") or "") else 0
        day = session.get("date") or "9999-99-99"
        return (named, float(session["distance_km"]), tuple(-ord(ch) for ch in day))

    return max(sessions, key=key)


def _longest_run(runs: list[dict]) -> dict:
    return min(
        runs,
        key=lambda run: (
            -float(run["distance_km"]),
            run.get("date") or "",
            run.get("strava_activity_id") or "",
            run.get("name") or "",
        ),
    )


def match_sessions(planned: list[dict], runs: list[dict], *, week_over: bool) -> list[SessionMatch]:
    """Pair runs with sessions inside one week.

    The longest run fills the planned long run. Each remaining run fills the
    unmatched session closest in distance. Ties break toward the earlier
    session, then the earlier run. Extra runs are Additional. A session with
    no run is Missed once the week is over, and To do until then.
    """
    sessions = [day for day in planned if not _is_rest(day) and day.get("distance_km")]
    pool = list(runs)
    paired: dict[int, dict] = {}

    if sessions and pool:
        long_session = _planned_long(sessions)
        long_run = _longest_run(pool)
        paired[id(long_session)] = long_run
        sessions = [day for day in sessions if day is not long_session]
        pool = [run for run in pool if run is not long_run]

    while sessions and pool:
        best_key: tuple | None = None
        best: tuple[dict, dict] | None = None
        for session in sessions:
            planned_km = float(session["distance_km"])
            for run in pool:
                key = (
                    abs(float(run["distance_km"]) - planned_km),
                    session.get("date") or "",
                    run.get("date") or "",
                    run.get("strava_activity_id") or "",
                    run.get("name") or "",
                    session.get("workout") or "",
                )
                if best_key is None or key < best_key:
                    best_key = key
                    best = (session, run)
        assert best is not None
        session, run = best
        paired[id(session)] = run
        sessions = [day for day in sessions if day is not session]
        pool = [item for item in pool if item is not run]

    gap = ("missed", "Missed") if week_over else ("todo", "To do")
    rows: list[SessionMatch] = []
    for day in planned:
        if _is_rest(day) or not day.get("distance_km"):
            continue
        run = paired.get(id(day))
        if run is None:
            rows.append(SessionMatch(gap[0], gap[1], day, None))
            continue
        rows.append(SessionMatch(
            "matched",
            delta_label(float(run["distance_km"]), float(day["distance_km"])),
            day,
            run,
        ))
    for run in sorted(pool, key=lambda item: (
        item.get("date") or "",
        item.get("strava_activity_id") or "",
        item.get("name") or "",
    )):
        rows.append(SessionMatch("additional", "Additional", None, run))
    return rows


def bar_width(week: WeekView) -> float:
    if week.pct <= 0:
        return 0.0
    return max(4.0, min(100.0, week.pct))


def _load_schedule_by_week(schedule_path: str) -> dict[datetime.date, list[dict]]:
    weeks: dict[datetime.date, list[dict]] = {}
    with open(schedule_path, newline="") as f:
        for row in csv.DictReader(f):
            day = datetime.date.fromisoformat(row["date"])
            week_start = day - datetime.timedelta(days=day.weekday())
            weeks.setdefault(week_start, []).append(row)
    return weeks


def _runs_in_week(run_rows: list[dict], week_start: datetime.date) -> list[dict]:
    week_end = week_start + datetime.timedelta(days=6)
    logged = []
    for run in run_rows:
        day = datetime.date.fromisoformat(run["date"])
        if week_start <= day <= week_end:
            logged.append(run)
    return logged


def build_weeks(schedule_path: str, weekly_status_path: str, race_date: datetime.date,
                today: datetime.date, run_rows: list[dict] | None = None) -> list[WeekView]:
    from training import status as status_mod

    weeks_by_start = _load_schedule_by_week(schedule_path)
    status_by_week = status_mod.load_weekly_status(weekly_status_path)
    views: list[WeekView] = []
    for week_start in sorted(weeks_by_start):
        days = sorted(weeks_by_start[week_start], key=lambda r: r["date"])
        phase = days[0].get("phase") or ""
        st = status_by_week.get(week_start.isoformat())
        if st:
            planned = float(st["planned_km"])
            actual = float(st["actual_km"])
            long_planned = float(st["long_run_planned_km"])
            long_actual = float(st["long_run_actual_km"])
        else:
            distances = [float(d["distance_km"]) for d in days if d.get("distance_km")]
            planned = sum(distances)
            actual = 0.0
            long_planned = max(distances, default=0.0)
            long_actual = 0.0
        logged: list[dict] = []
        if run_rows is not None:
            logged = _runs_in_week(run_rows, week_start)
            actual = sum(float(run["distance_km"]) for run in logged)
            long_actual = max((float(run["distance_km"]) for run in logged), default=0.0)
        views.append(WeekView(
            week_start=week_start,
            phase=phase,
            planned_km=planned,
            actual_km=actual,
            long_planned_km=long_planned,
            long_actual_km=long_actual,
            days=days,
            logged=logged,
            bucket=week_bucket(week_start, today),
            includes_race=any(d["date"] == race_date.isoformat() for d in days),
            plan_week=marathon_week_number(week_start, race_date),
        ))
    return views


def group_weeks(weeks: list[WeekView]) -> dict[str, list[WeekView]]:
    grouped = {key: [] for key in _GROUP_ORDER}
    for week in weeks:
        grouped[week.bucket].append(week)
    return grouped


@dataclass
class PhaseProgress:
    kind: str
    label: str
    actual_km: float
    planned_km: float
    weeks_done: int
    weeks_total: int

    @property
    def pct(self) -> float:
        if self.planned_km <= 0:
            return 0.0
        return min(100.0, self.actual_km / self.planned_km * 100)


def phase_km_label(phase: PhaseProgress) -> str:
    return f"{fmt_km(phase.actual_km)} km / {fmt_km(phase.planned_km)} km"


def phase_weeks_label(phase: PhaseProgress) -> str:
    unit = "week" if phase.weeks_total == 1 else "weeks"
    return f"{phase.weeks_done}/{phase.weeks_total} {unit}"


def phase_progress(weeks: list[WeekView]) -> tuple[PhaseProgress, PhaseProgress]:
    """Kilometres and finished weeks for base building and the 18-week block.

    Actual kilometres are whatever each week already logged. A finished week
    counts as done at the same 85% bar as the Completed summary.
    """
    def pack(kind: str, label: str, chosen: list[WeekView]) -> PhaseProgress:
        done = sum(
            1 for week in chosen
            if week.bucket == "completed" and counts_as_done(week.planned_km, week.actual_km)
        )
        return PhaseProgress(
            kind=kind,
            label=label,
            actual_km=sum(week.actual_km for week in chosen),
            planned_km=sum(week.planned_km for week in chosen),
            weeks_done=done,
            weeks_total=len(chosen),
        )

    base = [week for week in weeks if not week.plan_week]
    plan = [week for week in weeks if week.plan_week]
    return (
        pack("base", "Base building", base),
        pack("plan", "Marathon training · 18 weeks", plan),
    )


def _esc(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _phase_label(phase: str) -> str:
    """Short labels so a long phase name doesn't stretch the column."""
    if phase.startswith("LT+endurance"):
        return "LT + endurance"
    if phase == "Race preparation":
        return "Race prep"
    return phase


def _week_label(week: WeekView) -> str:
    start = week.week_start
    end = start + datetime.timedelta(days=6)

    def md(day: datetime.date) -> str:
        return f"{day.strftime('%b')} {day.day}"

    if start.year != end.year:
        label = f"{md(start)}, {start.year} – {md(end)}, {end.year}"
    elif start.month != end.month:
        label = f"{md(start)} – {md(end)}"
    else:
        label = f"{md(start)} – {end.day}"
    if week.includes_race:
        label += " · Race"
    return label


def _fmt_width(width: float) -> str:
    if abs(width - round(width)) < 0.05:
        return str(int(round(width)))
    return f"{width:.1f}"


def _metric(actual: float, planned: float) -> str:
    if planned <= 0 and actual <= 0:
        return "—"
    return f"{fmt_km(actual)}/{fmt_km(planned)} km"


def _is_rest(day: dict) -> bool:
    return day.get("workout") == "Rest or cross-train"


def _session_name(workout: str) -> str:
    """Drop a parenthetical such as '(flexible day)'. Days are not part of the plan."""
    name = workout or ""
    cut = name.find(" (")
    if cut != -1:
        name = name[:cut]
    return name.strip() or (workout or "").strip()


def _session_title(planned: dict) -> str:
    name = _session_name(planned.get("workout") or "")
    if planned.get("distance_km"):
        return f"{name} · {fmt_km(float(planned['distance_km']))} km"
    return name or "Session"


def _run_measure(run: dict) -> str:
    """Distance and moving time, with no calendar day."""
    pieces = [f"{fmt_km(float(run['distance_km']))} km"]
    moving = (run.get("moving_time") or "").strip()
    if moving:
        pieces.append(moving)
    return " · ".join(pieces)


def _run_text(run: dict) -> str:
    name = (run.get("name") or "").strip() or "Run"
    return f"{name} · {_run_measure(run)}"


def _tag_class(label: str) -> str:
    if label == "on plan":
        return "on-plan"
    if label == "Additional":
        return "additional"
    if label == "Missed":
        return "missed"
    if label == "To do":
        return "todo"
    if label.startswith("+"):
        return "plus"
    if label.startswith("-"):
        return "minus"
    return "todo"


def _session_rows(week: WeekView) -> str:
    """Planned sessions beside the run matched inside this week."""
    matches = match_sessions(week.days, week.logged, week_over=week.bucket == "completed")
    if not matches:
        return '<p class="why">No runs scheduled.</p>'
    parts = [
        '<div class="session head">'
        "<span>Session</span><span>Logged run</span><span>Vs plan</span>"
        "</div>"
    ]
    for match in matches:
        if match.role == "additional" and match.run is not None:
            what = (match.run.get("name") or "").strip() or "Run"
            logged = _run_measure(match.run)
            logged_class = "logged"
        else:
            what = _session_title(match.planned or {})
            if match.run is not None:
                logged = _run_text(match.run)
                logged_class = "logged"
            else:
                logged = "—"
                logged_class = "logged wait"
        parts.append(
            '<div class="session">'
            f'<span class="what">{_esc(what)}</span>'
            f'<span class="{logged_class}">{_esc(logged)}</span>'
            f'<span class="spill"><span class="tag {_tag_class(match.label)}">{_esc(match.label)}</span></span>'
            "</div>"
        )
    return "".join(parts)


def _row(week: WeekView, today: datetime.date) -> str:
    tone = progress_tone(week, today)
    width = bar_width(week)
    # A yellow or red week with no kilometres yet still shows a sliver of that color.
    if tone in ("yellow", "red") and width < 4:
        width = 4.0
    fill_html = (
        f'<span class="fill {tone}" style="width:{_fmt_width(width)}%"></span>' if width else ""
    )
    distance = _metric(week.actual_km, week.planned_km)
    long_run = _metric(week.long_actual_km, week.long_planned_km)
    described = f"{fmt_km(week.actual_km)} of {fmt_km(week.planned_km)} kilometres, {tone}"
    opened = " open" if week.bucket == "this-week" else ""
    number = ""
    if week.plan_week:
        number = f'<span class="wk">Week {week.plan_week}</span>'
    return f"""<details class="item"{opened}>
<summary class="row">
  <span class="name"><svg class="chev" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>{number}<span class="weeklabel">{_esc(_week_label(week))}</span></span>
  <span class="phase" title="{_esc(week.phase)}">{_esc(_phase_label(week.phase))}</span>
  <span class="progress"><span class="bar {tone}" role="img" aria-label="{_esc(described)}">{fill_html}</span><span class="km">{_esc(distance)}</span></span>
  <span class="long">{_esc(long_run)}</span>
</summary>
<div class="subitems">{_session_rows(week)}</div>
</details>"""


def _phase_bars(weeks: list[WeekView]) -> str:
    parts = []
    for phase in phase_progress(weeks):
        km = phase_km_label(phase)
        weeks_label = phase_weeks_label(phase)
        width = _fmt_width(phase.pct)
        fill = (
            f'<span class="phasebar-fill" style="width:{width}%"></span>'
            if phase.pct > 0 else ""
        )
        parts.append(
            f'<div class="phasebar {phase.kind}">'
            '<div class="phasebar-head">'
            f'<span class="phasebar-name">{_esc(phase.label)}</span>'
            f'<span class="phasebar-km">{_esc(km)}</span>'
            "</div>"
            f'<div class="phasebar-track" role="img" aria-label="{_esc(phase.label)}, {_esc(km)}">'
            f"{fill}</div>"
            f'<p class="phasebar-weeks" title="Finished weeks at 85% of the planned distance">'
            f"{_esc(weeks_label)}</p>"
            "</div>"
        )
    return '<section class="phases" aria-label="Plan progress">\n' + "\n".join(parts) + "\n</section>"


def _group_summary(bucket: str, weeks: list[WeekView]) -> str:
    if bucket == "completed":
        return completed_summary(weeks)
    if bucket == "this-week":
        if not weeks:
            return "Nothing scheduled"
        week = weeks[0]
        return f"{fmt_km(week.actual_km)}/{fmt_km(week.planned_km)} km this week"
    unit = "week" if len(weeks) == 1 else "weeks"
    return f"{len(weeks)} {unit}"


def _band(kind: str) -> str:
    """Section label inside a group. The race block is the one that should stand out."""
    if kind == "plan":
        label = "Marathon training · 18 weeks"
        tone = "plan"
    else:
        label = "Base building"
        tone = "base"
    return (
        f'<div class="band {tone}">'
        f'<span class="band-name">{label}</span>'
        '<span class="band-line" aria-hidden="true"></span>'
        "</div>"
    )


def _section_rows(weeks: list[WeekView], today: datetime.date) -> str:
    parts: list[str] = []
    current = ""
    for week in weeks:
        kind = "plan" if week.plan_week else "base"
        if kind != current:
            parts.append(_band(kind))
            current = kind
        parts.append(_row(week, today))
    return "\n".join(parts)


def _group(bucket: str, weeks: list[WeekView], today: datetime.date) -> str:
    opened = "" if bucket == "completed" else " open"
    rows = _section_rows(weeks, today) if weeks else '<p class="empty">Nothing scheduled.</p>'
    title = _GROUP_TITLE[bucket]
    summary = _group_summary(bucket, weeks)
    return f"""<details class="group {bucket}"{opened}>
<summary class="ghead">
  <span class="gtitle"><svg class="chev" viewBox="0 0 16 16" width="18" height="18" aria-hidden="true"><path d="M6 3.5l5 4.5-5 4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="gname">{title}</span><span class="gsum">{_esc(summary)}</span></span>
</summary>
<div class="colhead" aria-hidden="true">
  <span></span><span class="phase">Phase</span><span>Progress</span><span class="long">Long run</span>
</div>
<div class="rows">
{rows}
</div>
</details>"""


_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #ffffff; }
body {
  color: #323338;
  font-family: Figtree, "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 14px;
  line-height: 1.4;
}
.wrap { max-width: 1120px; margin: 0 auto; padding: 28px 32px 72px; }
.top {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 24px; margin-bottom: 8px;
}
h1 {
  margin: 0; font-size: 32px; font-weight: 600; letter-spacing: -0.5px;
  color: #323338; line-height: 1.15;
}
.subtitle { margin: 6px 0 0; color: #676879; font-size: 14px; white-space: nowrap; }
.updated { margin: 2px 0 0; color: #676879; font-size: 13px; }
.countdown { margin: 0 0 2px; color: #676879; font-size: 14px; white-space: nowrap; }
.board { padding-bottom: 8px; }
.board-inner { min-width: 0; }
.phases {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  margin: 18px 0 6px;
}
.phasebar {
  min-width: 0; background: #f5f6f8; border-left: 6px solid #c4c4c4;
  border-radius: 0 6px 6px 0; padding: 10px 14px 12px;
}
.phasebar.plan { border-left-color: #ff642e; background: #fff4ee; }
.phasebar-head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 4px 12px; flex-wrap: wrap; min-width: 0;
}
.phasebar-name {
  font-size: 13px; font-weight: 600; letter-spacing: -0.1px; color: #676879;
  min-width: 0;
}
.phasebar.plan .phasebar-name { color: #323338; }
.phasebar-km {
  margin-left: auto; font-size: 13px; font-weight: 600; color: #323338;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.phasebar-track {
  margin-top: 8px; height: 10px; background: #e6e9ef;
  border-radius: 999px; overflow: hidden;
}
.phasebar.plan .phasebar-track { background: #ffd0c2; }
.phasebar-fill { display: block; height: 100%; border-radius: 999px; background: #676879; }
.phasebar.plan .phasebar-fill { background: #ff642e; }
.phasebar-weeks { margin: 6px 0 0; color: #676879; font-size: 12px; }
.group { margin-top: 26px; }
summary { list-style: none; cursor: pointer; }
summary::-webkit-details-marker { display: none; }
summary:focus-visible { outline: 2px solid #579bfc; outline-offset: 2px; border-radius: 4px; }
.ghead {
  display: flex; align-items: center; min-height: 36px; padding: 2px 0 2px;
}
.gtitle { display: flex; align-items: center; gap: 8px; min-width: 0; flex-wrap: wrap; }
.gname { font-size: 18px; font-weight: 600; letter-spacing: -0.2px; color: var(--group); }
.gsum { color: #676879; font-size: 14px; font-weight: 400; }
.group.completed { --group: #00c875; }
.group.this-week { --group: #579bfc; }
.group.upcoming { --group: #a25ddc; }
.colhead, .row {
  display: grid;
  grid-template-columns: minmax(180px, 1.5fr) 132px minmax(210px, 1.25fr) 108px;
  column-gap: 12px; align-items: center;
}
.colhead {
  border-left: 6px solid transparent; color: #676879; font-size: 14px;
  font-weight: 400; padding: 2px 0 6px;
}
.chev { flex: none; color: var(--group, #676879); transition: transform 0.15s ease; }
.group:not([open]) > .ghead .chev,
.item:not([open]) > .row .chev { transform: rotate(0deg); }
.group[open] > .ghead .chev,
.item[open] > .row .chev { transform: rotate(90deg); }
.item .chev { color: #676879; }
.row {
  background: #f5f6f8; border-left: 6px solid var(--group);
  min-height: 40px; margin-bottom: 4px; color: #323338;
}
.row:hover { background: #eceff3; }
.item[open] > .row { margin-bottom: 0; background: #eceff3; }
.name {
  display: flex; align-items: center; gap: 8px;
  padding-left: 10px; font-size: 14px; color: #323338; min-width: 0;
}
.weeklabel { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.wk {
  flex: none; color: #ff642e; font-size: 12px; font-weight: 600;
  letter-spacing: -0.1px; font-variant-numeric: tabular-nums;
}
.band {
  display: flex; align-items: center; gap: 10px;
  min-height: 28px; margin: 14px 0 6px; padding: 4px 8px 4px 10px;
  border-left: 6px solid #c4c4c4; min-width: 0;
}
.rows > .band:first-child { margin-top: 2px; }
.band.plan { border-left-color: #ff642e; background: #fff4ee; border-radius: 0 4px 4px 0; }
.band-name {
  flex: 0 1 auto; min-width: 0; color: #676879; font-size: 13px; font-weight: 600;
  letter-spacing: -0.1px;
}
.band.plan .band-name { color: #323338; }
.band-line { flex: 1 1 24px; height: 1px; background: #e6e9ef; min-width: 16px; }
.band.plan .band-line { background: #ffd0c2; }
.phase, .long, .km { font-size: 14px; color: #323338; white-space: nowrap; min-width: 0; }
.phase { overflow: hidden; text-overflow: ellipsis; }
.long, .km { font-variant-numeric: tabular-nums; }
.progress { display: flex; align-items: center; gap: 10px; min-width: 0; min-height: 40px; }
.bar {
  flex: 1 1 96px; width: auto; max-width: 148px; min-width: 72px; height: 14px;
  background: #e6e9ef; border-radius: 999px; overflow: hidden;
}
.bar.neutral { background: #e6e9ef; }
.fill { display: block; height: 100%; border-radius: 999px; }
.fill.green { background: #00c875; }
.fill.yellow { background: #fdab3d; }
.fill.red { background: #e2445c; }
.fill.neutral { background: #c4c4c4; }
.tag {
  display: flex; align-items: center; justify-content: center;
  height: 26px; border-radius: 4px; color: #fff; font-size: 13px; font-weight: 500;
  white-space: nowrap;
}
.tag.on-plan { background: #00c875; }
.tag.plus { background: #579bfc; }
.tag.minus, .tag.missed { background: #e2445c; }
.tag.additional { background: #a25ddc; }
.tag.todo { background: #c4c4c4; }
.subitems {
  border-left: 6px solid var(--group); background: #fafbfc;
  padding: 4px 16px 8px 34px; margin: 0 0 4px;
}
.session {
  display: grid;
  grid-template-columns: minmax(160px, 1.2fr) minmax(180px, 1.5fr) 116px;
  gap: 6px 12px; align-items: center; padding: 5px 0;
  border-top: 1px solid #eceff3;
}
.session.head {
  border-top: 0; color: #676879; font-size: 12px; padding: 2px 0 0;
}
.session .what, .session .logged {
  font-size: 13px; color: #323338; min-width: 0;
}
.session .logged { font-variant-numeric: tabular-nums; }
.session .logged.miss { color: #e2445c; }
.session .logged.wait { color: #676879; }
.runline { display: block; overflow-wrap: anywhere; }
.why { margin: 0; color: #676879; font-size: 13px; padding: 6px 0; }
.empty { border-left: 6px solid var(--group); background: #f5f6f8; color: #676879;
  min-height: 40px; padding-left: 16px; display: flex; align-items: center; }
footer { margin-top: 36px; color: #9699a6; font-size: 12px; line-height: 1.5; max-width: 720px; }
footer p { margin: 0; }
@media (prefers-reduced-motion: reduce) { .chev { transition: none; } }
@media (max-width: 900px) {
  .long { display: none; }
  .colhead, .row {
    grid-template-columns: minmax(150px, 1.3fr) minmax(96px, 130px) minmax(180px, 1fr);
  }
  .session { grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.3fr) 104px; }
}
@media (max-width: 640px) {
  .wrap { padding: 16px 12px 40px; }
  h1 { font-size: 26px; }
  .top { flex-direction: column; align-items: flex-start; gap: 4px; }
  .subtitle { white-space: normal; }
  .phases { grid-template-columns: 1fr; gap: 8px; margin-top: 14px; }
  .phasebar { padding: 10px 12px; }
  .colhead, .phase { display: none; }
  .row {
    grid-template-columns: minmax(0, 1fr) auto;
    column-gap: 8px;
  }
  .name { padding-left: 8px; font-size: 13px; gap: 4px; }
  .progress { gap: 8px; padding-right: 8px; min-height: 36px; }
  .bar { flex: 0 0 64px; width: 64px; min-width: 64px; max-width: 64px; }
  .km { font-size: 13px; }
  .session.head { display: none; }
  .session {
    grid-template-columns: minmax(0, 1fr) 96px;
    grid-template-areas: "what spill" "logged logged";
    gap: 2px 8px;
    padding: 8px 0;
  }
  .session .what { grid-area: what; }
  .session .spill { grid-area: spill; }
  .session .logged { grid-area: logged; padding-bottom: 2px; }
}
"""


def last_updated_label(now: datetime.datetime | None = None) -> str:
    """Clock time in Europe/Brussels, shown at the top of the page."""
    moment = now or datetime.datetime.now(_BRUSSELS)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_BRUSSELS)
    else:
        moment = moment.astimezone(_BRUSSELS)
    return f"Last updated {moment.strftime('%-d %b %Y, %H:%M')}"


def _countdown(race_date: datetime.date, today: datetime.date) -> str:
    days = (race_date - today).days
    if days > 1:
        return f"{days} days to go"
    if days == 1:
        return "1 day to go"
    if days == 0:
        return "Race day"
    return "Race day has passed"


def _resolve_now(now: datetime.datetime | None) -> datetime.datetime:
    if now is None:
        return datetime.datetime.now(_BRUSSELS)
    if now.tzinfo is None:
        return now.replace(tzinfo=_BRUSSELS)
    return now.astimezone(_BRUSSELS)


def _weeks_for_page(schedule_path: str, weekly_status_path: str,
                    race_date: datetime.date, today: datetime.date,
                    runs_path: str | None) -> list[WeekView]:
    run_rows = None
    if runs_path:
        from training import status as status_mod
        run_rows, _skipped = status_mod.load_strava_runs(runs_path)
    return build_weeks(schedule_path, weekly_status_path, race_date, today, run_rows=run_rows)


_EMBED_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
html, body {
  margin: 0; background: transparent;
  color: #323338;
  font-family: Figtree, "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 14px; line-height: 1.3;
}
.phases {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 0;
}
.phasebar {
  min-width: 0; background: #f5f6f8; border-left: 6px solid #c4c4c4;
  border-radius: 0 6px 6px 0; padding: 8px 10px 7px;
}
.phasebar.plan { border-left-color: #ff642e; background: #fff4ee; }
.phasebar-head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 2px 12px; flex-wrap: wrap; min-width: 0;
}
.phasebar-name {
  font-size: 13px; font-weight: 600; letter-spacing: -0.1px; color: #676879;
  min-width: 0;
}
.phasebar.plan .phasebar-name { color: #323338; }
.phasebar-km {
  margin-left: auto; font-size: 13px; font-weight: 600; color: #323338;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.phasebar-track {
  margin-top: 6px; height: 8px; background: #e6e9ef;
  border-radius: 999px; overflow: hidden;
}
.phasebar.plan .phasebar-track { background: #ffd0c2; }
.phasebar-fill { display: block; height: 100%; border-radius: 999px; background: #676879; }
.phasebar.plan .phasebar-fill { background: #ff642e; }
.phasebar-weeks { margin: 3px 0 0; color: #676879; font-size: 12px; line-height: 1.2; }
@media (max-width: 640px) {
  .phases { grid-template-columns: 1fr; gap: 6px; }
}
"""


def render_progress(schedule_path: str, weekly_status_path: str,
                    race_date: datetime.date,
                    today: datetime.date | None = None,
                    runs_path: str | None = None,
                    now: datetime.datetime | None = None) -> str:
    """Only the two phase bars, for an iframe on another site."""
    moment = _resolve_now(now)
    today = today or moment.date()
    weeks = _weeks_for_page(schedule_path, weekly_status_path, race_date, today, runs_path)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>Training progress</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600&amp;display=swap" rel="stylesheet">
<style>{_EMBED_STYLE}</style>
</head>
<body>
{_phase_bars(weeks)}
</body>
</html>
"""


def render(schedule_path: str, weekly_status_path: str, race_name: str,
           race_date: datetime.date, goal_pace: str,
           today: datetime.date | None = None,
           runs_path: str | None = None,
           now: datetime.datetime | None = None,
           site_title: str = "Marathon training") -> str:
    brussels_now = _resolve_now(now)
    today = today or brussels_now.date()
    updated = last_updated_label(brussels_now)
    weeks = _weeks_for_page(schedule_path, weekly_status_path, race_date, today, runs_path)
    grouped = group_weeks(weeks)
    groups_html = "\n".join(_group(bucket, grouped[bucket], today) for bucket in _GROUP_ORDER)
    title = f"{race_name} training"
    subtitle = (f"{_esc(race_name)} · {race_date.strftime('%B')} {race_date.day}, "
                f"{race_date.year} · goal pace {_esc(goal_pace)}/km")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{_esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600&amp;display=swap" rel="stylesheet">
<style>{_STYLE}</style>
</head>
<body>
  <div class="wrap">
    <header class="top">
      <div>
        <h1>{_esc(site_title)}</h1>
        <p class="subtitle">{subtitle}</p>
        <p class="updated">{_esc(updated)}</p>
      </div>
      <p class="countdown">{_esc(_countdown(race_date, today))}</p>
    </header>
    {_phase_bars(weeks)}
    <div class="board"><div class="board-inner">
{groups_html}
    </div></div>
    <footer>
      <p>The bar is green when a week is done or on pace, yellow when it is behind and the remaining kilometres still fit in the days left, and red when they do not. Weeks that have not started stay grey. Inside a week, the longest run fills the long session and the other runs fill the closest remaining distances. A past week counts as done at 85% of its planned distance.</p>
    </footer>
  </div>
</body>
</html>
"""
