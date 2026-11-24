"""Logging: console + app.log, plus dedicated sent_emails.log and failed_emails.log."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import Settings

FMT = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")


def setup_logging(settings: Settings, console: bool = True) -> logging.Logger:
    root = logging.getLogger("emailauto")
    if root.handlers:  # already configured
        return root
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    root.setLevel(logging.INFO)

    def add(logger, filename):
        h = RotatingFileHandler(settings.logs_dir / filename, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(FMT)
        logger.addHandler(h)

    add(root, "app.log")
    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(FMT)
        root.addHandler(sh)
    add(logging.getLogger("emailauto.sent"), "sent_emails.log")
    add(logging.getLogger("emailauto.failed"), "failed_emails.log")
    return root
