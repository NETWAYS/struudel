from __future__ import annotations

import logging

from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.mail import send_mail
from struudel.models.poll import Poll
from struudel.services.notifications import build_poll_url, render_mail
from struudel.services.poll import get_audience_response_status

log = logging.getLogger(__name__)


@huey.task(retries=3, retry_delay=60)
def send_non_responder_report_task(poll_id: int) -> None:
    with SessionLocal() as db:
        poll = db.get(Poll, poll_id)
        if poll is None:
            return
        owner = poll.created_by
        if not owner.is_active or not owner.email:
            return
        _, pending = get_audience_response_status(db, poll=poll)
        subject, html, text = render_mail(
            "non_responder_report",
            poll=poll,
            recipient_user=owner,
            non_responders=pending,
            poll_url=build_poll_url(poll),
        )
        send_mail(to=owner.email, subject=subject, html=html, text=text)
