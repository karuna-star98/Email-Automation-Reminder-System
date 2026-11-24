"""Load contacts, templates and reminders from CSV / Markdown files into the database."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from .config import Settings
from .db import UTC, iso, new_id
from .renderer import split_template
from .scheduler import get_tz

_REL = re.compile(r"^\+(\d+)\s*([smhdw])$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
REMINDER_CORE = {"contact_email", "title", "campaign", "start", "rrule"}


def parse_start(value: str, tz, now: datetime) -> datetime:
    """'now' | '+5m' | '+2h' | '+1d' | '2026-12-01 19:00' (local to the contact's timezone) -> UTC datetime."""
    v = (value or "").strip().lower()
    if v in ("", "now"):
        return now
    m = _REL.match(v)
    if m:
        return now + timedelta(**{_UNITS[m.group(2)]: int(m.group(1))})
    try:
        dt = datetime.fromisoformat(value.strip().replace(" ", "T"))
    except ValueError as exc:
        raise ValueError(f"Bad start '{value}'. Use 'now', '+5m', '+2h', '+1d' or 'YYYY-MM-DD HH:MM'") from exc
    return (dt if dt.tzinfo else dt.replace(tzinfo=tz)).astimezone(UTC)


def _read(path: Path) -> list[dict]:
    return pd.read_csv(path, dtype=str, keep_default_na=False).to_dict("records")


def import_templates(conn, folder: Path, now: datetime) -> int:
    n = 0
    for f in sorted(folder.glob("*.md")):
        subject, body = split_template(f.read_text(encoding="utf-8"))
        conn.execute(
            """INSERT INTO templates(id,name,subject,body_md,created_at) VALUES(?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET subject=excluded.subject, body_md=excluded.body_md""",
            (new_id(), f.stem, subject, body, iso(now)))
        n += 1
    conn.commit()
    return n


def import_contacts(conn, path: Path, now: datetime, default_tz: str) -> int:
    n = 0
    for r in _read(path):
        email = r.get("email", "").strip()
        if not email:
            continue
        conn.execute(
            """INSERT INTO contacts(id,name,email,timezone,unsubscribed,created_at) VALUES(?,?,?,?,?,?)
               ON CONFLICT(email) DO UPDATE SET name=excluded.name, timezone=excluded.timezone, unsubscribed=excluded.unsubscribed""",
            (new_id(), r.get("name", "").strip() or email, email, r.get("timezone", "").strip() or default_tz,
             1 if r.get("unsubscribed", "").strip().lower() in ("1", "true", "yes") else 0, iso(now)))
        n += 1
    conn.commit()
    return n


def ensure_campaign(conn, name: str, settings: Settings, now: datetime):
    """A campaign named like a template is auto-created (template + default sender)."""
    row = conn.execute("SELECT id FROM campaigns WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    t = conn.execute("SELECT id FROM templates WHERE name=?", (name,)).fetchone()
    if not t:
        return None
    cid = new_id()
    conn.execute("INSERT INTO campaigns(id,name,template_id,sender_name,sender_email,created_at) VALUES(?,?,?,?,?,?)",
                 (cid, name, t["id"], settings.sender_name, settings.sender_email, iso(now)))
    return cid


def import_reminders(conn, path: Path, now: datetime, settings: Settings) -> tuple[int, list[str]]:
    n, errors = 0, []
    for i, r in enumerate(_read(path), start=2):  # row 1 is the header
        email = r.get("contact_email", "").strip()
        c = conn.execute("SELECT id, timezone FROM contacts WHERE email=?", (email,)).fetchone()
        if not c:
            errors.append(f"row {i}: unknown contact '{email}'")
            continue
        camp = ensure_campaign(conn, r.get("campaign", "").strip(), settings, now)
        if not camp:
            errors.append(f"row {i}: unknown campaign/template '{r.get('campaign')}'")
            continue
        try:
            start = parse_start(r.get("start", ""), get_tz(c["timezone"], settings.default_tz), now)
        except ValueError as exc:
            errors.append(f"row {i}: {exc}")
            continue
        extra = {k: v.strip() for k, v in r.items() if k not in REMINDER_CORE and v.strip()}
        conn.execute(
            """INSERT INTO reminders(id,title,contact_id,campaign_id,start_at_utc,rrule,vars_json,active,created_at)
               VALUES(?,?,?,?,?,?,?,1,?)""",
            (new_id(), r.get("title", "").strip() or "Reminder", c["id"], camp, iso(start),
             r.get("rrule", "").strip() or None, json.dumps(extra, ensure_ascii=False), iso(now)))
        n += 1
    conn.commit()
    return n, errors


def seed_all(conn, settings: Settings, now: datetime) -> dict:
    """Import the sample files shipped in data/ and templates/."""
    t = import_templates(conn, settings.templates_dir, now)
    c = import_contacts(conn, settings.data_dir / "contacts.csv", now, settings.default_tz)
    r, errors = import_reminders(conn, settings.data_dir / "reminders.csv", now, settings)
    return {"templates": t, "contacts": c, "reminders": r, "errors": errors}
