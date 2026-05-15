"""Test fixtures for the Struudel test suite.

Env vars are set at module load time — pytest imports conftest before any test
files, which import struudel modules. The struudel.config.Settings singleton
reads these env vars on first construction.
"""

from __future__ import annotations

import os

os.environ.setdefault("DB_NAME", "struudel_test")
os.environ.setdefault("DB_USER", "struudel")
os.environ.setdefault("DB_PASS", "struudel")
os.environ.setdefault("DB_HOST", "postgres")
os.environ.setdefault("OIDC_CLIENT_ID", "test-client")
os.environ.setdefault("OIDC_CLIENT_SECRET", "test-secret")
os.environ.setdefault("OIDC_DISCOVERY_URL", "http://test/.well-known/openid-configuration")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
# Disable outgoing mail and isolate from the dev Huey queue: tests must never
# leak enqueues into the shared Redis broker the live dev worker is reading.
os.environ.setdefault("MAIL_ENABLED", "false")

from collections.abc import Generator  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from flask import Flask  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from struudel import database as db_module  # noqa: E402
from struudel.app import create_app  # noqa: E402
from struudel.config import settings  # noqa: E402
from struudel.extensions import huey  # noqa: E402
from struudel.models.user import User  # noqa: E402

# Run Huey tasks synchronously in the pytest process. Without this, every
# enqueue in tests lands in the shared Redis broker (DB 0) and the live dev
# worker picks them up and runs them against the dev database — see the
# poll-close-mail incident from 2026-05-13. Immediate mode keeps tasks
# in-process and bypasses the broker entirely.
huey.immediate = True

BOOTSTRAP_DSN = (
    f"host={settings.db_host} user={settings.db_user} password={settings.db_pass} dbname=postgres"
)


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> Generator[None]:
    """Create struudel_test, run migrations, drop after the session."""
    db_name = sql.Identifier(settings.db_name)
    with psycopg.connect(BOOTSTRAP_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(db_name))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(db_name))

    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")

    yield

    db_module.engine.dispose()
    with psycopg.connect(BOOTSTRAP_DSN, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = {} AND pid <> pg_backend_pid()"
            ).format(sql.Literal(settings.db_name))
        )
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(db_name))


@pytest.fixture(scope="session")
def _engine():
    return create_engine(settings.database_url, future=True)


@pytest.fixture
def db_session(_engine) -> Generator[Session]:
    """Per-test transaction with savepoint isolation.

    Reconfigures the shared `SessionLocal` sessionmaker to bind to the test
    connection. Services that call `with SessionLocal() as db:` will see the
    same outer transaction; their `db.commit()` becomes a savepoint commit.
    Outer transaction is rolled back at fixture teardown.
    """
    connection = _engine.connect()
    transaction = connection.begin()

    db_module.SessionLocal.configure(bind=connection, join_transaction_mode="create_savepoint")

    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        db_module.SessionLocal.configure(bind=db_module.engine, join_transaction_mode=None)


@pytest.fixture(scope="session")
def app() -> Flask:
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    return flask_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


# ---------------------------------------------------------------------------
# Factories & helpers
# ---------------------------------------------------------------------------


_user_counter = 0


def make_user(
    db: Session,
    *,
    name: str | None = None,
    email: str | None = None,
    is_active: bool = True,
) -> User:
    global _user_counter
    _user_counter += 1
    user = User(
        external_id=f"test-{_user_counter}",
        preferred_username=f"user{_user_counter}",
        name=name or f"User {_user_counter}",
        email=email or f"user{_user_counter}@test.local",
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return user


def login_as(client: FlaskClient, user: User) -> None:
    """Stamp the session so `g.user` is populated by `load_current_user`."""
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "preferred_username": user.preferred_username,
        }
