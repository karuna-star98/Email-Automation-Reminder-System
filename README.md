# ✉️ Email Automation & Reminder System

> A production-style Python system that **schedules and sends personalised emails (one-off or recurring), retries failures, tracks delivery status and generates reports** — with a FastAPI backend and a Next.js dashboard. Safe **dry-run mode** by default, so nothing is sent until you say `--live`.

![Python](https://img.shields.io/badge/Python-3.11+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-API-009688) ![Next.js](https://img.shields.io/badge/Next.js-Dashboard-black) ![Tests](https://img.shields.io/badge/tests-19%20passing-brightgreen)

## Problem statement
Teams waste hours sending the same follow-ups, class/meeting reminders and payment notices by hand — and still miss some. This project automates the whole loop: **contacts → template → schedule → send → track → report.**

## Industry relevance
Used in the same way by training institutes (class reminders), finance/ops (invoice dues), HR (interview follow-ups), sales (drip/follow-up) and support (ticket nudges). Demonstrates job scheduling, templating, queues, SMTP integration, idempotency, retries and observability — core backend skills.

## ✨ Features
| Area | What it does |
|---|---|
| Scheduling | One-off + recurring reminders using **RFC 5545 RRULE** (`FREQ=WEEKLY;BYDAY=MO,WE`), evaluated in each **contact's local timezone** (DST-safe); stored in UTC |
| Templating | Jinja2 variables + Markdown → responsive branded **HTML + plain-text** email; missing variables are caught, never sent blank |
| Safe sending | **Dry-run default** (saves `.eml`/`.html` to `outputs/outbox/`), unsubscribe handling, optional domain allow-list, per-minute **rate limit** |
| Reliability | **Idempotent** (unique dedupe key per occurrence), crash recovery, **retry with exponential backoff** for transient errors, no retry for permanent ones |
| Tracking | Status per message (`scheduled → sent → opened → clicked` / `failed` / `skipped`), open pixel, click redirect (open-redirect protected), one-click unsubscribe |
| Reporting | Timestamped **CSV report + JSON summary**, separate `sent_emails.log` / `failed_emails.log` |
| API | FastAPI CRUD + actions, Swagger docs at `/docs`, embedded APScheduler worker |
| Dashboard | Next.js UI: live stats, status bar, schedule reminders, add contacts, view emails, retry failures, download report |
| Quality | 19 automated tests; secrets only via env vars (`.env.example` provided) |

## 🧱 Architecture
```
 contacts.csv ─┐                          ┌─► DryRunMailer → outputs/outbox/*.eml|html
 reminders.csv ┼─► Importer ─► SQLite ─► Scheduler ─► Renderer ─► Mailer ─┤
 templates/*.md┘      ▲         (UTC)     (RRULE→messages)  (Jinja2+MD)   └─► SMTPMailer → real inbox
                      │            │              │                              │
   Next.js dashboard ─┴─► FastAPI ─┘        status + retries ◄───────────────────┘
                                                  │
                                  logs/*.log  +  outputs/email_report_*.csv|json
```
Flow: **contact list → message template → scheduled reminder → email sending → status tracking → report.**

## 📁 Folder structure
```
Email-Automation-Reminder-System/
├── main.py              # CLI: demo | seed | run | worker | report | status | serve
├── src/                 # config, db, importer, renderer, mailer, scheduler, reports, logging
├── api/app.py           # FastAPI backend (+ APScheduler)
├── apps/web/            # Next.js dashboard
├── data/                # contacts.csv, reminders.csv (dummy data)
├── templates/           # Markdown email templates
├── tests/               # 19 tests
├── outputs/             # generated reports (+ outbox in dry-run)
├── logs/                # app.log, sent_emails.log, failed_emails.log
├── docs/                # PROJECT_GUIDE.md, sample_output/
├── images/              # your screenshots
├── .env.example  .gitignore  requirements.txt  README.md
```

## 🚀 Setup
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows        |   source .venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env   (needed only for --live)
```

## ▶️ How to run
```bash
python main.py demo                 # ⭐ one-command safe simulation (fast-forwards the clock)
python -m pytest -q                 # run tests

python main.py seed --reset         # load sample CSV data
python main.py run                  # one scheduler cycle, DRY-RUN
python main.py run --at +1d         # pretend it is tomorrow
python main.py worker               # continuous worker (every TICK_SECONDS)
python main.py report               # CSV + JSON report in outputs/

python main.py serve                # API → http://127.0.0.1:8000/docs
cd apps/web && npm install && npm run dev   # dashboard → http://localhost:3000
```
**Real emails (Gmail):** enable 2-step verification → create an *App Password* → put it in `.env` as `SMTP_PASS` → `python main.py run --live`. (API server: set `DRY_RUN=false`.) Test with your own address first.

## 📊 Sample output (real run of `python main.py demo`)
```
>>> Simulated clock +10 min    -> planned=9 sent=6 failed=2 skipped=1
>>> Simulated clock +2 hours   -> planned=1 sent=1 failed=0 skipped=0
>>> Simulated clock +1 day 1h  -> planned=2 sent=2 failed=0 skipped=0
>>> Simulated clock +2 days 1h -> planned=1 sent=1 failed=0 skipped=0
>>> Simulated clock +8 days    -> planned=1 sent=1 failed=0 skipped=0

=== SUMMARY ===
Contacts: 10 (1 unsubscribed) | Templates: 5 | Active reminders: 1
Messages: sent=11 | failed=2 | skipped=1 | total=14
Delivery success rate: 84.6%
```
The 2 failures and 1 skip are **intentional test cases**: invalid email address, a template with a missing variable (`amount`), and an unsubscribed contact. Full files: [`docs/sample_output/`](docs/sample_output).

## 🖼️ Screenshots
Add yours to `images/` (checklist in [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md#13-screenshots--outputs)):
`![Dry-run](images/dry_run.png)` · `![Dashboard](images/dashboard.png)` · `![Report](images/report.png)`

## 🔌 API overview
`GET /api/stats` · `GET/POST /api/contacts` · `GET/POST /api/templates` · `POST /api/templates/preview` · `GET/POST /api/campaigns` · `GET/POST/PATCH/DELETE /api/reminders` · `GET /api/messages` · `POST /api/messages/{id}/retry` · `POST /api/run` · `POST /api/send-test` · `GET /api/report.csv` · `GET /t/o/{id}.png` · `GET /t/c/{id}` · `GET /u/{contact_id}`

## 🔒 Security
No secrets in the repo (`.env` is git-ignored). Credentials via env vars; HTML auto-escaped (no template injection into emails); click redirects validated; unsubscribe respected; use an **App Password**, never your real password.

## 🎓 Learning outcomes
Python modular design · CSV/pandas · SMTP & MIME (`email`, `smtplib`) · Jinja2 templating · RFC 5545 recurrence & timezones · idempotency, retries & backoff · SQLite/SQL schema design · REST API with FastAPI · APScheduler · logging & reporting · unit testing · React/Next.js dashboard · Git/GitHub workflow.

## 🚧 Future improvements
Postgres, SendGrid/Mailgun provider, ICS calendar attachments, WhatsApp/SMS channel, drip sequences, IMAP reply ingestion, Docker + cloud deploy.
