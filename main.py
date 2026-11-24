#!/usr/bin/env python3
"""Email Automation & Reminder System - command line interface.

  python main.py demo              # one-command simulation (safe, no real emails)
  python main.py seed              # load sample CSVs + templates into the DB
  python main.py run               # run ONE scheduler cycle (dry-run by default)
  python main.py worker            # run continuously (Ctrl+C to stop)
  python main.py report | status   # CSV/JSON report, or live statistics
  python main.py serve             # start the FastAPI server (dashboard backend)
Add --live to really send through SMTP (needs .env credentials).
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import timedelta

from src.config import get_settings
from src.db import get_conn, iso, utcnow
from src.importer import parse_start, seed_all
from src.logging_setup import setup_logging
from src.mailer import get_mailer
from src.reports import export_report, stats
from src.scheduler import run_cycle

C = {"sent": "\033[92m", "failed": "\033[91m", "skipped": "\033[93m", "scheduled": "\033[94m", "end": "\033[0m"}


def table(rows, cols, widths):
    line = "  ".join(f"{c.upper():<{w}}" for c, w in zip(cols, widths))
    print("\n" + line + "\n" + "-" * len(line))
    for r in rows:
        cells = []
        for c, w in zip(cols, widths):
            v = str(r[c] if r[c] is not None else "")[:w]
            cells.append(f"{C.get(v, '')}{v:<{w}}{C['end'] if v in C else ''}")
        print("  ".join(cells))


def show_messages(conn, limit=50):
    rows = conn.execute(
        """SELECT c.name, c.email, camp.name AS campaign, m.status, m.attempts AS tries, COALESCE(m.error,'') AS note
           FROM messages m JOIN contacts c ON c.id=m.contact_id JOIN campaigns camp ON camp.id=m.campaign_id
           ORDER BY m.scheduled_at_utc, c.name LIMIT ?""", (limit,)).fetchall()
    table(rows, ["name", "email", "campaign", "status", "tries", "note"], [14, 30, 18, 9, 5, 38])


def print_stats(conn):
    s = stats(conn)
    print("\n=== SUMMARY ===")
    print(f"Contacts: {s['contacts']} ({s['unsubscribed']} unsubscribed) | Templates: {s['templates']} | Active reminders: {s['active_reminders']}")
    print("Messages: " + " | ".join(f"{k}={v}" for k, v in s["by_status"].items() if v) + f" | total={s['total_messages']}")
    print(f"Delivery success rate: {s['success_rate']}%")


def cmd_seed(a, s):
    if a.reset and s.db_path.exists():
        for ext in ("", "-wal", "-shm"):
            p = s.db_path.with_name(s.db_path.name + ext)
            p.exists() and p.unlink()
    conn = get_conn(s)
    r = seed_all(conn, s, utcnow())
    print(f"Seeded: {r['templates']} templates, {r['contacts']} contacts, {r['reminders']} reminders")
    for e in r["errors"]:
        print("  WARNING:", e)


def cmd_run(a, s):
    conn = get_conn(s)
    now = utcnow()
    if a.at:  # simulate a different 'current time', e.g. --at +1d
        now = parse_start(a.at, None, now)
    mailer = get_mailer(s, a.live)
    print(f"[{mailer.name}] cycle at {iso(now)}")
    print("Result:", run_cycle(conn, mailer, now, s))
    show_messages(conn)
    print_stats(conn)


def cmd_worker(a, s):
    conn = get_conn(s)
    mailer = get_mailer(s, a.live)
    log = logging.getLogger("emailauto")
    log.info("Worker started | provider=%s | tick=%ss | Ctrl+C to stop", mailer.name, s.tick_seconds)
    try:
        while True:
            res = run_cycle(conn, mailer, utcnow(), s)
            if res["sent"] or res["failed"] or res["created"] or res["retrying"]:
                log.info("tick %s", res)
            time.sleep(s.tick_seconds)
    except KeyboardInterrupt:
        log.info("Worker stopped")


def cmd_report(a, s):
    conn = get_conn(s)
    csv_path, json_path = export_report(conn, s.outputs_dir, utcnow())
    print(f"Report saved:\n  {csv_path}\n  {json_path}")


def cmd_demo(a, s):
    """Full simulation: reset DB, seed, then fast-forward time so recurring reminders fire several times."""
    cmd_seed(argparse.Namespace(reset=True), s)
    conn = get_conn(s)
    mailer = get_mailer(s, live=False)  # demo is ALWAYS dry-run
    base = utcnow()
    for label, delta in [("+10 min", timedelta(minutes=10)), ("+2 hours", timedelta(hours=2)),
                         ("+1 day 1h", timedelta(days=1, hours=1)), ("+2 days 1h", timedelta(days=2, hours=1)),
                         ("+8 days", timedelta(days=8))]:
        res = run_cycle(conn, mailer, base + delta, s)
        print(f"\n>>> Simulated clock {label:<10} -> planned={res['created']} sent={res['sent']} failed={res['failed']} skipped={res['skipped']}")
    show_messages(conn)
    print_stats(conn)
    cmd_report(a, s)
    print(f"\nOpen the generated emails in: {s.outbox_dir}")


def cmd_serve(a, s):
    import uvicorn
    uvicorn.run("api.app:app", host=a.host, port=a.port, reload=a.reload)


def main():
    p = argparse.ArgumentParser(description="Email Automation & Reminder System")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in [("seed", cmd_seed, "load sample data"), ("run", cmd_run, "run one cycle"),
                            ("worker", cmd_worker, "run continuously"), ("report", cmd_report, "export CSV report"),
                            ("status", lambda a, s: print_stats(get_conn(s)), "show statistics"),
                            ("demo", cmd_demo, "full dry-run simulation"), ("serve", cmd_serve, "start API server")]:
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        if name in ("run", "worker"):
            sp.add_argument("--live", action="store_true", help="really send via SMTP (default is dry-run)")
        if name == "run":
            sp.add_argument("--at", help="simulate the clock, e.g. +1d or '2026-12-01 09:00'")
        if name == "seed":
            sp.add_argument("--reset", action="store_true", help="delete the DB first")
        if name == "serve":
            sp.add_argument("--host", default="127.0.0.1")
            sp.add_argument("--port", type=int, default=8000)
            sp.add_argument("--reload", action="store_true")
    a = p.parse_args()
    s = get_settings()
    setup_logging(s, console=a.cmd in ("worker", "serve"))
    a.fn(a, s)


if __name__ == "__main__":
    main()
