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


def status_for(week: WeekView, today: datetime.date) -> tuple[str, str]:
    """Return (css class, label) for the week's status pill.

    Upcoming weeks are Not started. A week at the on-track bar is Done.
    The current week stays On track until it ends, because a session can
    move to another day. A finished week under the bar is Behind.
    """
    del today  # The bucket is already chosen from this date.
    if week.bucket == "upcoming":
        return "not-started", "Not started"
    if week.planned_km <= 0 or counts_as_done(week.planned_km, week.actual_km):
        return "done", "Done"
    if week.bucket == "this-week":
        return "on-track", "On track"
    return "behind", "Behind"


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
        ))
    return views


def group_weeks(weeks: list[WeekView]) -> dict[str, list[WeekView]]:
    grouped = {key: [] for key in _GROUP_ORDER}
    for week in weeks:
        grouped[week.bucket].append(week)
    return grouped


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


def _plan_text(days: list[dict]) -> str:
    bits: list[str] = []
    for day in days:
        if _is_rest(day):
            continue
        parts: list[str] = []
        if day.get("distance_km"):
            parts.append(f"{fmt_km(float(day['distance_km']))} km")
        if day.get("pace_per_km"):
            parts.append(f"{day['pace_per_km']}/km")
        if day.get("duration"):
            parts.append(day["duration"])
        if parts:
            bits.append(" · ".join(parts))
    return " · ".join(bits) if bits else "—"


def _day_label(iso: str) -> str:
    day = datetime.date.fromisoformat(iso)
    return f"{day.strftime('%a')} {day.day}"


def _run_text(run: dict, *, include_date: bool) -> str:
    name = (run.get("name") or "").strip() or "Run"
    pieces: list[str] = []
    if include_date and run.get("date"):
        pieces.append(_day_label(run["date"]))
    pieces.append(name)
    pieces.append(f"{fmt_km(float(run['distance_km']))} km")
    moving = (run.get("moving_time") or "").strip()
    if moving:
        pieces.append(moving)
    return " · ".join(pieces)


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
        "<span>Day</span><span>Session</span><span>Plan</span><span>Logged run</span><span>Vs plan</span>"
        "</div>"
    ]
    for match in matches:
        if match.role == "additional" and match.run is not None:
            when = _day_label(match.run["date"]) if match.run.get("date") else ""
            what = (match.run.get("name") or "").strip() or "Run"
            plan = "—"
            logged = _run_text(match.run, include_date=False)
            logged_class = "logged"
        else:
            planned = match.planned or {}
            when = _day_label(planned["date"]) if planned.get("date") else ""
            what = planned.get("workout") or ""
            plan = _plan_text([planned]) if planned else "—"
            if match.run is not None:
                logged = _run_text(match.run, include_date=True)
                logged_class = "logged"
            else:
                logged = "—"
                logged_class = "logged wait"
        parts.append(
            '<div class="session">'
            f'<span class="when">{_esc(when)}</span>'
            f'<span class="what">{_esc(what)}</span>'
            f'<span class="plan">{_esc(plan)}</span>'
            f'<span class="{logged_class}">{_esc(logged)}</span>'
            f'<span class="spill"><span class="tag {_tag_class(match.label)}">{_esc(match.label)}</span></span>'
            "</div>"
        )
    return "".join(parts)


def _row(week: WeekView, today: datetime.date) -> str:
    css, label = status_for(week, today)
    width = bar_width(week)
    fill_html = (
        f'<span class="fill {css}" style="width:{_fmt_width(width)}%"></span>' if width else ""
    )
    distance = _metric(week.actual_km, week.planned_km)
    long_run = _metric(week.long_actual_km, week.long_planned_km)
    described = f"{fmt_km(week.actual_km)} of {fmt_km(week.planned_km)} kilometres"
    opened = " open" if week.bucket == "this-week" else ""
    return f"""<details class="item"{opened}>
<summary class="row">
  <span class="name"><svg class="chev" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>{_esc(_week_label(week))}</span>
  <span class="phase" title="{_esc(week.phase)}">{_esc(_phase_label(week.phase))}</span>
  <span class="progress"><span class="bar" role="img" aria-label="{_esc(described)}">{fill_html}</span></span>
  <span class="metric">{_esc(distance)}</span>
  <span class="metric">{_esc(long_run)}</span>
  <span class="pill {css}">{label}</span>
</summary>
<div class="subitems">{_session_rows(week)}</div>
</details>"""


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


def _group(bucket: str, weeks: list[WeekView], today: datetime.date) -> str:
    opened = "" if bucket == "completed" else " open"
    rows = "\n".join(_row(w, today) for w in weeks) if weeks else '<p class="empty">Nothing scheduled.</p>'
    title = _GROUP_TITLE[bucket]
    summary = _group_summary(bucket, weeks)
    return f"""<details class="group {bucket}"{opened}>
<summary class="ghead">
  <span class="gtitle"><svg class="chev" viewBox="0 0 16 16" width="18" height="18" aria-hidden="true"><path d="M6 3.5l5 4.5-5 4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="gname">{title}</span><span class="gsum">{_esc(summary)}</span></span>
</summary>
<div class="colhead" aria-hidden="true">
  <span></span><span>Phase</span><span>Progress</span><span>Distance</span><span>Long run</span><span>Status</span>
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
.countdown { margin: 0 0 2px; color: #676879; font-size: 14px; white-space: nowrap; }
.board { overflow-x: auto; padding-bottom: 8px; }
.board-inner { min-width: 980px; }
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
  grid-template-columns: minmax(200px, 1.6fr) 148px minmax(110px, 0.8fr) 120px 116px 168px;
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
.phase, .metric { font-size: 14px; color: #323338; white-space: nowrap; min-width: 0; }
.phase { overflow: hidden; text-overflow: ellipsis; }
.metric { font-variant-numeric: tabular-nums; }
.progress { display: flex; align-items: center; min-height: 40px; }
.bar {
  display: block; width: 100%; max-width: 132px; height: 14px;
  background: #e6e9ef; border-radius: 999px; overflow: hidden;
}
.fill { display: block; height: 100%; border-radius: 999px; }
.fill.done { background: #00c875; }
.fill.on-track { background: #579bfc; }
.fill.behind { background: #e2445c; }
.fill.not-started { background: #c4c4c4; }
.pill {
  display: flex; align-items: center; justify-content: center;
  height: 30px; margin: 5px 8px 5px 0; border-radius: 4px;
  color: #fff; font-size: 14px; font-weight: 500; white-space: nowrap;
}
.pill.done { background: #00c875; }
.pill.on-track { background: #579bfc; }
.pill.behind { background: #e2445c; }
.pill.not-started { background: #c4c4c4; }
.pill.sm { height: 26px; margin: 0; width: 100%; font-size: 13px; }
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
  grid-template-columns: 72px minmax(150px, 1.4fr) minmax(120px, 1fr) minmax(180px, 1.5fr) 116px;
  gap: 6px 12px; align-items: center; padding: 5px 0;
  border-top: 1px solid #eceff3;
}
.session.head {
  border-top: 0; color: #676879; font-size: 12px; padding: 2px 0 0;
}
.session .when, .session .what, .session .plan, .session .logged {
  font-size: 13px; color: #323338; min-width: 0;
}
.session .plan, .session .logged { font-variant-numeric: tabular-nums; }
.session .logged.miss { color: #e2445c; }
.session .logged.wait { color: #676879; }
.runline { display: block; overflow-wrap: anywhere; }
.why { margin: 0; color: #676879; font-size: 13px; padding: 6px 0; }
.empty { border-left: 6px solid var(--group); background: #f5f6f8; color: #676879;
  min-height: 40px; padding-left: 16px; display: flex; align-items: center; }
footer { margin-top: 36px; color: #9699a6; font-size: 12px; line-height: 1.5; max-width: 720px; }
footer p { margin: 0; }
@media (prefers-reduced-motion: reduce) { .chev { transition: none; } }
@media (max-width: 720px) {
  .wrap { padding: 20px 16px 48px; }
  h1 { font-size: 26px; }
  .top { flex-direction: column; align-items: flex-start; gap: 4px; }
  .subtitle { white-space: normal; }
  .board-inner { min-width: 0; }
  .colhead { display: none; }
  .row {
    grid-template-columns: minmax(0, 1fr) 112px;
    grid-template-areas:
      "name pill"
      "progress progress"
      "distance distance";
    row-gap: 2px;
    padding-bottom: 6px;
  }
  .name { grid-area: name; }
  .phase { display: none; }
  .progress { grid-area: progress; padding: 0 12px 2px 34px; }
  .bar { max-width: none; }
  .metric { grid-area: distance; padding: 0 12px 2px 34px; }
  .metric + .metric { display: none; }
  .pill { grid-area: pill; width: auto; min-width: 104px; margin: 6px 8px 6px 0; }
  .session.head { display: none; }
  .session {
    grid-template-columns: 58px minmax(0, 1fr) 104px;
    grid-template-areas:
      "when what spill"
      "plan plan plan"
      "logged logged logged";
    gap: 2px 8px;
    padding: 8px 0;
  }
  .session .when { grid-area: when; }
  .session .what { grid-area: what; }
  .session .spill { grid-area: spill; }
  .session .plan { grid-area: plan; color: #676879; font-size: 12px; }
  .session .logged { grid-area: logged; padding-bottom: 2px; }
}
"""


def _countdown(race_date: datetime.date, today: datetime.date) -> str:
    days = (race_date - today).days
    if days > 1:
        return f"{days} days to go"
    if days == 1:
        return "1 day to go"
    if days == 0:
        return "Race day"
    return "Race day has passed"


def render(schedule_path: str, weekly_status_path: str, race_name: str,
           race_date: datetime.date, goal_pace: str,
           today: datetime.date | None = None,
           runs_path: str | None = None) -> str:
    today = today or datetime.date.today()
    run_rows = None
    if runs_path:
        from training import status as status_mod
        run_rows, _skipped = status_mod.load_strava_runs(runs_path)
    weeks = build_weeks(schedule_path, weekly_status_path, race_date, today, run_rows=run_rows)
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
        <h1>Marathon training</h1>
        <p class="subtitle">{subtitle}</p>
      </div>
      <p class="countdown">{_esc(_countdown(race_date, today))}</p>
    </header>
    <div class="board"><div class="board-inner">
{groups_html}
    </div></div>
    <footer>
      <p>Every week shows logged kilometres against the plan. Inside a week, the longest run fills the long session and the other runs fill the closest remaining distances. A matched run shows its gap from the plan. Extra runs are Additional. A session with no run is Missed once the week is over, and To do until then. A past week counts as completed at 85% of its planned distance. Updated {today.isoformat()}.</p>
    </footer>
  </div>
</body>
</html>
"""
