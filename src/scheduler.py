"""Scheduling engine: expand reminders (one-off + RRULE) into messages, then dispatch the due ones."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from .config import Settings
from .db import UTC, iso, new_id, parse_iso
from .mailer import BaseMailer, is_valid_email
from .renderer import RenderError, render_email

log = logging.getLogger("emailauto.scheduler")
sent_log = logging.getLogger("emailauto.sent")
failed_log = logging.getLogger("emailauto.failed")

LOOKAHEAD = timedelta(seconds=60)


def get_tz(name: str, fallback: str = "UTC") -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(fallback)


def occurrences(start_utc: datetime, rrule: str | None, tz: ZoneInfo, last: datetime | None, lower: datetime):
    """Yield UTC occurrences. RRULE is evaluated in the contact's LOCAL time (so '9 AM daily' stays 9 AM across DST)."""
    start_local = start_utc.astimezone(tz)
    if not rrule:
        if last is None:
            yield start_utc
        return
    rule = rrulestr(rrule.replace("RRULE:", "").strip(), dtstart=start_local)
    if last and last >= lower:
        it = rule.xafter(last.astimezone(tz), inc=False)
    else:
        it = rule.xafter(max(lower, start_utc - timedelta(seconds=1)).astimezone(tz), inc=True)
    for occ in it:
        yield occ.astimezone(UTC)


def plan_next_fires(conn, now: datetime, settings: Settings) -> dict:
    """Turn reminders that are due (within the next minute) into 'scheduled' messages. Idempotent."""
    created = skipped = 0
    lower = now - timedelta(hours=settings.grace_hours)
    horizon = now + LOOKAHEAD
    rows = conn.execute(
        """SELECT r.*, c.timezone AS tz FROM reminders r JOIN contacts c ON c.id=r.contact_id WHERE r.active=1"""
    ).fetchall()
    for r in rows:
        tz = get_tz(r["tz"], settings.default_tz)
        last = parse_iso(r["last_occurrence_utc"]) if r["last_occurrence_utc"] else None
        newest, exhausted = last, True
        try:
            for occ in occurrences(parse_iso(r["start_at_utc"]), r["rrule"], tz, last, lower):
                if occ > horizon:
                    exhausted = False
                    break
                newest = occ
                if occ < lower:  # too old: never send stale reminders after downtime
                    skipped += 1
                    continue
                cur = conn.execute(
                    """INSERT OR IGNORE INTO messages(id,reminder_id,campaign_id,contact_id,dedupe_key,scheduled_at_utc,status,created_at)
                       VALUES(?,?,?,?,?,?,'scheduled',?)""",
                    (new_id(), r["id"], r["campaign_id"], r["contact_id"], f"{r['id']}:{iso(occ)}", iso(occ), iso(now)),
                )
                created += cur.rowcount
        except Exception as exc:  # bad RRULE etc. must not stop other reminders
            log.error("Reminder %s skipped, invalid schedule: %s", r["id"], exc)
            conn.execute("UPDATE reminders SET active=0 WHERE id=?", (r["id"],))
            continue
        done = exhausted  # one-off fired, or RRULE finished
        conn.execute("UPDATE reminders SET last_occurrence_utc=?, active=? WHERE id=?",
                     (iso(newest) if newest else None, 0 if done else 1, r["id"]))
    conn.commit()
    return {"created": created, "skipped_stale": skipped}


def _context(row, tz: ZoneInfo) -> dict:
    local = parse_iso(row["scheduled_at_utc"]).astimezone(tz)
    ctx = json.loads(row["vars_json"] or "{}")
    ctx.update(
        name=row["cname"], email=row["cemail"], title=row["rtitle"] or "Reminder",
        when=local.strftime("%a, %d %b %Y, %I:%M %p"), date=local.strftime("%d %b %Y"),
        time=local.strftime("%I:%M %p").lstrip("0"), timezone=str(tz),
    )
    return ctx


def _finish(conn, mid, status, now, error=None, **extra):
    conn.execute(
        "UPDATE messages SET status=?, error=?, sent_at_utc=COALESCE(?, sent_at_utc), next_attempt_at_utc=NULL, "
        "subject=COALESCE(?, subject), body_rendered_html=COALESCE(?, body_rendered_html), "
        "provider_msg_id=COALESCE(?, provider_msg_id) WHERE id=?",
        (status, error, extra.get("sent_at"), extra.get("subject"), extra.get("html"), extra.get("pid"), mid),
    )
    conn.commit()


def dispatch_due(conn, mailer: BaseMailer, now: datetime, settings: Settings) -> dict:
    """Send every due message with safety rails: unsubscribe, allow-list, rate limit, retries, idempotent claim."""
    result = {"sent": 0, "failed": 0, "skipped": 0, "retrying": 0}
    # recover messages stuck in 'sending' (worker crashed mid-send)
    conn.execute("UPDATE messages SET status='scheduled' WHERE status='sending' AND next_attempt_at_utc<=?",
                 (iso(now - timedelta(minutes=10)),))
    sent_last_min = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE sent_at_utc>? AND status IN ('sent','opened','clicked')",
        (iso(now - timedelta(seconds=60)),)).fetchone()[0]
    budget = max(0, settings.rate_per_min - sent_last_min)
    rows = conn.execute(
        """SELECT m.id, m.contact_id, m.scheduled_at_utc, m.attempts, t.subject AS tsubject, t.body_md,
                  c.name AS cname, c.email AS cemail, c.timezone AS ctz, c.unsubscribed,
                  camp.sender_name, camp.sender_email, r.title AS rtitle, r.vars_json
           FROM messages m
           JOIN campaigns camp ON camp.id=m.campaign_id JOIN templates t ON t.id=camp.template_id
           JOIN contacts c ON c.id=m.contact_id LEFT JOIN reminders r ON r.id=m.reminder_id
           WHERE m.status='scheduled' AND m.scheduled_at_utc<=? AND (m.next_attempt_at_utc IS NULL OR m.next_attempt_at_utc<=?)
           ORDER BY m.scheduled_at_utc LIMIT ?""", (iso(now), iso(now), budget)).fetchall()

    for row in rows:
        mid, to = row["id"], row["cemail"]
        claim = conn.execute("UPDATE messages SET status='sending', next_attempt_at_utc=? WHERE id=? AND status='scheduled'",
                             (iso(now), mid))
        conn.commit()
        if claim.rowcount == 0:  # another worker got it
            continue
        if row["unsubscribed"]:
            _finish(conn, mid, "skipped", now, "Contact is unsubscribed")
            failed_log.warning("SKIPPED | to=%s | reason=unsubscribed", to)
            result["skipped"] += 1
            continue
        domain = to.split("@")[-1].lower() if "@" in to else ""
        if settings.allowed_domains and domain not in settings.allowed_domains:
            _finish(conn, mid, "skipped", now, f"Domain '{domain}' not in ALLOWED_DOMAINS")
            failed_log.warning("SKIPPED | to=%s | reason=domain not allowed", to)
            result["skipped"] += 1
            continue
        if not is_valid_email(to):
            _finish(conn, mid, "failed", now, "Invalid email address")
            failed_log.error("FAILED | to=%s | reason=invalid email address", to)
            result["failed"] += 1
            continue
        tz = get_tz(row["ctz"], settings.default_tz)
        try:
            rendered = render_email(row["tsubject"], row["body_md"], _context(row, tz), message_id=mid,
                                    contact_id=row["contact_id"], base_url=settings.tracking_base_url, brand=settings.brand)
        except RenderError as exc:
            _finish(conn, mid, "failed", now, str(exc))
            failed_log.error("FAILED | to=%s | reason=%s", to, exc)
            result["failed"] += 1
            continue
        unsub = f"{settings.tracking_base_url}/u/{row['contact_id']}" if settings.tracking_base_url else ""
        res = mailer.send(from_name=row["sender_name"], from_email=row["sender_email"], to_email=to,
                          subject=rendered.subject, html=rendered.html, text=rendered.text, unsubscribe_url=unsub)
        if res.ok:
            _finish(conn, mid, "sent", now, None, sent_at=iso(now), subject=rendered.subject, html=rendered.html, pid=res.provider_msg_id)
            sent_log.info("SENT | to=%s | subject=%s | id=%s", to, rendered.subject, mid[:8])
            result["sent"] += 1
            continue
        attempts = row["attempts"] + 1
        if res.permanent or attempts >= settings.max_retries:
            conn.execute("UPDATE messages SET attempts=?, subject=?, body_rendered_html=? WHERE id=?",
                         (attempts, rendered.subject, rendered.html, mid))
            _finish(conn, mid, "failed", now, res.error)
            failed_log.error("FAILED | to=%s | attempts=%d | reason=%s", to, attempts, res.error)
            result["failed"] += 1
        else:  # transient: exponential backoff, try again later
            retry_at = now + timedelta(seconds=settings.retry_backoff_seconds * 2 ** (attempts - 1))
            conn.execute("UPDATE messages SET status='scheduled', attempts=?, error=?, next_attempt_at_utc=? WHERE id=?",
                         (attempts, res.error, iso(retry_at), mid))
            conn.commit()
            failed_log.warning("RETRY | to=%s | attempt=%d | next=%s | reason=%s", to, attempts, iso(retry_at), res.error)
            result["retrying"] += 1
    return result


def run_cycle(conn, mailer: BaseMailer, now: datetime, settings: Settings) -> dict:
    """One worker tick: plan -> dispatch."""
    plan = plan_next_fires(conn, now, settings)
    sent = dispatch_due(conn, mailer, now, settings)
    return {**plan, **sent}
