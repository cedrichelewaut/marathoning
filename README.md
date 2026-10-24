# Marathoning

Training setup for Hamburg Marathon, 25 April 2027.

Live schedule: https://cedrichelewaut.github.io/marathoning/

The page compares the plan with `data/strava_runs.csv`. Every week shows
planned km versus actual km beside one progress bar. The bar is **green**
when the week is done or on pace, **yellow** when it is behind and the
remaining kilometres still fit in the days left (about 20 km a day), and
**red** when they do not, including a finished week under the done bar and
a week with less than two days left that is still a long way short. Weeks
that have not started stay **grey**.

**This week** is open, and the same comparison is in the expanded rows of
**Completed**. A session is the run and its distance, for example
`Easy run · 6 km`. Logged runs show their distance and time. Neither is
tied to a day; the week header keeps the date range. Runs are matched
within the week: the longest run fills the planned long run, and the other
runs fill the closest remaining distances. A matched run shows a gap such as `+1 km`,
`-1 km`, or `on plan` (within half a kilometre). Extra runs are
**Additional**. A session with no run is **Missed** once the week is over,
and **To do** until then. **Completed** stays collapsed; its header is the
actual-vs-planned total, e.g. `52/54 km completed, 4/4 weeks`. **Coming
up** is the rest of the plan. The book file stays local (see `.gitignore`).

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

Actual kilometres on the site come from one tracked file, `data/strava_runs.csv`.
It holds run rows only: no client secret, no token, no refresh token.
Strava has required a subscription for API apps since June 2026, so nothing
here calls the Strava API. `training/strava.py` is an unused client kept in
the tree; the generator does not import it, and CI does not need
`data/strava_auth.json`, `data/runs.csv`, or `books/`.

A morning updater appends new rows to `data/strava_runs.csv` on `main` through
the GitHub API (it does not run Python). That push triggers
`.github/workflows/regenerate-site.yml`, which runs `python cli.py sync-site`
and, if the totals or the page changed, commits `data/weekly_status.csv` and
`docs/` back to `main`. The same workflow then deploys GitHub Pages from the
regenerated `docs/` directory. A `GITHUB_TOKEN` push does not start
`pages.yml`, so the deploy step here is what publishes the page after the
commit. The workflow uses `contents: write`, `pages: write`, and
`id-token: write`. It does not stage `data/strava_runs.csv`, so the commit
cannot start the workflow again. Deploying Pages does not create another
commit.

### `data/strava_runs.csv`

Columns, in this order:

| Column | Format |
| --- | --- |
| `date` | `YYYY-MM-DD`, the local date of the run |
| `name` | Activity title. Quote the field if it contains a comma. |
| `distance_km` | Kilometres as a decimal, e.g. `8.02` |
| `moving_time` | `h:mm:ss`, e.g. `0:46:12` |
| `strava_activity_id` | Strava activity id. This is the dedupe key. |

```csv
date,name,distance_km,moving_time,strava_activity_id
2026-10-22,Morning run,8.02,0:46:12,12345678901
```

Append one row per activity. Repeating a `strava_activity_id` is safe: the
first row wins and the distance is counted once. A week counts toward the
collapsed Completed header (`52/54 km completed, 4/4 weeks`) when its actual
distance is at least 85% of the plan, the same on-track bar as
`python cli.py status`.

Regenerate the totals and the page:

```
python cli.py sync-site
```

That rewrites `data/weekly_status.csv` and `docs/index.html` from
`data/schedule.csv` plus `data/strava_runs.csv`. Running it again with the
same file produces the same output. You can also run it by hand from the
Actions tab (workflow **Regenerate site from logged runs**).

`python cli.py status` reads the same file.

### Manual export (optional, local only)

```
python cli.py import-runs path/to/export.csv --source strava   # or garmin
```

This appends to gitignored `data/runs.csv` and does not change the site.
To publish a run, add a row to `data/strava_runs.csv` and run `sync-site`.

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

```
python cli.py sync-site
git add data/strava_runs.csv data/weekly_status.csv docs/index.html
git commit -m "Update logged runs and site"
git push
```

Pushing to `main` triggers `.github/workflows/pages.yml`, which runs
`sync-site` on a clean checkout (no book file, no private run export, no API
token) and deploys `docs/`. A push that changes `data/strava_runs.csv` also
triggers `.github/workflows/regenerate-site.yml`. That workflow regenerates
the page, commits `data/weekly_status.csv` and `docs/` when they differ,
then deploys GitHub Pages from those files. The commit cannot retrigger
either workflow, because it is pushed with `GITHUB_TOKEN` and it does not
touch `data/strava_runs.csv`. `data/runs.csv`, `data/strava_auth.json`, and
`books/` stay gitignored.
