import logging

from huey import crontab

from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.services.poll import purge_expired_polls

log = logging.getLogger(__name__)


@huey.periodic_task(crontab(minute="0", hour="3"))
def purge_expired_polls_task() -> None:
    with SessionLocal() as db:
        count = purge_expired_polls(db)
    if count:
        log.info("purged %d expired poll(s)", count)
