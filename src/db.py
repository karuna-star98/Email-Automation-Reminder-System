"""SQLite storage layer. All timestamps are stored as UTC ISO-8601 strings (sortable as text)."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from .config import Settings, get_settings

UTC = timezone.utc
FMT = "%Y-%m-%dT%H:%M:%S+00:00"

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  unsubscribed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS templates(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  subject TEXT NOT NULL,
  body_md TEXT NOT NULL,                 -- markdown with {{ variables }}
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  template_id TEXT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
  sender_name TEXT NOT NULL,
  sender_email TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders(
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  start_at_utc TEXT NOT NULL,            -- first fire
  rrule TEXT,                            -- optional RFC 5545 RRULE, e.g. FREQ=WEEKLY;BYDAY=MO,WE
  vars_json TEXT NOT NULL DEFAULT '{}',  -- extra template variables (amount, link, ...)
  active INTEGER NOT NULL DEFAULT 1,
  last_occurrence_utc TEXT,              -- last occurrence already turned into a message
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY,
  reminder_id TEXT REFERENCES reminders(id) ON DELETE SET NULL,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  dedupe_key TEXT NOT NULL UNIQUE,       -- idempotency: one message per reminder occurrence
  scheduled_at_utc TEXT NOT NULL,
  sent_at_utc TEXT,
  provider_msg_id TEXT,
  status TEXT NOT NULL,                  -- scheduled|sending|sent|failed|skipped|opened|clicked
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at_utc TEXT,
  subject TEXT,
  body_rendered_html TEXT,
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_sched ON messages(scheduled_at_utc, status);
CREATE INDEX IF NOT EXISTS idx_reminders_active ON reminders(active);
"""


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime(FMT)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


def get_conn(settings: Settings | None = None, init: bool = True) -> sqlite3.Connection:
    s = settings or get_settings()
    s.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(s.db_path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    if init:
        conn.executescript(SCHEMA)
    return conn
