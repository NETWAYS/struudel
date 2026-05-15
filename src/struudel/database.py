from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from struudel.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass
