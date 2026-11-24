# Project Guide — Email Automation & Reminder System
Covers every section of the assignment prompt. Code lives in the repo; this guide explains, plans and prepares you.

## 1. Project explanation
**Simple:** a robot assistant that sends the right email to the right person at the right time — class reminders, payment dues, webinar alerts — and keeps a diary of what happened.
**Technical:** a scheduler expands reminder rules (one-off or RFC 5545 RRULE) into idempotent `messages` rows; a worker renders Jinja2/Markdown templates per contact, sends through a pluggable provider (dry-run or SMTP), records status/errors, retries transient failures with backoff, and exports reports.

**Problem solved:** manual follow-ups are slow, forgotten and inconsistent. **Who benefits:** trainers (class/assignment reminders), HR (interview & onboarding nudges), sales (follow-ups after demos), finance/ops (invoice and payment reminders), admin (meeting alerts), support (ticket nudges). Python automates the repetitive part (looping, personalising, timing, logging) so humans handle replies.

**Workflow:** contact list → message template → scheduled reminder → email sending → status tracking → report generation.

## 2. Tech-stack options
| Option | Stack | Difficulty | Output |
|---|---|---|---|
| A Easy | Python, pandas, smtplib, `schedule`, CSV, logging | ★☆☆ | Script sending emails + CSV report |
| B Intermediate | A + Jinja2, SQLite, RRULE, retries, dry-run, Streamlit dashboard | ★★☆ | Robust CLI + simple dashboard |
| C Advanced (**this repo**) | B + FastAPI, APScheduler, Next.js, tracking pixel, rate limit, tests | ★★★ | Full product: API + worker + dashboard |

**Best for students:** build Option B first (Days 1–5), then add the API/dashboard layer (Option C) for a standout portfolio. The repo already contains all of it, so you can demo A→C.

## 3. Architecture
See the diagram in `README.md`. **Input:** contacts CSV, reminders CSV, templates. **Processing:** read → personalise → schedule → send → track. **Output:** sent emails (outbox), failed/sent logs, reminder log, CSV report.
**Data flow:** CSV → `importer.py` → SQLite → `scheduler.plan_next_fires` creates `messages` (unique `dedupe_key`) → `dispatch_due` renders (`renderer.py`) and sends (`mailer.py`) → status written back → `reports.py` exports CSV/JSON.

## 4. Implementation plan (10 phases)
| # | Phase | What / why | Expected output | Beginner mistake |
|---|---|---|---|---|
| 1 | Setup | Install Python 3.11+, VS Code, Git | `python --version` works | Not adding Python to PATH |
| 2 | Folders | Create structure (section 5) | Folders visible | Putting everything in one file |
| 3 | Contact CSV | Dummy people with timezones | `data/contacts.csv` | Using real people's emails |
| 4 | Templates | Markdown with `{{ variables }}` | `templates/*.md` | Forgetting the `Subject:` line |
| 5 | SMTP config | `.env` + App Password | Config loads | Committing `.env`; using normal password |
| 6 | Personalisation | Jinja2 + Markdown → HTML | Rendered email | Silent blank variables (we use StrictUndefined) |
| 7 | Scheduling | RRULE → messages, timezone aware | Planned messages | Mixing local time and UTC |
| 8 | Sending | Dry-run first, then `--live` to yourself | Outbox files / inbox mail | Testing on real customers |
| 9 | Logs & report | sent/failed logs + CSV | `logs/`, `outputs/` | Not logging the failure reason |
| 10 | GitHub | Commit, push, README, screenshots | Public repo | Uploading passwords |

## 5. Folder structure
`data/` input CSVs · `templates/` email templates · `src/` engine code · `api/` FastAPI · `apps/web/` dashboard · `outputs/` reports & dry-run outbox · `logs/` log files · `images/` screenshots · `docs/` documentation · `tests/` automated tests · `main.py` CLI entry · `README.md`, `requirements.txt`, `.gitignore`, `.env.example`.

## 6. Installation
```bash
# Windows                              # Mac / Linux
python -m venv .venv                   python3 -m venv .venv
.venv\Scripts\activate                 source .venv/bin/activate
pip install -r requirements.txt        pip install -r requirements.txt
copy .env.example .env                 cp .env.example .env
```
Libraries: pandas, Jinja2, Markdown, python-dateutil, tzdata (core); FastAPI, uvicorn, APScheduler (API); pytest. Dashboard needs Node 18+.

## 7. Full project code
All code is in the repository: `src/*.py`, `api/app.py`, `main.py`, `apps/web/app/page.tsx`. It includes CSV reading, template loading, personalisation, SMTP sending, scheduling, error handling, success/failure logging, CSV reports, env-var secrets and dry-run mode.

## 8. Virtual simulation
- **Dummy data:** `data/contacts.csv` (10 people, includes 1 unsubscribed + 1 invalid email on purpose).
- **Sample reminders:** `data/reminders.csv` uses relative times (`+1m`, `+1h`, `+1d`) so it works whenever you run it; includes recurring rules and one deliberately broken template.
- **Templates:** `templates/*.md` (class, payment, webinar, task, follow-up).
- **Run safely:** `python main.py demo` — dry-run, no network. `--at +1d` fast-forwards the clock.
- **Outputs:** `outputs/outbox/*.html` (open in browser = the email), `logs/*.log`, `outputs/email_report_*.csv`.
- **In a real company:** the worker runs 24/7 on a server/container, contacts come from a CRM/HR database, SMTP is replaced by SendGrid/SES, and domain SPF/DKIM keep mail out of spam.
- **Never upload:** `.env`, passwords/app passwords, real customer emails, real logs containing personal data.

## 9. How to run
```bash
python main.py demo          # simulation (expected output in docs/sample_output/demo_terminal_output.txt)
python main.py run           # dry-run cycle
python main.py run --live    # real emails (needs .env) — test with your own address first
python main.py worker        # continuous
```
Generated: `logs/sent_emails.log`, `logs/failed_emails.log`, `logs/app.log`, `outputs/email_report_<time>.csv`, `outputs/summary_<time>.json`.

## 10. GitHub upload
```bash
git init
git add .
git status                       # confirm .env is NOT listed
git commit -m "feat: initial email automation engine"
git branch -M main
git remote add origin https://github.com/<you>/Email-Automation-Reminder-System.git
git push -u origin main
```
- **Repo name:** `Email-Automation-Reminder-System`
- **Description:** *Python + FastAPI + Next.js system to schedule, send and track personalised email reminders with RRULE recurrence, retries, dry-run mode and CSV reports.*
- **Topics:** `python` `fastapi` `nextjs` `email-automation` `smtp` `scheduler` `apscheduler` `jinja2` `automation` `reminder-system` `sqlite` `portfolio-project`
- **Safety:** never commit passwords; keep `.env` ignored, ship `.env.example`. If a secret leaks: revoke it immediately — deleting the commit is not enough.

## 11. README
Ready-made in `README.md` (overview, problem, relevance, features, stack, structure, setup, env vars, run, sample output, screenshots, outcomes).

## 12. Proof-building strategy (6 days)
| Day | Do | Commit message | Save |
|---|---|---|---|
| 1 | Setup, folders, venv, `.gitignore` | `chore: project scaffold` | folder screenshot |
| 2 | Contacts CSV + templates | `feat: sample contacts and templates` | CSV + template screenshots |
| 3 | Rendering / personalisation | `feat: jinja2 markdown renderer` | rendered email screenshot |
| 4 | Scheduler + RRULE + mailer | `feat: scheduler, dry-run and smtp mailer` | dry-run terminal |
| 5 | Logging, retries, report, tests | `feat: logging, retries, csv report, tests` | logs + report CSV |
| 6 | API/dashboard, README, screenshots | `docs: readme, guide and screenshots` | GitHub preview |

## 13. Screenshots / outputs
1. Project folder tree · 2. `contacts.csv` · 3. a template file · 4. `python main.py demo` terminal · 5. reminder schedule (`python main.py run --at +1d`) · 6. `logs/sent_emails.log` and `failed_emails.log` · 7. report CSV opened in Excel · 8. dashboard (`localhost:3000`) · 9. an outbox `.html` email in the browser · 10. GitHub repo page. Save into `images/` and link from README.

## 14. Interview preparation
**1. Explain your project.** *HR version:* "I built a system that automatically sends reminder emails at the right time so teams don't have to follow up manually, and it reports what was delivered or failed." *Technical version:* "It's a Python engine that imports contacts and reminders, expands one-off and RRULE schedules in each contact's timezone into idempotent message records, renders Jinja2/Markdown templates, sends via SMTP or a dry-run provider, retries transient failures with exponential backoff, logs every outcome and exports CSV reports. A FastAPI backend and Next.js dashboard sit on top."

**2. What problem does it solve?** Repetitive manual reminders: class, meeting, webinar, task and payment follow-ups — it saves time and prevents missed messages.

**3. Technologies?** Python, pandas, smtplib/`email`, Jinja2, python-dateutil (RRULE), SQLite, FastAPI, APScheduler, Next.js, pytest, logging.

**4. How is personalisation done?** CSV/DB gives name, title, time and custom variables; Jinja2 fills placeholders. `StrictUndefined` makes a missing variable an error rather than a blank email.

**5. What is SMTP?** Simple Mail Transfer Protocol — how mail is submitted to a server. I use `smtplib` over SSL/STARTTLS with an app password from env vars.

**6. Error handling?** Invalid addresses and template errors fail immediately; network/timeouts retry with exponential backoff up to `MAX_RETRIES`; auth/recipient-refused errors are permanent. Everything is logged to `failed_emails.log`.

**7. How do you avoid sending duplicates?** Each reminder occurrence has a unique `dedupe_key` (reminder id + time) and a message is *claimed* (`scheduled → sending`) atomically before sending, so two workers or a restart can't double-send.

**8. How do you handle timezones and recurring reminders?** Store UTC; evaluate the RRULE in the contact's local time so "9 AM daily" stays 9 AM across DST; stale occurrences older than a grace window are skipped after downtime.

**9. How is it safe for GitHub and production?** Secrets only in env vars, `.env` git-ignored, `.env.example` committed, dry-run by default, unsubscribe respected, rate limiting, optional domain allow-list, escaped HTML, validated click redirects.

**10. How would you improve it?** Postgres + queue (Celery/RQ), SendGrid/SES provider with webhooks for bounces, ICS invites, SMS/WhatsApp, drip sequences, Docker + cloud deploy, metrics endpoint.

**Bonus — non-technical explanation:** "I made a tool that sends reminder emails by itself at the right time and shows who got them."
