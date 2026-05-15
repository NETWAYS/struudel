from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from huey import crontab
from sqlalchemy.orm import Session

from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.models.poll import Poll, PollStatus
from struudel.models.poll_response import PollResponse
from struudel.services.poll import get_audience_user_ids
from struudel.tasks.mail.send_mandatory_reminder import send_mandatory_reminder_task

log = logging.getLogger(__name__)

# (tier_label, lead_time): if `now` falls within [ends_at - lead, ends_at - lead + 15min]
# we enqueue this tier's reminder.
_TIERS: tuple[tuple[str, timedelta], ...] = (
    ("72h", timedelta(hours=72)),
    ("24h", timedelta(hours=24)),
    ("2h", timedelta(hours=2)),
)

_DISPATCH_WINDOW = timedelta(minutes=15)


@huey.periodic_task(crontab(minute="*/15"))
def dispatch_mandatory_reminders_task() -> None:
    now = datetime.now(UTC)
    horizon = now + max(t[1] for t in _TIERS) + _DISPATCH_WINDOW

    with SessionLocal() as db:
        polls = list(
            db.scalars(
                sa.select(Poll).where(
                    Poll.status == PollStatus.ACTIVE,
                    Poll.is_mandatory.is_(True),
                    Poll.ends_at.is_not(None),
                    Poll.ends_at > now,
                    Poll.ends_at <= horizon,
                    sa.or_(Poll.starts_at.is_(None), Poll.starts_at <= now),
                )
            )
        )
        for poll in polls:
            _dispatch_for_poll(db, poll=poll, now=now)


def _dispatch_for_poll(db: Session, *, poll: Poll, now: datetime) -> None:
    assert poll.ends_at is not None
    remaining = poll.ends_at - now
    tier = _select_tier(remaining)
    if tier is None:
        return

    audience_ids = get_audience_user_ids(db, poll_id=poll.id)
    if not audience_ids:
        return
    responder_ids = set(
        db.scalars(sa.select(PollResponse.user_id).where(PollResponse.poll_id == poll.id)).all()
    )
    non_responders = audience_ids - responder_ids
    if not non_responders:
        return

    log.info(
        "dispatching %s reminder for poll=%s to %d user(s)",
        tier,
        poll.id,
        len(non_responders),
    )
    for user_id in non_responders:
        send_mandatory_reminder_task(poll.id, user_id, tier)


def _select_tier(remaining: timedelta) -> str | None:
    """Pick the most-urgent tier whose lead-time falls inside the dispatch
    window. With the periodic task running every 15 min, we fire when `remaining`
    is within [lead - 15min, lead]."""
    for label, lead in _TIERS:
        if lead - _DISPATCH_WINDOW <= remaining <= lead:
            return label
    return None
