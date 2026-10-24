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
    def test_phase_progress_counts_finished_weeks_and_logged_km(self) -> None:
        weeks = [
            site.WeekView(datetime.date(2026, 10, 5), "Base-building", 17, 16.54, 11, 10,
                          bucket="completed"),
            site.WeekView(datetime.date(2026, 10, 12), "Base-building", 19, 26.01, 7, 12,
                          bucket="completed"),
            site.WeekView(datetime.date(2026, 10, 19), "Base-building", 20, 6, 8, 6,
                          bucket="this-week"),
            site.WeekView(datetime.date(2026, 12, 21), "Endurance", 54, 0, 18, 0,
                          bucket="upcoming", plan_week=1),
        ]
        base, plan = site.phase_progress(weeks)
        self.assertEqual(site.phase_km_label(base), "48.5 km / 56 km")
        self.assertEqual(site.phase_weeks_label(base), "2/3 weeks")
        self.assertEqual(site.phase_km_label(plan), "0 km / 54 km")
        self.assertEqual(site.phase_weeks_label(plan), "0/1 week")
        self.assertAlmostEqual(base.pct, 48.55 / 56 * 100, places=2)
        self.assertEqual(plan.pct, 0.0)

    def test_eighteen_week_block_counts_back_from_race_week(self) -> None:
        race = datetime.date(2027, 4, 25)  # Sunday
        self.assertEqual(site.plan_block_start(race), datetime.date(2026, 12, 21))
        self.assertIsNone(site.marathon_week_number(datetime.date(2026, 12, 14), race))
        self.assertEqual(site.marathon_week_number(datetime.date(2026, 12, 21), race), 1)
        self.assertEqual(site.marathon_week_number(datetime.date(2027, 4, 19), race), 18)
        self.assertIsNone(site.marathon_week_number(datetime.date(2027, 4, 26), race))

    def test_last_updated_uses_brussels_time(self) -> None:
        moment = datetime.datetime(2026, 10, 24, 10, 1, tzinfo=datetime.timezone.utc)
        self.assertEqual(site.last_updated_label(moment), "Last updated 24 Oct 2026, 12:01")

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
        self.assertIn('class="fill green" style="width:90%"', page)
        self.assertIn('class="fill red" style="width:50%"', page)
        self.assertIn('class="fill yellow" style="width:25%"', page)
        self.assertNotIn('class="pill', page)
        self.assertNotIn(">Done<", page)
        self.assertNotIn(">On track<", page)
        self.assertNotIn(">Not started<", page)
        self.assertNotIn(">Status<", page)
        self.assertIn("Oct 26 – Nov 1 · Race", page)
        self.assertIn("0/30 km", page)
        self.assertIn("Logged run", page)
        self.assertIn(">Missed<", page)
        self.assertIn(">To do<", page)
        self.assertEqual(page.count('<details class="item" open>'), 1)
        upcoming = page.split('class="group upcoming"', 1)[1]
        self.assertNotIn("fill red", upcoming)
        self.assertNotIn("fill yellow", upcoming)
        self.assertNotIn("fill green", upcoming)
        self.assertNotIn(">Missed<", upcoming)
        self.assertIn(">To do<", upcoming)
        self.assertIn("width:90%", page)
        self.assertIn("width:50%", page)

    def test_progress_bar_color_follows_pace(self) -> None:
        monday = datetime.date(2026, 10, 19)
        saturday = datetime.date(2026, 10, 24)
        sunday = datetime.date(2026, 10, 25)

        def week(start, planned, actual, bucket):
            return site.WeekView(start, "Base-building", planned, actual, 8, 0, bucket=bucket)

        self.assertEqual(site.progress_tone(week(datetime.date(2026, 10, 26), 25, 0, "upcoming"), monday), "neutral")
        self.assertEqual(site.progress_tone(week(datetime.date(2026, 9, 28), 20, 18, "completed"), saturday), "green")
        self.assertEqual(site.progress_tone(week(datetime.date(2026, 10, 5), 20, 10, "completed"), saturday), "red")
        # Monday, nothing elapsed yet: still on pace.
        self.assertEqual(site.progress_tone(week(datetime.date(2026, 10, 19), 20, 0, "this-week"), monday), "green")
        # Saturday with nothing logged: behind, and two days can still cover 25 km.
        self.assertEqual(site.progress_tone(week(datetime.date(2026, 10, 19), 25, 0, "this-week"), saturday), "yellow")
        # Sunday with 25 km still to go is more than one day can cover.
        self.assertEqual(site.progress_tone(week(datetime.date(2026, 10, 19), 25, 0, "this-week"), sunday), "red")
        # Sunday with 13 km left is short of the line, and still runnable.
        self.assertEqual(site.progress_tone(week(datetime.date(2026, 10, 19), 25, 12, "this-week"), sunday), "yellow")

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
        self.assertIn("Easy run · 6 km", page)
        self.assertIn("Long run · 8 km", page)
        self.assertIn("Oct 19 – 25", page)
        self.assertIn("Last updated", page)
        self.assertIn("Base building", page)
        self.assertIn("Marathon training · 18 weeks", page)
        upcoming = page.split('class="group upcoming"', 1)[1]
        self.assertLess(upcoming.find("Base building"), upcoming.find("Marathon training · 18 weeks"))
        week_one = upcoming.find("Dec 21 – 27")
        self.assertIn(">Week 1<", upcoming[week_one - 40:week_one])
        week_eighteen = upcoming.find("Apr 19 – 25")
        self.assertIn(">Week 18<", upcoming[week_eighteen - 40:week_eighteen])
        completed = page.split('class="group completed"', 1)[1].split('class="group this-week"', 1)[0]
        self.assertIn("Base building", completed)
        self.assertNotIn("Marathon training · 18 weeks", completed)
        self.assertNotIn("flexible day", page)
        self.assertNotIn(">Day<", page)
        self.assertIn('class="phasebar base"', page)
        self.assertIn('class="phasebar plan"', page)
        self.assertIn("km / ", page)
        self.assertIn("0/18 weeks", page)
        self.assertIn("fill green", page)
        self.assertIn("bar neutral", page)
        self.assertNotIn('class="pill', page)
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
        self.assertIn("fill green", page)
        self.assertIn("0/20 km this week", page)
        self.assertIn("Morning", page)
        self.assertIn("Treadmill", page)
        self.assertNotIn("Morning again", page)
        self.assertNotIn("9:00:00", page)

    def test_matches_runs_to_sessions_within_the_week(self) -> None:
        self.assertEqual(site.delta_label(6.1, 6), "on plan")
        self.assertEqual(site.delta_label(6.5, 6), "on plan")
        self.assertEqual(site.delta_label(6.6, 6), "+1 km")
        self.assertEqual(site.delta_label(5.4, 6), "-1 km")
        self.assertEqual(site.delta_label(15.2, 16), "-1 km")
        self.assertEqual(site.delta_label(9.4, 8), "+1 km")

        # The long run moved to Monday. The easy run happened on the long day.
        swapped = site.match_sessions(
            [
                {"date": "2026-10-19", "workout": "Easy run", "distance_km": "6"},
                {"date": "2026-10-21", "workout": "Long run", "distance_km": "14"},
            ],
            [
                {"date": "2026-10-19", "name": "Actually long", "distance_km": "13.4",
                 "moving_time": "1:16:00", "strava_activity_id": "a"},
                {"date": "2026-10-21", "name": "Easy instead", "distance_km": "6.2",
                 "moving_time": "0:35:00", "strava_activity_id": "b"},
            ],
            week_over=True,
        )
        self.assertEqual([row.role for row in swapped], ["matched", "matched"])
        self.assertEqual(swapped[0].run["name"], "Easy instead")
        self.assertEqual(swapped[0].label, "on plan")
        self.assertEqual(swapped[1].run["name"], "Actually long")
        self.assertEqual(swapped[1].label, "-1 km")

        finished = site.match_sessions(
            [
                {"date": "2026-10-05", "workout": "Easy run", "distance_km": "6"},
                {"date": "2026-10-07", "workout": "Easy run", "distance_km": "10"},
                {"date": "2026-10-10", "workout": "Long run", "distance_km": "16"},
            ],
            [
                {"date": "2026-10-06", "name": "Morning", "distance_km": "6.10",
                 "moving_time": "0:34:00", "strava_activity_id": "1"},
                {"date": "2026-10-11", "name": "Big loop", "distance_km": "15.20",
                 "moving_time": "1:26:00", "strava_activity_id": "2"},
            ],
            week_over=True,
        )
        self.assertEqual([row.label for row in finished], ["on plan", "Missed", "-1 km"])
        self.assertEqual(finished[2].run["name"], "Big loop")

        open_week = site.match_sessions(
            [
                {"date": "2026-10-19", "workout": "Easy run", "distance_km": "8"},
                {"date": "2026-10-21", "workout": "Easy run", "distance_km": "6"},
            ],
            [
                {"date": "2026-10-22", "name": "Evening", "distance_km": "9.40",
                 "moving_time": "0:52:00", "strava_activity_id": "3"},
                {"date": "2026-10-20", "name": "Steady", "distance_km": "6.30",
                 "moving_time": "0:36:00", "strava_activity_id": "4"},
                {"date": "2026-10-23", "name": "Shakeout", "distance_km": "4.00",
                 "moving_time": "0:22:00", "strava_activity_id": "5"},
            ],
            week_over=False,
        )
        self.assertEqual([row.label for row in open_week], ["+1 km", "on plan", "Additional"])
        self.assertEqual(open_week[0].run["name"], "Evening")
        self.assertEqual(open_week[2].run["name"], "Shakeout")
        self.assertEqual(site.match_sessions(
            [{"date": "2026-10-19", "workout": "Easy run", "distance_km": "6"}],
            [],
            week_over=False,
        )[0].label, "To do")

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
