from __future__ import annotations

import logging

from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.mail import send_mail, try_claim_send_lock
from struudel.models.poll import Poll
from struudel.services.notifications import build_poll_url, render_mail
from struudel.services.poll import count_responses

log = logging.getLogger(__name__)


@huey.task(retries=3, retry_delay=60)
def send_poll_closed_owner_task(poll_id: int) -> None:
    if not try_claim_send_lock(f"close:owner:{poll_id}"):
        log.info("close-owner dedup hit for poll=%s", poll_id)
        return

    with SessionLocal() as db:
        poll = db.get(Poll, poll_id)
        if poll is None:
            log.info("poll-closed-owner skipped, poll %s gone", poll_id)
            return
        owner = poll.created_by
        if not owner.is_active or not owner.email:
            return
        subject, html, text = render_mail(
            "poll_closed_owner",
            poll=poll,
            recipient_user=owner,
            response_count=count_responses(db, poll_id=poll.id),
            poll_url=build_poll_url(poll),
        )
        send_mail(to=owner.email, subject=subject, html=html, text=text)
