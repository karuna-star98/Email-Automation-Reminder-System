"""Central configuration. Secrets come from environment variables / a local .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Tiny .env loader (no extra dependency). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else ROOT / p


@dataclass(frozen=True)
class Settings:
    db_path: Path
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    sender_name: str
    sender_email: str
    default_tz: str
    tick_seconds: int
    max_retries: int
    retry_backoff_seconds: int
    rate_per_min: int
    grace_hours: int
    allowed_domains: tuple
    tracking_base_url: str
    brand: str
    embedded_worker: bool
    dry_run: bool
    data_dir: Path
    templates_dir: Path
    outputs_dir: Path
    logs_dir: Path
    outbox_dir: Path


def get_settings() -> Settings:
    load_env()
    outputs = _path("OUTPUTS_DIR", "outputs")
    return Settings(
        db_path=_path("DB_PATH", "db/email.db"),
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "465")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_pass=os.getenv("SMTP_PASS", ""),
        sender_name=os.getenv("SENDER_NAME", "Python Academy"),
        sender_email=os.getenv("SENDER_EMAIL", "noreply@example.com"),
        default_tz=os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata"),
        tick_seconds=int(os.getenv("TICK_SECONDS", "15")),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        retry_backoff_seconds=int(os.getenv("RETRY_BACKOFF_SECONDS", "60")),
        rate_per_min=int(os.getenv("RATE_PER_MINUTE", "60")),
        grace_hours=int(os.getenv("GRACE_HOURS", "24")),
        allowed_domains=tuple(d.strip().lower() for d in os.getenv("ALLOWED_DOMAINS", "").split(",") if d.strip()),
        tracking_base_url=os.getenv("TRACKING_BASE_URL", "").rstrip("/"),
        brand=os.getenv("APP_BRAND", "Email Automation & Reminder System"),
        embedded_worker=_bool("EMBEDDED_WORKER", True),
        dry_run=_bool("DRY_RUN", True),
        data_dir=_path("DATA_DIR", "data"),
        templates_dir=_path("TEMPLATES_DIR", "templates"),
        outputs_dir=outputs,
        logs_dir=_path("LOGS_DIR", "logs"),
        outbox_dir=outputs / "outbox",
    )
