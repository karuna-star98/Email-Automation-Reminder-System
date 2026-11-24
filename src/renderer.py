"""Template rendering: Jinja2 variables + Markdown -> responsive HTML email (and plain-text part)."""
from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass
from urllib.parse import quote

import markdown
from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateError

# StrictUndefined: a missing variable raises an error instead of silently sending a blank.
_html_env = Environment(loader=BaseLoader(), autoescape=True, undefined=StrictUndefined)
_text_env = Environment(loader=BaseLoader(), autoescape=False, undefined=StrictUndefined)


class RenderError(Exception):
    """Template could not be rendered (e.g. missing variable). Never retried."""


@dataclass
class Rendered:
    subject: str
    html: str
    text: str


def split_template(raw: str) -> tuple[str, str]:
    """Template files look like:  'Subject: Hello {{ name }}' + blank line + markdown body."""
    lines = raw.strip().splitlines()
    if not lines or not lines[0].lower().startswith("subject:"):
        raise ValueError("Template must start with a 'Subject:' line")
    return lines[0].split(":", 1)[1].strip(), "\n".join(lines[1:]).strip()


def _wrap(inner: str, footer: str, brand: str, pixel: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#f4f6fb;font-family:'Segoe UI',Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e9f2;">
<tr><td style="background:#4f46e5;color:#ffffff;padding:20px 28px;font-size:18px;font-weight:600;">&#9993; {htmllib.escape(brand)}</td></tr>
<tr><td style="padding:28px;color:#1f2937;font-size:15px;line-height:1.65;">{inner}</td></tr>
<tr><td style="padding:16px 28px;background:#f9fafb;color:#6b7280;font-size:12px;line-height:1.5;">{footer}</td></tr>
</table></td></tr></table>{pixel}</body></html>"""


def _plain(md: str) -> str:
    """Markdown -> readable plain text (for the text/plain alternative part)."""
    md = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1: \2", md)
    return re.sub(r"\*\*(.+?)\*\*", r"\1", md).strip()


def render_email(subject_tmpl: str, body_md: str, context: dict, *, message_id: str | None = None,
                 contact_id: str | None = None, base_url: str = "", brand: str = "Email Automation") -> Rendered:
    try:
        subject = _text_env.from_string(subject_tmpl).render(**context)
        body_html_md = _html_env.from_string(body_md).render(**context)
        text = _text_env.from_string(body_md).render(**context)
    except TemplateError as exc:  # UndefinedError, TemplateSyntaxError ...
        raise RenderError(f"Template error: {exc}") from exc

    inner = markdown.markdown(body_html_md, extensions=["extra", "sane_lists"])
    inner = inner.replace("<a ", '<a style="color:#4f46e5;font-weight:600;" ')
    pixel = ""
    footer = "You are receiving this automated reminder. If this was a mistake, reply <b>STOP</b>."
    if base_url and message_id:
        def repl(m):  # wrap links so clicks are recorded
            return f'href="{base_url}/t/c/{message_id}?url={quote(htmllib.unescape(m.group(1)), safe="")}"'
        inner = re.sub(r'href="(https?://[^"]+)"', repl, inner)
        pixel = f'<img src="{base_url}/t/o/{message_id}.png" width="1" height="1" alt="" style="display:none">'
        if contact_id:
            footer += f' &nbsp;<a href="{base_url}/u/{contact_id}" style="color:#6b7280;">Unsubscribe</a>'
    return Rendered(subject.strip(), _wrap(inner, footer, brand, pixel), _plain(text) + "\n\n--\nReply STOP to unsubscribe.")
