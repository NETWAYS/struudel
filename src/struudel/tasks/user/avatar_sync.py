from struudel.database import SessionLocal
from struudel.extensions import huey
from struudel.services.user import sync_avatar


@huey.task(retries=3, retry_delay=30)
def sync_user_avatar(user_id: int) -> None:
    with SessionLocal() as db:
        sync_avatar(db, user_id=user_id)
