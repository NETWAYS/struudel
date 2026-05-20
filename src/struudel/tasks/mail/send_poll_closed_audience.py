from __future__ import annotations

import logging

from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.mail import send_mail, try_claim_send_lock
from struudel.models.poll import Poll
from struudel.models.user import User
from struudel.services.notifications import build_poll_url, render_mail

log = logging.getLogger(__name__)


@huey.task(retries=3, retry_delay=60)
def send_poll_closed_audience_task(poll_id: int, user_id: int) -> None:
    if not try_claim_send_lock(f"close:audience:{poll_id}:{user_id}"):
        log.info("close-audience dedup hit for poll=%s user=%s", poll_id, user_id)
        return

    with SessionLocal() as db:
        poll = db.get(Poll, poll_id)
        user = db.get(User, user_id)
        if poll is None or user is None or not user.is_active or not user.email:
            return
        subject, html, text = render_mail(
            "poll_closed_audience",
            poll=poll,
            recipient_user=user,
            poll_url=build_poll_url(poll),
        )
        send_mail(to=user.email, subject=subject, html=html, text=text)
