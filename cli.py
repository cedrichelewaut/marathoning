#!/usr/bin/env python3
"""Marathon training CLI.

Commands:
    generate-schedule           Build data/schedule.csv from config.yaml
    import-runs FILE --source {strava,garmin}
                                 Import an export into data/runs.csv
    status [--week N]           Compare actual vs planned for a week
    sync-status                 Write aggregated weekly status for all weeks
                                 (data/weekly_status.csv) from data/strava_runs.csv
    sync-site                   Rebuild weekly status, docs/index.html, and
                                 docs/progress.html from data/strava_runs.csv. Idempotent.
    render-site                 Build docs/index.html and docs/progress.html
                                 from weekly status and the run log
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
STRAVA_RUNS_PATH = "data/strava_runs.csv"
WEEKLY_STATUS_PATH = "data/weekly_status.csv"
SITE_OUT_PATH = "docs/index.html"
PROGRESS_OUT_PATH = "docs/progress.html"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _as_date(value) -> datetime.date:
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(value)


def _site_title(cfg: dict) -> str:
    """Board heading. config.yaml site.title, or the generic default."""
    site_cfg = cfg.get("site") or {}
    title = str(site_cfg.get("title") or "").strip()
    return title or "Marathon training"


def cmd_generate_schedule(args: argparse.Namespace) -> None:
    cfg = load_config()
    race_date = _as_date(cfg["race"]["date"])
    plan_start = _as_date(cfg["training"]["plan_18wk_start"])
    peak_km = cfg["training"]["peak_weekly_km"]
    today = datetime.date.today()
    mp_pace = predict.parse_pace_to_min_per_km(cfg["goal"]["pace_per_km"])

    base_start = status.current_week_start(today) + datetime.timedelta(weeks=1)
    n_base_weeks = max(0, (plan_start - base_start).days // 7)
    n_race_weeks = ((race_date - plan_start).days // 7) + 1
    race_start_km = cfg["training"]["race_block_start_km"]

    # The 18-week block follows the book's own progression (race_start_km
    # -> peak_km) unmodified. Base-building ramps from near zero toward
    # the book's own stated prerequisite for starting that block: at
    # least 25 mi/wk (40 km) total, with a long run close to the first
    # week's 12 mi (19 km), achieved in "the last month" beforehand. No
    # cutback weeks here (unlike generate_book_progression's), a 10-week
    # on-ramp doesn't leave room for them and still hit that target.
    base_total_target = cfg["training"]["base_building_final_total_km"]
    base_long_target = cfg["training"]["base_building_final_long_km"]
    base_totals = schedule.generate_mileage_ramp(
        start_km=cfg["training"]["base_building_start_km"],
        peak_km=base_total_target, n_weeks=n_base_weeks,
        recovery_every=n_base_weeks + 1,
    )
    base_long_runs = schedule.generate_mileage_ramp(
        start_km=round(cfg["training"]["base_building_start_km"] * 0.4),
        peak_km=base_long_target, n_weeks=n_base_weeks,
        recovery_every=n_base_weeks + 1,
    )
    race_totals = schedule.generate_book_progression(
        start_km=race_start_km, peak_km=peak_km, n_weeks=n_race_weeks,
    )

    base_weeks = schedule.generate_base_building(
        start_date=base_start, weekly_totals=base_totals, weekly_long_runs=base_long_runs,
        peak_km=peak_km, mp_pace=mp_pace,
    )
    race_weeks = schedule.generate_18wk_plan(
        plan_start=plan_start, weekly_totals=race_totals, peak_km=peak_km, mp_pace=mp_pace,
    )
    all_weeks = base_weeks + race_weeks
    schedule.write_schedule_csv(SCHEDULE_PATH, all_weeks)
    print(f"Wrote {len(all_weeks)} weeks ({sum(len(w.days) for w in all_weeks)} days) "
          f"to {SCHEDULE_PATH}")
    print(f"Base-building: {len(base_weeks)} weeks, then the 18-week race-specific "
          f"block from {plan_start} to race day {race_date}.")
    print(f"Marathon pace: {predict.format_pace(mp_pace)} (all other paces derived from this, "
          f"per the book's Table 1.1 percentages)")


def cmd_import_runs(args: argparse.Namespace) -> None:
    if args.source == "strava":
        runs = importers.parse_strava_export(args.file)
    else:
        runs = importers.parse_garmin_export(args.file)
    n = importers.write_runs_csv(RUNS_PATH, runs, append=True)
    print(f"Parsed {len(runs)} runs from {args.file}, added {n} new (skipped duplicates) "
          f"to {RUNS_PATH}")


def _rebuild_weekly_status() -> tuple[int, int, int]:
    """Returns (weeks, runs counted, duplicate ids skipped)."""
    schedule_rows = status.load_schedule(SCHEDULE_PATH)
    run_rows, skipped = status.load_strava_runs(STRAVA_RUNS_PATH)
    weeks = status.all_weeks_status(schedule_rows, run_rows)
    status.write_weekly_status_csv(WEEKLY_STATUS_PATH, weeks)
    return len(weeks), len(run_rows), skipped


def cmd_status(args: argparse.Namespace) -> None:
    schedule_rows = status.load_schedule(SCHEDULE_PATH)
    run_rows, _skipped = status.load_strava_runs(STRAVA_RUNS_PATH)
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
    weeks, runs, skipped = _rebuild_weekly_status()
    print(f"Wrote aggregated status for {weeks} weeks to {WEEKLY_STATUS_PATH} "
          f"from {runs} runs in {STRAVA_RUNS_PATH}"
          + (f" ({skipped} duplicate ids skipped)" if skipped else ""))


def cmd_sync_site(args: argparse.Namespace) -> None:
    """Regenerate weekly totals and the page. Safe to run twice."""
    weeks, runs, skipped = _rebuild_weekly_status()
    cmd_render_site(args)
    extra = f" ({skipped} duplicate ids skipped)" if skipped else ""
    print(f"Regenerated {WEEKLY_STATUS_PATH} ({weeks} weeks), {SITE_OUT_PATH}, "
          f"and {PROGRESS_OUT_PATH} from {runs} runs in {STRAVA_RUNS_PATH}{extra}.")


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
        runs_path=STRAVA_RUNS_PATH,
        site_title=_site_title(cfg),
    )
    with open(SITE_OUT_PATH, "w") as f:
        f.write(html_out)
    progress_out = site.render_progress(
        schedule_path=SCHEDULE_PATH,
        weekly_status_path=WEEKLY_STATUS_PATH,
        race_date=_as_date(cfg["race"]["date"]),
        runs_path=STRAVA_RUNS_PATH,
    )
    with open(PROGRESS_OUT_PATH, "w") as f:
        f.write(progress_out)
    open("docs/.nojekyll", "w").close()
    print(f"Wrote {SITE_OUT_PATH} and {PROGRESS_OUT_PATH}")


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
    sub.add_parser("sync-site").set_defaults(func=cmd_sync_site)
    sub.add_parser("render-site").set_defaults(func=cmd_render_site)

    p_predict = sub.add_parser("predict")
    p_predict.add_argument("--time", help="Result time, e.g. 19:30 or 1:45:00")
    p_predict.add_argument("--distance", type=float, help="Result distance in km")
    p_predict.add_argument("--goal-pace", help="Goal marathon pace per km, e.g. 4:30")
    p_predict.set_defaults(func=cmd_predict)

    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
