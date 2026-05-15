from __future__ import annotations

import logging

from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.mail import send_mail
from struudel.models.poll_response import PollResponse
from struudel.services.notifications import build_poll_url, render_mail
from struudel.services.poll import count_responses

log = logging.getLogger(__name__)


@huey.task(retries=3, retry_delay=60)
def send_response_notification_task(response_id: int) -> None:
    with SessionLocal() as db:
        response = db.get(PollResponse, response_id)
        if response is None:
            log.info("response notification skipped, response %s gone", response_id)
            return
        poll = response.poll
        owner = poll.created_by
        if not owner.is_active or not owner.email:
            return

        anonymous = bool(poll.attributes.get("anonymous_votes", False))
        voter = response.user
        voter_name = voter.name or voter.preferred_username if voter else ""

        subject, html, text = render_mail(
            "response_notification",
            poll=poll,
            recipient_user=owner,
            voter_name=voter_name,
            anonymous=anonymous,
            response_count=count_responses(db, poll_id=poll.id),
            poll_url=build_poll_url(poll),
        )
        send_mail(to=owner.email, subject=subject, html=html, text=text)
