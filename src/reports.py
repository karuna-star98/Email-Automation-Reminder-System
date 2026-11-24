"""Statistics and CSV/JSON report generation (pandas)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

STATUSES = ["scheduled", "sending", "sent", "opened", "clicked", "failed", "skipped"]
DELIVERED = ("sent", "opened", "clicked")

REPORT_SQL = """
SELECT m.id AS message_id, c.name AS recipient_name, c.email AS recipient_email, camp.name AS campaign,
       COALESCE(m.subject, '(not rendered)') AS subject, m.status, m.attempts, m.scheduled_at_utc, m.sent_at_utc, m.error
FROM messages m JOIN contacts c ON c.id=m.contact_id JOIN campaigns camp ON camp.id=m.campaign_id
JOIN templates t ON t.id=camp.template_id ORDER BY m.scheduled_at_utc, c.name
"""


def stats(conn) -> dict:
    counts = {s: 0 for s in STATUSES}
    for r in conn.execute("SELECT status, COUNT(*) n FROM messages GROUP BY status"):
        counts[r["status"]] = r["n"]
    delivered = sum(counts[s] for s in DELIVERED)
    attempted = delivered + counts["failed"]
    one = lambda q: conn.execute(q).fetchone()[0]
    return {
        "by_status": counts,
        "total_messages": sum(counts.values()),
        "delivered": delivered,
        "success_rate": round(100 * delivered / attempted, 1) if attempted else 0.0,
        "open_rate": round(100 * (counts["opened"] + counts["clicked"]) / delivered, 1) if delivered else 0.0,
        "contacts": one("SELECT COUNT(*) FROM contacts"),
        "unsubscribed": one("SELECT COUNT(*) FROM contacts WHERE unsubscribed=1"),
        "active_reminders": one("SELECT COUNT(*) FROM reminders WHERE active=1"),
        "templates": one("SELECT COUNT(*) FROM templates"),
    }


def export_report(conn, out_dir: Path, now: datetime) -> tuple[Path, Path]:
    """Write outputs/email_report_<ts>.csv and outputs/summary_<ts>.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_sql_query(REPORT_SQL, conn)
    ts = now.strftime("%Y%m%d_%H%M%S")
    csv_path, json_path = out_dir / f"email_report_{ts}.csv", out_dir / f"summary_{ts}.json"
    df.to_csv(csv_path, index=False)
    summary = stats(conn)
    summary["by_campaign"] = (df.groupby(["campaign", "status"]).size().unstack(fill_value=0).to_dict("index")
                              if not df.empty else {})
    summary["generated_at_utc"] = now.isoformat()
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return csv_path, json_path
