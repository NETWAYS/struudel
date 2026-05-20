from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from urllib.parse import urlparse

from struudel.config import settings
from struudel.extensions import app_state_redis_client

log = logging.getLogger(__name__)

# Long enough to outlast typical poll lifetimes — the lock just needs to
# survive the window the pending-invitation dispatcher scans.
_INVITATION_LOCK_TTL_SECONDS = 7 * 24 * 3600


def try_claim_invitation_lock(poll_id: int) -> bool:
    """Atomically mark a poll as "initial invitations dispatched".

    Returns True on the first call for a poll (caller should send), False on
    every subsequent call within the TTL. Used to make the immediate-activation
    path and the deferred (starts_at-in-future) path mutually exclusive.
    """
    key = f"mail:invitation_dispatched:{poll_id}".encode()
    return bool(app_state_redis_client.set(key, b"1", ex=_INVITATION_LOCK_TTL_SECONDS, nx=True))


def _message_id_domain() -> str:
    """Stable domain for Message-ID generation.

    Explicit `mail_message_id_domain` wins; otherwise we use the host of
    `app_base_url`. Last-ditch fallback is the host part of `mail_from`
    so we never hand make_msgid an empty string (which would make it
    fall back to socket.getfqdn() — usually the container id).
    """
    if settings.mail_message_id_domain:
        return settings.mail_message_id_domain
    host = urlparse(settings.app_base_url).hostname
    if host:
        return host
    _, _, from_domain = settings.mail_from.partition("@")
    return from_domain or "localhost"


def send_mail(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    reply_to: str | None = None,
) -> None:
    if not settings.mail_enabled:
        log.info("mail disabled, skipping send to %s (subject=%r)", to, subject)
        return

    msg = EmailMessage()
    msg["From"] = formataddr((settings.mail_from_name, settings.mail_from))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=_message_id_domain())
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    timeout = settings.mail_timeout_seconds
    if settings.mail_ssl:
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.mail_host, settings.mail_port, timeout=timeout
        )
    else:
        client = smtplib.SMTP(settings.mail_host, settings.mail_port, timeout=timeout)

    with client as smtp:
        smtp.ehlo()
        if settings.mail_starttls and not settings.mail_ssl:
            smtp.starttls()
            smtp.ehlo()
        if settings.mail_username:
            smtp.login(settings.mail_username, settings.mail_password)
        smtp.send_message(msg)

    log.info("sent mail to %s (subject=%r)", to, subject)
