# Marathoning

Training setup for Hamburg Marathon, 25 April 2027.

Live schedule: https://cedrichelewaut.github.io/marathoning/ (public — shows
the plan and aggregated weekly progress, no raw run data or the book file,
both of which stay local only, see `.gitignore`).

## Setup

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Schedule

`config.yaml` holds the race date, goal pace, and mileage targets. Edit it,
then regenerate:

```
python cli.py generate-schedule
```

Writes `data/schedule.csv`: flexible, easy-only base-building from whenever
you run this up to `training.plan_18wk_start`, then an 18-week block
structured like *Advanced Marathoning* chapter 9 ("Up to 55 Miles per
Week") — one long run, one medium-long run, rest days, mileage ramping to
`peak_weekly_km` with a lighter week every 4th. Every LT/VO2max-interval
and hill-sprint session from the book is replaced with general-aerobic or
marathon-pace running, since the goal is to avoid fast running. Strides are
kept but marked optional.

## Logging actual runs

Export your activities from Strava (bulk export) or Garmin Connect
(Activities list -> Export CSV), then:

```
python cli.py import-runs path/to/export.csv --source strava   # or garmin
```

Appends new runs to `data/runs.csv`, skipping ones already imported.

## Checking progress

```
python cli.py status            # current week
python cli.py status --week -1  # last week
python cli.py status --week 2   # two weeks from now
```

Compares actual vs planned weekly distance and long-run distance.

## Predicting finish time

From a recent race or hard effort:

```
python cli.py predict --time 19:30 --distance 5
```

From just your goal pace (training paces only, no result needed):

```
python cli.py predict --goal-pace 4:30
```

Uses Jack Daniels' VDOT formula plus a Riegel-formula cross-check.

## Publishing the schedule to GitHub Pages

After `import-runs` (or any time you want the public page to reflect
current progress):

```
python cli.py sync-status   # writes data/weekly_status.csv (aggregated, no raw runs)
python cli.py render-site   # writes docs/index.html, for local preview
git add data/schedule.csv data/weekly_status.csv
git commit -m "Update schedule/status"
git push
```

Pushing to `main` triggers `.github/workflows/pages.yml`, which rebuilds
`docs/index.html` from the committed CSVs and deploys it. `data/runs.csv`
(your raw per-run log) and `books/` (the copyrighted training book) are
gitignored and never leave your machine.
