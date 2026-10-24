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
    strava-auth                 One-time Strava API authorization
    sync-strava [--days N]       Pull recent runs from Strava into data/runs.csv
    predict --time T --distance D [--goal]
                                 Predict finish times / show training paces
"""

from __future__ import annotations

import argparse
import datetime

import yaml

from training import importers, predict, schedule, site, status, strava

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


def cmd_strava_auth(args: argparse.Namespace) -> None:
    existing = strava.load_auth()
    if existing and not args.force:
        print("Already authorized (data/strava_auth.json exists). Pass --force to redo it.")
        return
    client_id = input("Strava Client ID (from strava.com/settings/api): ").strip()
    client_secret = input("Strava Client Secret: ").strip()
    print("\nOpen this URL, click Authorize, then copy the FULL URL you land on "
          "(it will 404, that's expected, just copy the address bar):\n")
    print(strava.authorize_url(client_id))
    redirected = input("\nPaste the full redirected URL (or just the code= value): ").strip()
    if "code=" in redirected:
        code = redirected.split("code=")[1].split("&")[0]
    else:
        code = redirected
    auth = strava.exchange_code(client_id, client_secret, code)
    strava.save_auth(auth)
    print(f"\nSaved to {strava.AUTH_PATH} (gitignored, never commit this file). "
          "Run `python cli.py sync-strava` any time to pull recent runs.")


def cmd_sync_strava(args: argparse.Namespace) -> None:
    auth = strava.load_auth()
    if not auth:
        raise SystemExit("Not authorized yet. Run `python cli.py strava-auth` first.")
    auth = strava.ensure_access_token(auth)

    if auth.get("last_sync_epoch"):
        after_epoch = auth["last_sync_epoch"]
    else:
        after_epoch = int((datetime.datetime.now() - datetime.timedelta(days=args.days)).timestamp())

    activities = strava.fetch_runs(auth, after_epoch)
    runs = strava.to_run_records(activities)
    n = importers.write_runs_csv(RUNS_PATH, runs, append=True)
    auth["last_sync_epoch"] = int(datetime.datetime.now().timestamp())
    strava.save_auth(auth)
    print(f"Pulled {len(runs)} runs from Strava, added {n} new (skipped duplicates) to {RUNS_PATH}")


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

    p_strava_auth = sub.add_parser("strava-auth")
    p_strava_auth.add_argument("--force", action="store_true", help="Redo authorization")
    p_strava_auth.set_defaults(func=cmd_strava_auth)

    p_sync_strava = sub.add_parser("sync-strava")
    p_sync_strava.add_argument("--days", type=int, default=30,
                                help="On first sync, how many days back to pull (default 30)")
    p_sync_strava.set_defaults(func=cmd_sync_strava)

    p_predict = sub.add_parser("predict")
    p_predict.add_argument("--time", help="Result time, e.g. 19:30 or 1:45:00")
    p_predict.add_argument("--distance", type=float, help="Result distance in km")
    p_predict.add_argument("--goal-pace", help="Goal marathon pace per km, e.g. 4:30")
    p_predict.set_defaults(func=cmd_predict)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
