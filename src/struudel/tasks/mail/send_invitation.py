from __future__ import annotations

import logging

from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.mail import send_mail
from struudel.models.poll import Poll
from struudel.models.user import User
from struudel.services.notifications import build_vote_url, render_mail
from struudel.services.poll import get_audience_user_ids

log = logging.getLogger(__name__)


@huey.task(retries=3, retry_delay=60)
def send_invitation_task(poll_id: int, user_id: int) -> None:
    with SessionLocal() as db:
        poll = db.get(Poll, poll_id)
        user = db.get(User, user_id)
        if poll is None or user is None or not user.is_active:
            log.info("invitation skipped (poll=%s, user=%s)", poll_id, user_id)
            return
        if user_id not in get_audience_user_ids(db, poll_id=poll_id):
            log.info("invitation skipped, user %s no longer in audience %s", user_id, poll_id)
            return
        subject, html, text = render_mail(
            "invitation",
            poll=poll,
            recipient_user=user,
            vote_url=build_vote_url(poll),
        )
        send_mail(to=user.email, subject=subject, html=html, text=text)
