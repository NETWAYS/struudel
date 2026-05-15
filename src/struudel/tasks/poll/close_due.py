import logging

from huey import crontab

from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.services.poll import close_due_polls

log = logging.getLogger(__name__)


@huey.periodic_task(crontab(minute="*/5"))
def close_due_polls_task() -> None:
    with SessionLocal() as db:
        count = close_due_polls(db)
    if count:
        log.info("closed %d due poll(s)", count)
