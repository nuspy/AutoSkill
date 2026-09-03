"""Outgoing email: templates per kind and language, SMTP or console backend.

Sending never raises into request handlers: failures are logged and reported by the return value.
The console backend keeps an in-memory outbox (tests and development).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from autoskill.config import get_settings

log = logging.getLogger(__name__)

_env = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "prompts" / "email"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


@dataclass
class Mail:
    to: str
    subject: str
    text: str
    kind: str = ""
    headers: dict[str, str] = field(default_factory=dict)


OUTBOX: list[Mail] = []  # console backend


def render_email(kind: str, language: str, **ctx) -> tuple[str, str]:
    """(subject, body) from prompts/email/<kind>.<lang>.j2, falling back to English."""
    lang = (language or "en")[:2]
    try:
        template = _env.get_template(f"{kind}.{lang}.j2")
    except TemplateNotFound:
        template = _env.get_template(f"{kind}.en.j2")
    rendered = template.render(**ctx).strip()
    first, _, rest = rendered.partition("\n")
    subject = first.removeprefix("Subject:").strip()
    return subject, rest.strip() + "\n"


def _smtp_send(mail: Mail) -> None:
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    for k, v in mail.headers.items():
        msg[k] = v
    msg.set_content(mail.text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(msg)


async def send_email(to: str, subject: str, text: str, *, kind: str = "") -> bool:
    settings = get_settings()
    mail = Mail(to=to, subject=subject, text=text, kind=kind)
    if settings.email_backend == "none":
        return False
    if settings.email_backend == "console":
        OUTBOX.append(mail)
        log.info("email to %s: %s", to, subject)
        return True
    try:
        await asyncio.to_thread(_smtp_send, mail)
        return True
    except Exception as exc:  # noqa: BLE001 - never break the caller because of SMTP
        log.warning("email to %s failed: %s", to, exc)
        return False


async def send_templated(to: str, kind: str, language: str, **ctx) -> bool:
    subject, text = render_email(kind, language, **ctx)
    return await send_email(to, subject, text, kind=kind)


def reset_outbox() -> None:
    OUTBOX.clear()
