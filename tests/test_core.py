"""Run with:  python -m pytest -q   (or: python -m unittest discover tests)"""
import sys, tempfile, unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings
from src.db import get_conn, iso, new_id
from src.importer import import_reminders, parse_start, seed_all
from src.mailer import BaseMailer, SendResult, is_valid_email
from src.renderer import RenderError, render_email
from src.reports import export_report, stats
from src.scheduler import get_tz, occurrences, plan_next_fires, run_cycle, dispatch_due

UTC = timezone.utc
NOW = datetime(2026, 12, 1, 3, 30, tzinfo=UTC)


class FakeMailer(BaseMailer):
    def __init__(self, results=None):
        self.results, self.sent = list(results or []), []

    def send(self, **kw):
        self.sent.append(kw)
        return self.results.pop(0) if self.results else SendResult(True, "<id@test>")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.s = replace(get_settings(), db_path=t / "t.db", outputs_dir=t / "out", outbox_dir=t / "out" / "box",
                         max_retries=3, retry_backoff_seconds=60, rate_per_min=60, allowed_domains=())
        self.conn = get_conn(self.s)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.conn.close)

    def add(self, email="a@example.com", unsub=0, body="Hi {{ name }}", subject="Hello {{ name }}"):
        cid, tid, camp = new_id(), new_id(), new_id()
        self.conn.execute("INSERT INTO contacts VALUES(?,?,?,?,?,?)", (cid, "Asha", email, "Asia/Kolkata", unsub, iso(NOW)))
        self.conn.execute("INSERT INTO templates VALUES(?,?,?,?,?)", (tid, new_id(), subject, body, iso(NOW)))
        self.conn.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,?)", (camp, new_id(), tid, "Bot", "bot@example.com", iso(NOW)))
        self.conn.commit()
        return cid, camp

    def remind(self, cid, camp, start, rrule=None):
        self.conn.execute("INSERT INTO reminders(id,title,contact_id,campaign_id,start_at_utc,rrule,created_at) VALUES(?,?,?,?,?,?,?)",
                          (new_id(), "T", cid, camp, iso(start), rrule, iso(NOW)))
        self.conn.commit()


class TestRenderer(unittest.TestCase):
    def test_renders_html_and_text(self):
        r = render_email("Hi {{ name }}", "Hello **{{ name }}**", {"name": "Asha"})
        self.assertEqual(r.subject, "Hi Asha")
        self.assertIn("<strong>Asha</strong>", r.html)
        self.assertIn("Hello Asha", r.text)
        self.assertNotIn("**", r.text)

    def test_missing_variable_raises(self):
        with self.assertRaises(RenderError):
            render_email("Hi", "Pay {{ amount }}", {})

    def test_html_is_escaped(self):
        r = render_email("x", "{{ name }}", {"name": "<script>alert(1)</script>"})
        self.assertNotIn("<script>", r.html)

    def test_tracking_links_and_pixel(self):
        r = render_email("x", "[go](https://example.com/a)", {}, message_id="m1", contact_id="c1", base_url="http://h")
        self.assertIn("http://h/t/c/m1?url=https%3A%2F%2Fexample.com%2Fa", r.html)
        self.assertIn("/t/o/m1.png", r.html)
        self.assertIn("/u/c1", r.html)


class TestSchedule(Base):
    def test_rrule_runs_in_local_time(self):
        tz = get_tz("Asia/Kolkata")
        start = datetime(2026, 12, 1, 3, 30, tzinfo=UTC)  # 09:00 IST
        got = []
        for o in occurrences(start, "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0;COUNT=3", tz, None, start - timedelta(days=1)):
            got.append(o)
        self.assertEqual([o.astimezone(tz).strftime("%H:%M") for o in got], ["09:00"] * 3)
        self.assertEqual(got[1] - got[0], timedelta(days=1))

    def test_one_off_fires_once_and_deactivates(self):
        cid, camp = self.add()
        self.remind(cid, camp, NOW)
        self.assertEqual(plan_next_fires(self.conn, NOW, self.s)["created"], 1)
        self.assertEqual(plan_next_fires(self.conn, NOW + timedelta(minutes=5), self.s)["created"], 0)  # idempotent
        self.assertEqual(self.conn.execute("SELECT active FROM reminders").fetchone()[0], 0)

    def test_recurring_creates_each_occurrence_once(self):
        cid, camp = self.add()
        self.remind(cid, camp, NOW, "FREQ=DAILY;COUNT=3")
        total = sum(plan_next_fires(self.conn, NOW + timedelta(days=d), self.s)["created"] for d in (0, 0, 1, 2, 3))
        self.assertEqual(total, 3)

    def test_stale_occurrences_are_skipped_after_downtime(self):
        cid, camp = self.add()
        self.remind(cid, camp, NOW)
        res = plan_next_fires(self.conn, NOW + timedelta(days=5), self.s)
        self.assertEqual((res["created"], res["skipped_stale"]), (0, 1))


class TestDispatch(Base):
    def go(self, mailer, now=NOW + timedelta(minutes=1)):
        return dispatch_due(self.conn, mailer, now, self.s)

    def status(self):
        return self.conn.execute("SELECT status, error, attempts FROM messages").fetchone()

    def test_success(self):
        cid, camp = self.add()
        self.remind(cid, camp, NOW)
        m = FakeMailer()
        run_cycle(self.conn, m, NOW + timedelta(minutes=1), self.s)
        self.assertEqual(self.status()["status"], "sent")
        self.assertEqual(m.sent[0]["subject"], "Hello Asha")

    def test_unsubscribed_is_skipped_not_sent(self):
        cid, camp = self.add(unsub=1)
        self.remind(cid, camp, NOW)
        m = FakeMailer()
        run_cycle(self.conn, m, NOW + timedelta(minutes=1), self.s)
        self.assertEqual((self.status()["status"], len(m.sent)), ("skipped", 0))

    def test_invalid_email_fails_without_sending(self):
        cid, camp = self.add(email="not-an-email")
        self.remind(cid, camp, NOW)
        m = FakeMailer()
        run_cycle(self.conn, m, NOW + timedelta(minutes=1), self.s)
        self.assertEqual((self.status()["status"], len(m.sent)), ("failed", 0))

    def test_missing_template_variable_fails(self):
        cid, camp = self.add(body="Pay {{ amount }}")
        self.remind(cid, camp, NOW)
        run_cycle(self.conn, FakeMailer(), NOW + timedelta(minutes=1), self.s)
        self.assertIn("amount", self.status()["error"])

    def test_transient_error_retries_with_backoff_then_fails(self):
        cid, camp = self.add()
        self.remind(cid, camp, NOW)
        m = FakeMailer([SendResult(False, error="timeout")] * 3)
        t = NOW + timedelta(minutes=1)
        run_cycle(self.conn, m, t, self.s)
        self.assertEqual(self.status()["status"], "scheduled")           # attempt 1 -> retry
        self.go(m, t + timedelta(seconds=30))                             # too early: backoff not elapsed
        self.assertEqual(len(m.sent), 1)
        self.go(m, t + timedelta(seconds=61))                             # attempt 2
        self.go(m, t + timedelta(seconds=61 + 121))                       # attempt 3 -> give up
        st = self.status()
        self.assertEqual((st["status"], st["attempts"], len(m.sent)), ("failed", 3, 3))

    def test_permanent_error_does_not_retry(self):
        cid, camp = self.add()
        self.remind(cid, camp, NOW)
        m = FakeMailer([SendResult(False, error="550 no such user", permanent=True)])
        run_cycle(self.conn, m, NOW + timedelta(minutes=1), self.s)
        self.assertEqual((self.status()["status"], len(m.sent)), ("failed", 1))

    def test_rate_limit(self):
        for i in range(5):
            cid, camp = self.add(email=f"u{i}@example.com")
            self.remind(cid, camp, NOW)
        s = replace(self.s, rate_per_min=2)
        t = NOW + timedelta(minutes=1)
        plan_next_fires(self.conn, t, s)
        self.assertEqual(dispatch_due(self.conn, FakeMailer(), t, s)["sent"], 2)

    def test_allowed_domains(self):
        cid, camp = self.add(email="a@blocked.com")
        self.remind(cid, camp, NOW)
        s = replace(self.s, allowed_domains=("example.com",))
        run_cycle(self.conn, FakeMailer(), NOW + timedelta(minutes=1), s)
        self.assertEqual(self.status()["status"], "skipped")


class TestImportAndReport(Base):
    def test_parse_start(self):
        tz = get_tz("Asia/Kolkata")
        self.assertEqual(parse_start("+5m", tz, NOW), NOW + timedelta(minutes=5))
        self.assertEqual(parse_start("2026-12-01 09:00", tz, NOW), datetime(2026, 12, 1, 3, 30, tzinfo=UTC))
        with self.assertRaises(ValueError):
            parse_start("tomorrow-ish", tz, NOW)

    def test_seed_and_report(self):
        s = replace(self.s, data_dir=get_settings().data_dir, templates_dir=get_settings().templates_dir)
        r = seed_all(self.conn, s, NOW)
        self.assertEqual((r["contacts"], r["templates"], r["errors"]), (10, 5, []))
        run_cycle(self.conn, FakeMailer(), NOW + timedelta(minutes=10), s)
        st = stats(self.conn)
        self.assertEqual((st["by_status"]["failed"], st["by_status"]["skipped"]), (2, 1))
        csv_path, json_path = export_report(self.conn, s.outputs_dir, NOW)
        self.assertTrue(csv_path.exists() and json_path.exists())
        self.assertIn("recipient_email", csv_path.read_text().splitlines()[0])

    def test_email_validation(self):
        self.assertTrue(is_valid_email("a.b+c@mail.example.co"))
        self.assertFalse(is_valid_email("invalid-email.example.com"))


if __name__ == "__main__":
    unittest.main()
