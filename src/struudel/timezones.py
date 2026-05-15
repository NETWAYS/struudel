from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from struudel.config import settings

UTC = ZoneInfo("UTC")


@lru_cache(maxsize=1)
def app_tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=app_tz())
    return value.astimezone(UTC)


def to_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(app_tz())
