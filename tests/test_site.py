"""Board grouping, the collapsed-week summary, and the generated page."""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path

from training import site, status

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.write_text(text)


class SummaryTests(unittest.TestCase):
    def test_fmt_km_trims_trailing_zero(self) -> None:
        self.assertEqual(site.fmt_km(17), "17")
        self.assertEqual(site.fmt_km(0), "0")
        self.assertEqual(site.fmt_km(67.2), "67.2")

    def test_buckets_use_the_week_that_contains_today(self) -> None:
        today = datetime.date(2026, 10, 24)  # Saturday
        self.assertEqual(site.week_bucket(datetime.date(2026, 10, 12), today), "completed")
        self.assertEqual(site.week_bucket(datetime.date(2026, 10, 19), today), "this-week")
        self.assertEqual(site.week_bucket(datetime.date(2026, 10, 26), today), "upcoming")
        # Sunday is still this week; Monday rolls forward.
        self.assertEqual(site.week_bucket(datetime.date(2026, 10, 19), datetime.date(2026, 10, 25)), "this-week")
        self.assertEqual(site.week_bucket(datetime.date(2026, 10, 19), datetime.date(2026, 10, 26)), "completed")

    def test_done_matches_the_on_track_bar(self) -> None:
        self.assertTrue(site.counts_as_done(20, 17))    # 85%
        self.assertTrue(site.counts_as_done(20, 22))    # ahead
        self.assertFalse(site.counts_as_done(20, 16.9))
        self.assertTrue(site.counts_as_done(0, 0))

    def test_completed_summary_is_actual_over_planned(self) -> None:
        weeks = [
            site.WeekView(datetime.date(2026, 9, 28), "Base-building", 20, 18, 10, 10),
            site.WeekView(datetime.date(2026, 10, 5), "Base-building", 20, 10, 10, 4),
        ]
        self.assertEqual(site.completed_summary(weeks), "28/40 km completed, 1/2 weeks")
        self.assertEqual(site.completed_summary(weeks[:1]), "18/20 km completed, 1/1 week")
        self.assertEqual(site.completed_summary([]), "0/0 km completed, 0/0 weeks")


class PageTests(unittest.TestCase):
    def _render(self, today: datetime.date) -> str:
        schedule = """date,phase,weeks_out,workout,distance_km,pace_per_km,duration,notes,explanation
2026-09-28,Base-building,,Easy run,20,5:30,60m,keep it easy,Comfortable.
2026-10-05,Base-building,,Easy run,20,5:30,60m,,Comfortable.
2026-10-20,Base-building,,Long run,20,5:30,60m,,The long one.
2026-10-26,Taper,,Goal marathon,30,4:30,,race day,Race day.
"""
        weekly = """week_start,planned_km,actual_km,pct,verdict,long_run_planned_km,long_run_actual_km
2026-09-28,20.0,18.0,90,on track,20.0,18.0
2026-10-05,20.0,10.0,50,behind,20.0,8.0
2026-10-19,20.0,5.0,25,behind,20.0,0.0
2026-10-26,30.0,0.0,0,behind,30.0,0.0
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "schedule.csv", schedule)
            _write(root / "weekly.csv", weekly)
            return site.render(
                str(root / "schedule.csv"), str(root / "weekly.csv"),
                "Hamburg Marathon", datetime.date(2026, 10, 26), "4:30", today=today,
            )

    def test_three_groups_and_collapsed_summary(self) -> None:
        page = self._render(datetime.date(2026, 10, 24))
        self.assertLess(page.find('class="group completed"'), page.find('class="group this-week"'))
        self.assertLess(page.find('class="group this-week"'), page.find('class="group upcoming"'))

        tag_at = page.find('<details class="group completed"')
        tag = page[tag_at:page.find(">", tag_at) + 1]
        self.assertEqual(tag, '<details class="group completed">')
        self.assertIn("<details class=\"group this-week\" open>", page)
        self.assertIn("<details class=\"group upcoming\" open>", page)

        self.assertIn("28/40 km completed, 1/2 weeks", page)
        self.assertIn("5/20 km this week", page)
        self.assertIn(">Done<", page)
        self.assertIn(">Behind<", page)
        self.assertIn(">Not started<", page)
        self.assertNotIn(">Stuck<", page)
        self.assertNotIn(">Working on it<", page)
        self.assertNotIn(">Planned<", page)
        self.assertIn("Oct 26 – Nov 1 · Race", page)
        self.assertIn("0/30 km", page)
        self.assertIn("Logged run", page)
        self.assertEqual(page.count('<details class="item" open>'), 1)
        # Future weeks stay Not started even though the status file marks them behind.
        upcoming = page.split('class="group upcoming"', 1)[1]
        self.assertNotIn(">Behind<", upcoming)
        self.assertIn(">Not started<", upcoming)
        self.assertIn("width:90%", page)
        self.assertIn("width:50%", page)

    def test_status_pills_follow_the_plan(self) -> None:
        today = datetime.date(2026, 10, 19)  # Monday
        upcoming = site.WeekView(
            datetime.date(2026, 10, 26), "Base-building", 20, 0, 8, 0, bucket="upcoming",
        )
        done = site.WeekView(
            datetime.date(2026, 9, 28), "Base-building", 20, 18, 10, 10, bucket="completed",
        )
        behind = site.WeekView(
            datetime.date(2026, 10, 5), "Base-building", 20, 10, 10, 4, bucket="completed",
        )
        on_track = site.WeekView(
            datetime.date(2026, 10, 19), "Base-building", 20, 0, 8, 0,
            days=[{"date": "2026-10-21", "workout": "Long run", "distance_km": "8"}],
            bucket="this-week",
        )
        self.assertEqual(site.status_for(upcoming, today), ("not-started", "Not started"))
        self.assertEqual(site.status_for(done, today), ("done", "Done"))
        self.assertEqual(site.status_for(behind, today), ("behind", "Behind"))
        self.assertEqual(site.status_for(on_track, today), ("on-track", "On track"))
        missed = site.WeekView(
            datetime.date(2026, 10, 19), "Base-building", 20, 0, 8, 0,
            days=[{"date": "2026-10-19", "workout": "Easy run", "distance_km": "6"}],
            bucket="this-week",
        )
        self.assertEqual(site.status_for(missed, datetime.date(2026, 10, 20)), ("behind", "Behind"))
        self.assertEqual(
            site.session_status(6, 0, datetime.date(2026, 10, 19), datetime.date(2026, 10, 20)),
            ("behind", "Behind"),
        )
        self.assertEqual(
            site.session_status(6, 6, datetime.date(2026, 10, 19), datetime.date(2026, 10, 20)),
            ("done", "Done"),
        )
        self.assertEqual(
            site.session_status(6, 0, datetime.date(2026, 10, 24), datetime.date(2026, 10, 24)),
            ("not-started", "Not started"),
        )

    def test_real_schedule_renders_three_groups(self) -> None:
        page = site.render(
            str(ROOT / "data" / "schedule.csv"),
            str(ROOT / "data" / "weekly_status.csv"),
            "Hamburg Marathon", datetime.date(2027, 4, 25), "4:30",
            today=datetime.date(2026, 10, 24),
        )
        self.assertIn("Marathon training", page)
        self.assertIn("Completed", page)
        self.assertIn("This week", page)
        self.assertIn("Coming up", page)
        self.assertIn("km completed", page)
        self.assertNotIn("strava_auth", page)
        self.assertNotIn("refresh_token", page)


class StravaRunsFeedTheBoardTests(unittest.TestCase):
    def test_duplicate_activity_id_counts_once(self) -> None:
        raw = """date,name,distance_km,moving_time,strava_activity_id
2026-10-10,Morning,10.00,0:55:00,111
2026-10-10,Morning again,99.00,9:00:00,111
2026-10-11,Treadmill,5.5,0:30:00,222
"""
        schedule = """date,phase,weeks_out,workout,distance_km,pace_per_km,duration,notes,explanation
2026-10-10,Base-building,,Easy run,17,5:30,60m,,Easy.
2026-10-20,Base-building,,Easy run,20,5:30,60m,,Easy.
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "runs.csv", raw)
            _write(root / "schedule.csv", schedule)
            run_rows, skipped = status.load_strava_runs(str(root / "runs.csv"))
            self.assertEqual(skipped, 1)
            self.assertEqual([float(r["distance_km"]) for r in run_rows], [10.0, 5.5])
            weeks = status.all_weeks_status(status.load_schedule(str(root / "schedule.csv")), run_rows)
            status.write_weekly_status_csv(str(root / "weekly.csv"), weeks)
            status.write_weekly_status_csv(str(root / "weekly-2.csv"), weeks)
            self.assertEqual((root / "weekly.csv").read_bytes(), (root / "weekly-2.csv").read_bytes())
            page = site.render(
                str(root / "schedule.csv"), str(root / "weekly.csv"),
                "Hamburg Marathon", datetime.date(2027, 4, 25), "4:30",
                today=datetime.date(2026, 10, 24),
                runs_path=str(root / "runs.csv"),
            )
        # 15.5 km in the week of Oct 5 (planned 17) clears 85%. Oct 19 is this week.
        self.assertIn("15.5/17 km completed, 1/1 week", page)
        self.assertIn(">Done<", page)
        self.assertIn("0/20 km this week", page)
        self.assertIn("Morning", page)
        self.assertIn("Treadmill", page)
        self.assertNotIn("Morning again", page)
        self.assertNotIn("9:00:00", page)

    def test_this_week_matches_sessions_to_runs_by_date(self) -> None:
        raw = """date,name,distance_km,moving_time,strava_activity_id
2026-10-19,Morning run,6.10,0:34:12,1
2026-10-19,Morning run duplicate,99.00,9:00:00,1
2026-10-21,Short one,3.00,0:18:00,2
2026-10-22,Extra jog,2.50,0:15:00,3
"""
        schedule = """date,phase,weeks_out,workout,distance_km,pace_per_km,duration,notes,explanation
2026-10-19,Base-building,,Easy run,6,5:40,34m,,Easy.
2026-10-20,Base-building,,Easy run,6,5:40,34m,,Easy.
2026-10-21,Base-building,,Long run,8,5:38,45m,,Long.
2026-10-24,Base-building,,Easy run,4,5:40,24m,,Today.
2026-10-25,Base-building,,Easy run,4,5:40,24m,,Tomorrow.
"""
        weekly = """week_start,planned_km,actual_km,pct,verdict,long_run_planned_km,long_run_actual_km
2026-10-19,28.0,0.0,0,behind,8.0,0.0
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "runs.csv", raw)
            _write(root / "schedule.csv", schedule)
            _write(root / "weekly.csv", weekly)
            rows, skipped = status.load_strava_runs(str(root / "runs.csv"))
            self.assertEqual(skipped, 1)
            self.assertEqual(rows[0]["name"], "Morning run")
            self.assertEqual(rows[0]["moving_time"], "0:34:12")
            page = site.render(
                str(root / "schedule.csv"), str(root / "weekly.csv"),
                "Hamburg Marathon", datetime.date(2027, 4, 25), "4:30",
                today=datetime.date(2026, 10, 24),
                runs_path=str(root / "runs.csv"),
            )
        self.assertIn("11.6/28 km this week", page)
        self.assertIn(">Behind<", page)
        self.assertIn("Morning run · 6.1 km · 0:34:12", page)
        self.assertIn("Short one · 3 km · 0:18:00", page)
        self.assertIn("Extra jog · 2.5 km · 0:15:00", page)
        self.assertIn("No run logged", page)
        self.assertIn("Not yet", page)
        self.assertNotIn("Morning run duplicate", page)
        self.assertNotIn("9:00:00", page)
        self.assertIn('<details class="item" open>', page)
        # Monday's 6.1 km meets the 6 km session. Tuesday was missed.
        monday = page.split("Mon 19", 1)[1].split("Tue 20", 1)[0]
        tuesday = page.split("Tue 20", 1)[1].split("Wed 21", 1)[0]
        saturday = page.split("Sat 24", 1)[1].split("Sun 25", 1)[0]
        self.assertIn(">Done<", monday)
        self.assertIn(">Behind<", tuesday)
        self.assertIn("No run logged", tuesday)
        self.assertIn(">Not started<", saturday)
        self.assertIn("Not yet", saturday)

    def test_bad_time_and_missing_id_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.csv"
            _write(path, "date,name,distance_km,moving_time,strava_activity_id\n"
                   "2026-10-10,Run,5,45:00,\n")
            with self.assertRaises(ValueError):
                status.load_strava_runs(str(path))
            _write(path, "date,name,distance_km,moving_time,strava_activity_id\n"
                   "2026-10-10,Run,5,0:45:00,9\n")
            rows, skipped = status.load_strava_runs(str(path))
            self.assertEqual(skipped, 0)
            self.assertEqual(rows[0]["distance_km"], "5.0000")
            self.assertEqual(rows[0]["name"], "Run")
            self.assertEqual(rows[0]["moving_time"], "0:45:00")


if __name__ == "__main__":
    unittest.main()
