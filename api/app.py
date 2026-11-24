"""FastAPI backend: CRUD + actions + tracking + embedded APScheduler worker.
Run:  python main.py serve      (docs at http://127.0.0.1:8000/docs)
"""
import csv
import io
import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, EmailStr, Field

from src.config import get_settings
from src.db import get_conn, iso, new_id, utcnow
from src.importer import ensure_campaign, import_contacts, import_templates, parse_start, seed_all
from src.logging_setup import setup_logging
from src.mailer import get_mailer
from src.renderer import RenderError, render_email, split_template
from src.reports import REPORT_SQL, stats
from src.scheduler import get_tz, run_cycle

settings = get_settings()
setup_logging(settings)
log = logging.getLogger("emailauto.api")
PIXEL = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63fcffff3f0300050001a5f645400000000049454e44ae426082")


def tick():
    """Background job: plan + dispatch. Uses its own DB connection (thread-safe)."""
    conn = get_conn(settings)
    try:
        res = run_cycle(conn, get_mailer(settings, live=not settings.dry_run), utcnow(), settings)
        if any(res.values()):
            log.info("tick %s", res)
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_conn(settings).close()  # create tables
    sched = None
    if settings.embedded_worker:
        from apscheduler.schedulers.background import BackgroundScheduler
        sched = BackgroundScheduler(timezone="UTC")
        sched.add_job(tick, "interval", seconds=settings.tick_seconds, max_instances=1, coalesce=True, id="tick")
        sched.start()
        log.info("Embedded scheduler running every %ss (dry_run=%s)", settings.tick_seconds, settings.dry_run)
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Email Automation & Reminder System", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])


def db():
    conn = get_conn(settings)
    try:
        yield conn
    finally:
        conn.close()


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------- models
class ContactIn(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr
    timezone: str = "Asia/Kolkata"


class TemplateIn(BaseModel):
    name: str
    subject: str
    body_md: str


class PreviewIn(BaseModel):
    subject: str
    body_md: str
    context: dict = {}


class CampaignIn(BaseModel):
    name: str
    template_id: str
    sender_name: str
    sender_email: EmailStr


class ReminderIn(BaseModel):
    title: str
    contact_id: str
    campaign_id: str
    start: str = Field(description="'now', '+5m', or local time 'YYYY-MM-DDTHH:MM' in the contact's timezone")
    rrule: str | None = None
    vars: dict = {}


class TestIn(BaseModel):
    to_email: EmailStr
    campaign_id: str
    name: str = "Test User"


class CsvIn(BaseModel):
    csv: str


api = APIRouter(prefix="/api")


@api.get("/health")
def health():
    return {"status": "ok", "mode": "dry-run" if settings.dry_run else "live", "worker": settings.embedded_worker}


@api.get("/stats")
def get_stats(conn=Depends(db)):
    return stats(conn)


# ---------------------------------------------------------------- contacts
@api.get("/contacts")
def list_contacts(conn=Depends(db)):
    return rows(conn, "SELECT * FROM contacts ORDER BY created_at DESC, name")


@api.post("/contacts", status_code=201)
def create_contact(c: ContactIn, conn=Depends(db)):
    cid = new_id()
    try:
        conn.execute("INSERT INTO contacts(id,name,email,timezone,created_at) VALUES(?,?,?,?,?)",
                     (cid, c.name, c.email, c.timezone, iso(utcnow())))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A contact with this email already exists")
    return {"id": cid}


@api.patch("/contacts/{cid}/unsubscribe")
def set_unsubscribed(cid: str, value: bool = True, conn=Depends(db)):
    conn.execute("UPDATE contacts SET unsubscribed=? WHERE id=?", (int(value), cid))
    conn.commit()
    return {"id": cid, "unsubscribed": value}


@api.delete("/contacts/{cid}")
def delete_contact(cid: str, conn=Depends(db)):
    conn.execute("DELETE FROM contacts WHERE id=?", (cid,))
    conn.commit()
    return {"deleted": cid}


@api.post("/import/contacts")
def import_contacts_csv(body: CsvIn, conn=Depends(db)):
    """Body: {"csv": "name,email,timezone\\nAsha,asha@example.com,Asia/Kolkata"}"""
    n = 0
    for r in csv.DictReader(io.StringIO(body.csv)):
        if not (r.get("email") or "").strip():
            continue
        conn.execute("""INSERT INTO contacts(id,name,email,timezone,created_at) VALUES(?,?,?,?,?)
                        ON CONFLICT(email) DO UPDATE SET name=excluded.name, timezone=excluded.timezone""",
                     (new_id(), r.get("name") or r["email"], r["email"].strip(), r.get("timezone") or settings.default_tz, iso(utcnow())))
        n += 1
    conn.commit()
    return {"imported": n}


# ---------------------------------------------------------------- templates & campaigns
@api.get("/templates")
def list_templates(conn=Depends(db)):
    return rows(conn, "SELECT * FROM templates ORDER BY name")


@api.post("/templates", status_code=201)
def create_template(t: TemplateIn, conn=Depends(db)):
    tid = new_id()
    try:
        conn.execute("INSERT INTO templates(id,name,subject,body_md,created_at) VALUES(?,?,?,?,?)",
                     (tid, t.name, t.subject, t.body_md, iso(utcnow())))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Template name already exists")
    return {"id": tid}


@api.post("/templates/preview")
def preview_template(p: PreviewIn):
    ctx = {"name": "Asha", "title": "Sample", "when": "Mon, 01 Dec 2026, 07:00 PM", "date": "01 Dec 2026",
           "time": "7:00 PM", "timezone": "Asia/Kolkata", **p.context}
    try:
        r = render_email(p.subject, p.body_md, ctx, brand=settings.brand)
    except RenderError as exc:
        raise HTTPException(422, str(exc))
    return {"subject": r.subject, "html": r.html}


@api.get("/campaigns")
def list_campaigns(conn=Depends(db)):
    return rows(conn, """SELECT c.*, t.name AS template_name FROM campaigns c JOIN templates t ON t.id=c.template_id ORDER BY c.name""")


@api.post("/campaigns", status_code=201)
def create_campaign(c: CampaignIn, conn=Depends(db)):
    cid = new_id()
    try:
        conn.execute("INSERT INTO campaigns(id,name,template_id,sender_name,sender_email,created_at) VALUES(?,?,?,?,?,?)",
                     (cid, c.name, c.template_id, c.sender_name, c.sender_email, iso(utcnow())))
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, f"Could not create campaign: {exc}")
    return {"id": cid}


# ---------------------------------------------------------------- reminders
@api.get("/reminders")
def list_reminders(conn=Depends(db)):
    return rows(conn, """SELECT r.id, r.title, r.start_at_utc, r.rrule, r.active, r.last_occurrence_utc, r.vars_json,
                         c.name AS contact_name, c.email AS contact_email, c.timezone, camp.name AS campaign
                         FROM reminders r JOIN contacts c ON c.id=r.contact_id JOIN campaigns camp ON camp.id=r.campaign_id
                         ORDER BY r.active DESC, r.start_at_utc DESC""")


@api.post("/reminders", status_code=201)
def create_reminder(r: ReminderIn, conn=Depends(db)):
    c = conn.execute("SELECT timezone FROM contacts WHERE id=?", (r.contact_id,)).fetchone()
    if not c:
        raise HTTPException(404, "Unknown contact")
    try:
        start = parse_start(r.start, get_tz(c["timezone"], settings.default_tz), utcnow())
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    rid = new_id()
    conn.execute("""INSERT INTO reminders(id,title,contact_id,campaign_id,start_at_utc,rrule,vars_json,active,created_at)
                    VALUES(?,?,?,?,?,?,?,1,?)""",
                 (rid, r.title, r.contact_id, r.campaign_id, iso(start), r.rrule or None, json.dumps(r.vars), iso(utcnow())))
    conn.commit()
    return {"id": rid, "start_at_utc": iso(start)}


@api.patch("/reminders/{rid}")
def toggle_reminder(rid: str, active: bool, conn=Depends(db)):
    conn.execute("UPDATE reminders SET active=? WHERE id=?", (int(active), rid))
    conn.commit()
    return {"id": rid, "active": active}


@api.delete("/reminders/{rid}")
def delete_reminder(rid: str, conn=Depends(db)):
    conn.execute("DELETE FROM reminders WHERE id=?", (rid,))
    conn.commit()
    return {"deleted": rid}


# ---------------------------------------------------------------- messages
@api.get("/messages")
def list_messages(status: str | None = None, limit: int = Query(100, le=500), conn=Depends(db)):
    sql = """SELECT m.id, m.status, m.attempts, m.scheduled_at_utc, m.sent_at_utc, m.error, COALESCE(m.subject, '(not rendered)') AS subject,
             c.name AS contact_name, c.email AS contact_email, camp.name AS campaign
             FROM messages m JOIN contacts c ON c.id=m.contact_id JOIN campaigns camp ON camp.id=m.campaign_id
             JOIN templates t ON t.id=camp.template_id"""
    params = []
    if status:
        sql += " WHERE m.status=?"
        params.append(status)
    return rows(conn, sql + " ORDER BY m.scheduled_at_utc DESC LIMIT ?", (*params, limit))


@api.get("/messages/{mid}/html", response_class=HTMLResponse)
def message_html(mid: str, conn=Depends(db)):
    r = conn.execute("SELECT body_rendered_html FROM messages WHERE id=?", (mid,)).fetchone()
    if not r or not r["body_rendered_html"]:
        raise HTTPException(404, "No rendered body yet")
    return r["body_rendered_html"]


@api.post("/messages/{mid}/retry")
def retry_message(mid: str, conn=Depends(db)):
    cur = conn.execute("UPDATE messages SET status='scheduled', attempts=0, error=NULL, next_attempt_at_utc=NULL "
                       "WHERE id=? AND status IN ('failed','skipped')", (mid,))
    conn.commit()
    if not cur.rowcount:
        raise HTTPException(409, "Only failed/skipped messages can be retried")
    return {"id": mid, "status": "scheduled"}


# ---------------------------------------------------------------- actions
@api.post("/run")
def run_now(conn=Depends(db)):
    """Run one scheduler cycle immediately (what the worker does every tick)."""
    return run_cycle(conn, get_mailer(settings, live=not settings.dry_run), utcnow(), settings)


@api.post("/send-test")
def send_test(t: TestIn, conn=Depends(db)):
    camp = conn.execute("SELECT id FROM campaigns WHERE id=?", (t.campaign_id,)).fetchone()
    if not camp:
        raise HTTPException(404, "Unknown campaign")
    now = utcnow()
    c = conn.execute("SELECT id FROM contacts WHERE email=?", (t.to_email,)).fetchone()
    if c:
        cid = c["id"]
    else:
        cid = new_id()
        conn.execute("INSERT INTO contacts(id,name,email,timezone,created_at) VALUES(?,?,?,?,?)",
                     (cid, t.name, t.to_email, settings.default_tz, iso(now)))
    mid = new_id()
    conn.execute("INSERT INTO messages(id,campaign_id,contact_id,dedupe_key,scheduled_at_utc,status,created_at) VALUES(?,?,?,?,?,'scheduled',?)",
                 (mid, t.campaign_id, cid, f"test:{mid}", iso(now), iso(now)))
    conn.commit()
    res = run_cycle(conn, get_mailer(settings, live=not settings.dry_run), now + timedelta(seconds=1), settings)
    st = conn.execute("SELECT status, error FROM messages WHERE id=?", (mid,)).fetchone()
    return {"message_id": mid, "status": st["status"], "error": st["error"], "cycle": res}


@api.post("/demo/seed")
def demo_seed(conn=Depends(db)):
    return seed_all(conn, settings, utcnow())


@api.get("/report.csv", response_class=PlainTextResponse)
def report_csv(conn=Depends(db)):
    cur = conn.execute(REPORT_SQL)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([d[0] for d in cur.description])
    w.writerows(cur.fetchall())
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=email_report.csv"})


app.include_router(api)


# ---------------------------------------------------------------- tracking (public endpoints)
@app.get("/t/o/{mid}.png")
def opened(mid: str, conn=Depends(db)):
    conn.execute("UPDATE messages SET status='opened' WHERE id=? AND status='sent'", (mid,))
    conn.commit()
    return Response(PIXEL, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/t/c/{mid}")
def clicked(mid: str, url: str, conn=Depends(db)):
    r = conn.execute("SELECT body_rendered_html FROM messages WHERE id=?", (mid,)).fetchone()
    # open-redirect protection: only redirect to a URL that really is a link inside this message
    if not r or not url.startswith(("http://", "https://")) or quote(url, safe="") not in (r["body_rendered_html"] or ""):
        raise HTTPException(400, "Unknown link")
    conn.execute("UPDATE messages SET status='clicked' WHERE id=? AND status IN ('sent','opened')", (mid,))
    conn.commit()
    return Response(status_code=302, headers={"Location": url})


@app.get("/u/{contact_id}", response_class=HTMLResponse)
def unsubscribe(contact_id: str, conn=Depends(db)):
    conn.execute("UPDATE contacts SET unsubscribed=1 WHERE id=?", (contact_id,))
    conn.commit()
    return "<h3 style='font-family:sans-serif'>You have been unsubscribed. No more reminders will be sent.</h3>"
