# Running tracker

A static training board. A config file builds the plan, a CSV holds the runs you have logged, and GitHub Actions publishes the page. No server and no API secret.

This repo’s board: [https://cedrichelewaut.github.io/running-tracker/](https://cedrichelewaut.github.io/running-tracker/)

Embed the two phase bars in an iframe from [progress.html](https://cedrichelewaut.github.io/running-tracker/progress.html).

Source: [https://github.com/cedrichelewaut/running-tracker](https://github.com/cedrichelewaut/running-tracker)

## Use this as a template

1. Fork the repo. After the template setting is on, **Use this template** does the same thing.
2. Edit `config.yaml`. Every field is listed below. `config.example.yaml` is a blank start.
3. Rebuild the plan and the page:

   ```
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python3 cli.py generate-schedule
   python3 cli.py sync-site
   ```

4. Replace `data/strava_runs.csv`. The file in this repo is the original log. A fresh file can be just the header, or the sample row in `data/strava_runs.example.csv`.
5. Enable GitHub Pages: **Settings → Pages → Build and deployment → Source: GitHub Actions**. On a fork, enable Actions if GitHub has them paused, and approve the `github-pages` environment if it asks.
6. Push to `main`.

Your board is `https://<user>.github.io/<repo>/`. The embed is `progress.html` on that same site. Put those two URLs in `site.pages_url` and `site.repo_url`.

No repository secrets. Both workflows use the built-in `GITHUB_TOKEN`.

## Configuration

`site.title` is the heading on the board. The browser title is `<race.name> training`. `site.pages_url` and `site.repo_url` are the public links for this project. They are not printed on the page.

`race.name` and `race.date` are the race. `goal.pace_per_km` is the goal pace, `min:sec` per km. Other paces are derived from it.

`training.plan_18wk_start` is the Monday of week 1. It is 17 weeks before the Monday of the week that contains `race.date`. Earlier weeks are base building.

`training.peak_weekly_km` is the peak week of the 18-week block. `training.race_block_start_km` is that block’s first week. `training.base_building_start_km` is the first base week. `training.base_building_final_total_km` and `training.base_building_final_long_km` are the weekly distance and long run to reach by the last base week.

`training.avoid_fast_running` replaces LT, VO2max, and hill sessions with general aerobic or marathon-pace running. Optional strides stay.

After editing, run `python3 cli.py generate-schedule` and commit `data/schedule.csv`.

## Plan and phases

Base building is easy running on flexible days, from `plan_18wk_start` backward. The 18-week block is the race-specific plan: week 1 through week 18, ending on race week. The board labels the two parts **Base building** and **Marathon training · 18 weeks**, inside Completed, This week, and Coming up.

The 18-week mileage shape lives in `training/schedule.py`. It follows the progression in *Advanced Marathoning* (Pfitzinger & Douglas), chapter 9, “Up to 55 miles per week”, scaled to `peak_weekly_km`. The book file itself is not in the repo. `books/` is gitignored.

Each week shows planned km against logged km. The bar is green when the week is done or on pace, yellow when it is behind and the remainder still fits in the days left (about 20 km a day), and red when it does not. Weeks that have not started stay grey. A finished week counts as done at 85% of its planned distance.

Runs match inside the week, not to a calendar day. The longest run fills the long session. The other runs fill the closest remaining distances. A match is `on plan` within half a kilometre, otherwise `+1 km` or `-1 km`. Extra runs are **Additional**. A session with no run is **To do** until the week ends, then **Missed**.

The two bars at the top, and on `progress.html`, are the same split: logged km against planned km for base building, and for the 18-week block, plus how many finished weeks hit the 85% bar.

## Getting your run data

The code that reads a Strava account directly is not in this repo. Part of that integration is proprietary.

Runs here come from Strava. Strava has required a subscription for API apps since 2026, so this project does not call the API. A daily job reads the Strava training log and appends new rows to `data/strava_runs.csv` on `main`. That push starts **Regenerate site from logged runs**, which rebuilds `docs/index.html` and `docs/progress.html` and deploys Pages.

`training/strava.py` is an unused client. Nothing in the generator or the workflows imports it. Do not commit `data/strava_auth.json`.

### CSV

| Column | Format |
| --- | --- |
| `date` | `YYYY-MM-DD` |
| `name` | Activity title. Quote it if it contains a comma. |
| `distance_km` | Kilometres, e.g. `8.02` |
| `moving_time` | `h:mm:ss` |
| `strava_activity_id` | Dedupe key. The first row wins. |

```csv
date,name,distance_km,moving_time,strava_activity_id
2026-10-22,Morning run,8.02,0:46:12,12345678901
```

### Other ways to add runs

Edit `data/strava_runs.csv` by hand and push to `main`.

Or import a Strava or Garmin export locally:

```
python3 cli.py import-runs path/to/export.csv --source strava
python3 cli.py import-runs path/to/export.csv --source garmin
```

That writes gitignored `data/runs.csv` only. Copy the rows you want into `data/strava_runs.csv` to publish them.

## Commands

```
python3 cli.py generate-schedule   # config.yaml -> data/schedule.csv
python3 cli.py sync-site           # CSV -> weekly totals, index, and progress.html
python3 cli.py status              # this week; --week -1 or --week 2 to move
python3 cli.py predict --time 19:30 --distance 5
python3 cli.py predict --goal-pace 4:30
```

`sync-site` is safe to run twice. Pushing `data/strava_runs.csv` to `main` runs it again in Actions and deploys the result. Any other push to `main` deploys through **Deploy schedule to Pages**.

There is no license file yet.
