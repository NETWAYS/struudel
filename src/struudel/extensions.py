from authlib.integrations.flask_client import OAuth
from huey import RedisHuey
from redis import Redis

from struudel.config import settings

huey = RedisHuey("struudel", url=settings.huey_redis_url)
session_redis_client = Redis.from_url(settings.session_redis_url)
app_state_redis_client = Redis.from_url(settings.app_state_redis_url)
oauth = OAuth()
