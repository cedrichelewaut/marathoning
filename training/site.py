"""Render a static HTML page from the schedule + aggregated weekly status.

No raw per-run data is used here, only data/schedule.csv (the plan) and
data/weekly_status.csv (aggregated planned/actual totals per week), so
nothing from the private run log ends up in the published site.
"""

from __future__ import annotations

import csv
import datetime
import html


def _load_schedule_by_week(schedule_path: str) -> dict[datetime.date, list[dict]]:
    weeks: dict[datetime.date, list[dict]] = {}
    with open(schedule_path, newline="") as f:
        for row in csv.DictReader(f):
            d = datetime.date.fromisoformat(row["date"])
            week_start = d - datetime.timedelta(days=d.weekday())
            weeks.setdefault(week_start, []).append(row)
    return weeks


def render(schedule_path: str, weekly_status_path: str, race_name: str,
           race_date: datetime.date, goal_pace: str) -> str:
    from training import status as status_mod

    weeks_by_start = _load_schedule_by_week(schedule_path)
    status_by_week = status_mod.load_weekly_status(weekly_status_path)
    today = datetime.date.today()

    rows_html = []
    for week_start in sorted(weeks_by_start):
        days = sorted(weeks_by_start[week_start], key=lambda r: r["date"])
        phase = days[0]["phase"]
        total_km = sum(float(d["distance_km"]) for d in days if d["distance_km"])
        st = status_by_week.get(week_start.isoformat())

        if week_start > today:
            badge = ("upcoming", "")
        elif st:
            badge = (st["verdict"].replace(" ", "-"), f"{st['actual_km']} / {st['planned_km']} km")
        else:
            badge = ("no-data", "")

        day_cells = "".join(
            f'<li><span class="d">{datetime.date.fromisoformat(d["date"]).strftime("%a")}</span> '
            f'<span class="w">{html.escape(d["workout"])}</span>'
            + (f' <span class="km">{d["distance_km"]} km</span>' if d["distance_km"] else "")
            + (f'<div class="notes">{html.escape(d["notes"])}</div>' if d["notes"] else "")
            + "</li>"
            for d in days
        )

        rows_html.append(f"""
        <section class="week {badge[0]}">
          <header>
            <h2>Week of {week_start.strftime("%b %d, %Y")}</h2>
            <span class="phase">{html.escape(phase)}</span>
            <span class="total">{total_km:.0f} km planned</span>
            {f'<span class="status">{badge[0].replace("-", " ")} ({badge[1]})</span>' if badge[1] else f'<span class="status">{badge[0].replace("-", " ")}</span>'}
          </header>
          <ul class="days">{day_cells}</ul>
        </section>""")

    days_to_race = (race_date - today).days

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(race_name)} training</title>
<style>
  :root {{
    --bg: #fafaf8; --fg: #1a1a1a; --muted: #6b6b6b; --card: #ffffff;
    --border: #e4e2dd; --accent: #2a6f4e;
    --ontrack: #2a6f4e; --behind: #b5452e; --ahead: #2a6f4e; --upcoming: #8b8578;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #16161a; --fg: #e8e6e1; --muted: #9a968c; --card: #1f1f24;
      --border: #333; --accent: #4fae84; }}
  }}
  body {{ margin: 0; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    padding: 24px 16px 60px; }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 2px; }}
  .sub {{ color: var(--muted); margin-bottom: 24px; }}
  section.week {{ background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 14px; }}
  section.week header {{ display: flex; flex-wrap: wrap; gap: 8px 14px;
    align-items: baseline; margin-bottom: 8px; }}
  section.week h2 {{ font-size: 1rem; margin: 0; }}
  .phase {{ color: var(--muted); font-size: 0.85rem; }}
  .total {{ color: var(--muted); font-size: 0.85rem; margin-left: auto; }}
  .status {{ font-size: 0.78rem; font-weight: 600; text-transform: uppercase;
    padding: 2px 8px; border-radius: 999px; background: var(--border); }}
  .week.on-track .status, .week.ahead .status {{ background: var(--ontrack); color: #fff; }}
  .week.behind .status {{ background: var(--behind); color: #fff; }}
  .week.upcoming .status {{ background: transparent; color: var(--upcoming); }}
  ul.days {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }}
  ul.days li {{ font-size: 0.9rem; padding: 2px 0; }}
  .d {{ color: var(--muted); width: 2.4em; display: inline-block; }}
  .km {{ color: var(--muted); }}
  .notes {{ color: var(--muted); font-size: 0.8rem; margin-left: 2.4em; }}
  [hidden] {{ display: none !important; }}
</style>
</head>
<body>
  <div class="wrap">
    <h1>{html.escape(race_name)} &mdash; {race_date.strftime("%B %d, %Y")}</h1>
    <p class="sub">{days_to_race} days to go &middot; goal pace {html.escape(goal_pace)}/km
      &middot; generated {today.isoformat()}</p>
    {"".join(rows_html)}
  </div>
</body>
</html>"""
