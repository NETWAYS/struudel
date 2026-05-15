from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from struudel.database import SessionLocal
from struudel.extensions import app_state_redis_client, huey
from struudel.mail import send_mail
from struudel.models.poll import Poll, PollStatus
from struudel.models.user import User
from struudel.services.notifications import build_vote_url, render_mail

log = logging.getLogger(__name__)

_TIER_HOURS = {"72h": 72, "24h": 24, "2h": 2}


@huey.task(retries=3, retry_delay=60)
def send_mandatory_reminder_task(poll_id: int, user_id: int, tier: str) -> None:
    if tier not in _TIER_HOURS:
        log.warning("unknown reminder tier %r for poll=%s user=%s", tier, poll_id, user_id)
        return

    dedup_key = f"mail:reminder:{poll_id}:{user_id}:{tier}".encode()
    ttl = max(_TIER_HOURS[tier] * 3600 + 86400, 3600)
    if not app_state_redis_client.set(dedup_key, b"1", ex=ttl, nx=True):
        log.info("reminder dedup hit for poll=%s user=%s tier=%s", poll_id, user_id, tier)
        return

    with SessionLocal() as db:
        poll = db.get(Poll, poll_id)
        user = db.get(User, user_id)
        if poll is None or user is None or not user.is_active or not user.email:
            return
        if poll.status != PollStatus.ACTIVE or not poll.is_mandatory:
            return
        now = datetime.now(UTC)
        if poll.starts_at is not None and poll.starts_at > now:
            return
        if poll.ends_at is None or poll.ends_at <= now:
            return
        if poll.ends_at - now > timedelta(hours=_TIER_HOURS[tier] + 1):
            # ends_at moved further out — drop the reminder rather than fire too early
            return

        subject, html, text = render_mail(
            "mandatory_reminder",
            poll=poll,
            recipient_user=user,
            tier=tier,
            vote_url=build_vote_url(poll),
        )
        send_mail(to=user.email, subject=subject, html=html, text=text)
