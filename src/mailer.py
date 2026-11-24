"""Mail providers. DryRunMailer (safe, default) writes .eml/.html files; SMTPMailer really sends."""
from __future__ import annotations

import re
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from .config import Settings

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


@dataclass
class SendResult:
    ok: bool
    provider_msg_id: str | None = None
    error: str | None = None
    permanent: bool = False  # True -> retrying will not help


def is_valid_email(addr: str) -> bool:
    return bool(addr and EMAIL_RE.match(addr.strip()))


def build_message(from_name, from_email, to_email, subject, html, text, unsubscribe_url: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1])
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


class BaseMailer:
    name = "base"

    def send(self, *, from_name, from_email, to_email, subject, html, text, unsubscribe_url="") -> SendResult:
        raise NotImplementedError


class DryRunMailer(BaseMailer):
    """Never touches the network. Saves each email to outputs/outbox/ so you can open and screenshot it."""
    name = "dry-run"

    def __init__(self, outbox: Path):
        self.outbox = outbox
        outbox.mkdir(parents=True, exist_ok=True)

    def send(self, *, from_name, from_email, to_email, subject, html, text, unsubscribe_url="") -> SendResult:
        msg = build_message(from_name, from_email, to_email, subject, html, text, unsubscribe_url)
        stem = f"{to_email.split('@')[0]}_{uuid.uuid4().hex[:8]}"
        (self.outbox / f"{stem}.eml").write_bytes(bytes(msg))
        (self.outbox / f"{stem}.html").write_text(html, encoding="utf-8")
        return SendResult(True, provider_msg_id=msg["Message-ID"])


class SMTPMailer(BaseMailer):
    """Real delivery via any SMTP server (Gmail needs an App Password, never your normal password)."""
    name = "smtp"

    def __init__(self, host, port, username, password):
        self.host, self.port, self.username, self.password = host, port, username, password

    def send(self, *, from_name, from_email, to_email, subject, html, text, unsubscribe_url="") -> SendResult:
        if not (self.username and self.password):
            return SendResult(False, error="SMTP credentials missing (set SMTP_USER / SMTP_PASS in .env)", permanent=True)
        msg = build_message(from_name, from_email, to_email, subject, html, text, unsubscribe_url)
        ctx = ssl.create_default_context()
        try:
            if self.port == 465:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=30, context=ctx)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=30)
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
            with server:
                server.login(self.username, self.password)
                refused = server.send_message(msg)
            if refused:
                return SendResult(False, error=f"Recipient refused: {refused}", permanent=True)
            return SendResult(True, provider_msg_id=msg["Message-ID"])
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPAuthenticationError, smtplib.SMTPSenderRefused) as exc:
            return SendResult(False, error=f"{type(exc).__name__}: {exc}", permanent=True)
        except (smtplib.SMTPException, OSError) as exc:  # network blips, timeouts, 4xx -> retry
            return SendResult(False, error=f"{type(exc).__name__}: {exc}")


def get_mailer(settings: Settings, live: bool) -> BaseMailer:
    if live:
        return SMTPMailer(settings.smtp_host, settings.smtp_port, settings.smtp_user, settings.smtp_pass)
    return DryRunMailer(settings.outbox_dir)
