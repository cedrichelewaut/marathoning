#!/usr/bin/env python3
"""Marathon training CLI.

Commands:
    generate-schedule           Build data/schedule.csv from config.yaml
    import-runs FILE --source {strava,garmin}
                                 Import an export into data/runs.csv
    status [--week N]           Compare actual vs planned for a week
    sync-status                 Write aggregated weekly status for all weeks
                                 (data/weekly_status.csv, safe to publish)
    render-site                 Build docs/index.html for GitHub Pages
    predict --time T --distance D [--goal]
                                 Predict finish times / show training paces
"""

from __future__ import annotations

import argparse
import datetime

import yaml

from training import importers, predict, schedule, site, status

CONFIG_PATH = "config.yaml"
SCHEDULE_PATH = "data/schedule.csv"
RUNS_PATH = "data/runs.csv"
WEEKLY_STATUS_PATH = "data/weekly_status.csv"
SITE_OUT_PATH = "docs/index.html"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _as_date(value) -> datetime.date:
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(value)


def cmd_generate_schedule(args: argparse.Namespace) -> None:
    cfg = load_config()
    race_date = _as_date(cfg["race"]["date"])
    plan_start = _as_date(cfg["training"]["plan_18wk_start"])
    today = datetime.date.today()

    base_weeks = schedule.generate_base_building(
        start_date=status.current_week_start(today) + datetime.timedelta(weeks=1),
        end_before=plan_start,
        start_km=cfg["training"]["base_building_start_km"],
        target_km=cfg["training"]["start_weekly_km"],
    )
    race_weeks = schedule.generate_18wk_plan(
        plan_start=plan_start,
        race_date=race_date,
        start_km=cfg["training"]["start_weekly_km"],
        peak_km=cfg["training"]["peak_weekly_km"],
    )
    all_weeks = base_weeks + race_weeks
    schedule.write_schedule_csv(SCHEDULE_PATH, all_weeks)
    print(f"Wrote {len(all_weeks)} weeks ({sum(len(w.days) for w in all_weeks)} days) "
          f"to {SCHEDULE_PATH}")
    print(f"Base-building: {len(base_weeks)} weeks, then the 18-week race-specific "
          f"block from {plan_start} to race day {race_date}.")


def cmd_import_runs(args: argparse.Namespace) -> None:
    if args.source == "strava":
        runs = importers.parse_strava_export(args.file)
    else:
        runs = importers.parse_garmin_export(args.file)
    n = importers.write_runs_csv(RUNS_PATH, runs, append=True)
    print(f"Parsed {len(runs)} runs from {args.file}, added {n} new (skipped duplicates) "
          f"to {RUNS_PATH}")


def cmd_status(args: argparse.Namespace) -> None:
    schedule_rows = status.load_schedule(SCHEDULE_PATH)
    run_rows = status.load_runs(RUNS_PATH)
    today = datetime.date.today()
    week_start = status.current_week_start(today)
    if args.week:
        week_start = week_start + datetime.timedelta(weeks=args.week)
    ws = status.week_status(schedule_rows, run_rows, week_start)
    print(f"Week of {ws.week_start}: planned {ws.planned_km:.1f} km, "
          f"actual {ws.actual_km:.1f} km ({ws.pct:.0f}%) -> {ws.verdict}")
    print(f"  Long run: planned {ws.long_run_planned_km:.1f} km, "
          f"longest actual this week {ws.long_run_actual_km:.1f} km")


def cmd_sync_status(args: argparse.Namespace) -> None:
    schedule_rows = status.load_schedule(SCHEDULE_PATH)
    run_rows = status.load_runs(RUNS_PATH)
    weeks = status.all_weeks_status(schedule_rows, run_rows)
    status.write_weekly_status_csv(WEEKLY_STATUS_PATH, weeks)
    print(f"Wrote aggregated status for {len(weeks)} weeks to {WEEKLY_STATUS_PATH} "
          "(no raw run data, safe to commit/publish)")


def cmd_render_site(args: argparse.Namespace) -> None:
    import os

    cfg = load_config()
    os.makedirs("docs", exist_ok=True)
    html_out = site.render(
        schedule_path=SCHEDULE_PATH,
        weekly_status_path=WEEKLY_STATUS_PATH,
        race_name=cfg["race"]["name"],
        race_date=_as_date(cfg["race"]["date"]),
        goal_pace=cfg["goal"]["pace_per_km"],
    )
    with open(SITE_OUT_PATH, "w") as f:
        f.write(html_out)
    open("docs/.nojekyll", "w").close()
    print(f"Wrote {SITE_OUT_PATH}")


def cmd_predict(args: argparse.Namespace) -> None:
    if args.time and args.distance:
        time_min = predict.parse_time_to_minutes(args.time)
        vdot = predict.vdot_from_result(args.distance, time_min)
        marathon_min = predict.time_for_distance(vdot, 42.195)
        riegel_min = predict.riegel_predict(time_min, args.distance, 42.195)
        paces = predict.training_paces(vdot)
        print(f"VDOT: {vdot:.1f}")
        print(f"Predicted marathon (VDOT): {predict.format_time(marathon_min)}")
        print(f"Predicted marathon (Riegel cross-check): {predict.format_time(riegel_min)}")
        print(f"Easy pace range: {predict.format_pace(paces.easy_min_per_km[0])} - "
              f"{predict.format_pace(paces.easy_min_per_km[1])}")
        print(f"Marathon pace: {predict.format_pace(paces.marathon_min_per_km)}")
    elif args.goal_pace:
        goal_pace = predict.parse_pace_to_min_per_km(args.goal_pace)
        goal_min = goal_pace * 42.195
        vdot = predict.vdot_from_result(42.195, goal_min)
        paces = predict.training_paces(vdot)
        print(f"Goal marathon time: {predict.format_time(goal_min)} "
              f"({predict.format_pace(goal_pace)})")
        print(f"Implied VDOT: {vdot:.1f}")
        print(f"Easy pace range: {predict.format_pace(paces.easy_min_per_km[0])} - "
              f"{predict.format_pace(paces.easy_min_per_km[1])}")
    else:
        raise SystemExit("Pass either --time and --distance, or --goal-pace")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate-schedule").set_defaults(func=cmd_generate_schedule)

    p_import = sub.add_parser("import-runs")
    p_import.add_argument("file")
    p_import.add_argument("--source", choices=["strava", "garmin"], required=True)
    p_import.set_defaults(func=cmd_import_runs)

    p_status = sub.add_parser("status")
    p_status.add_argument("--week", type=int, default=0,
                           help="Offset from current week, e.g. -1 for last week")
    p_status.set_defaults(func=cmd_status)

    sub.add_parser("sync-status").set_defaults(func=cmd_sync_status)
    sub.add_parser("render-site").set_defaults(func=cmd_render_site)

    p_predict = sub.add_parser("predict")
    p_predict.add_argument("--time", help="Result time, e.g. 19:30 or 1:45:00")
    p_predict.add_argument("--distance", type=float, help="Result distance in km")
    p_predict.add_argument("--goal-pace", help="Goal marathon pace per km, e.g. 4:30")
    p_predict.set_defaults(func=cmd_predict)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
