from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from huey import crontab

from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.mail import try_claim_invitation_lock
from struudel.models.poll import Poll, PollStatus
from struudel.services.poll import get_audience_user_ids
from struudel.tasks.mail.send_invitation import send_invitation_task

log = logging.getLogger(__name__)

# How far back we scan. If the worker is down longer than this, polls that
# started during the outage don't trigger invitations — accepted limitation.
_BACKLOG_WINDOW = timedelta(hours=1)


@huey.periodic_task(crontab(minute="*/5"))
def dispatch_pending_invitations_task() -> None:
    now = datetime.now(UTC)
    earliest = now - _BACKLOG_WINDOW

    with SessionLocal() as db:
        polls = list(
            db.scalars(
                sa.select(Poll).where(
                    Poll.status == PollStatus.ACTIVE,
                    Poll.starts_at.is_not(None),
                    Poll.starts_at <= now,
                    Poll.starts_at >= earliest,
                )
            )
        )
        for poll in polls:
            if not try_claim_invitation_lock(poll.id):
                continue
            audience_ids = get_audience_user_ids(db, poll_id=poll.id)
            if not audience_ids:
                continue
            log.info(
                "dispatching deferred invitations for poll=%s to %d user(s)",
                poll.id,
                len(audience_ids),
            )
            for user_id in audience_ids:
                send_invitation_task(poll.id, user_id)
