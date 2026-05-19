import io
import ipaddress
import logging
import socket
from datetime import UTC, datetime
from typing import Any, NamedTuple
from urllib.parse import urlparse

import requests
import sqlalchemy as sa
from PIL import Image, UnidentifiedImageError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from struudel.config import settings
from struudel.models.poll import Poll
from struudel.models.user import User

log = logging.getLogger(__name__)

_AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_AVATAR_CHUNK_BYTES = 64 * 1024
_AVATAR_TIMEOUT_SECONDS = 10
_AVATAR_ALLOWED_SCHEMES = frozenset({"http", "https"})
_AVATAR_MAX_PIXELS = 25_000_000  # cap PIL decode work — 5000×5000 px

# Pillow bombs if it tries to decode a malicious oversize image. Set a hard
# cap module-wide so any subsequent Image.open() in this process is bounded.
Image.MAX_IMAGE_PIXELS = _AVATAR_MAX_PIXELS


def _is_public_host(hostname: str) -> bool:
    """Reject hostnames that resolve to private, loopback, link-local or
    multicast addresses. Guards against SSRF via attacker-controlled
    `picture` claims (OIDC) or SCIM payloads."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def get_user_by_id(db: Session, *, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_external_id(db: Session, *, external_id: str) -> User | None:
    return db.scalar(sa.select(User).where(User.external_id == external_id))


class UserAuthStatus(NamedTuple):
    is_active: bool
    is_superuser: bool


class UserCounts(NamedTuple):
    total: int
    superusers: int
    inactive: int


def count_users(db: Session) -> UserCounts:
    row = db.execute(
        sa.select(
            sa.func.count().label("total"),
            sa.func.count().filter(User.is_superuser.is_(True)).label("superusers"),
            sa.func.count().filter(User.is_active.is_(False)).label("inactive"),
        ).select_from(User)
    ).one()
    return UserCounts(total=row.total, superusers=row.superusers, inactive=row.inactive)


def get_user_auth_status(db: Session, *, user_id: int) -> UserAuthStatus | None:
    row = db.execute(
        sa.select(User.is_active, User.is_superuser).where(User.id == user_id)
    ).one_or_none()
    if row is None:
        return None
    return UserAuthStatus(is_active=row.is_active, is_superuser=row.is_superuser)


def get_cached_avatar(db: Session, *, user_id: int) -> bytes | None:
    return db.scalar(sa.select(User.cached_picture).where(User.id == user_id))


def list_users(
    db: Session,
    *,
    filter_attr: str | None = None,
    filter_value: str | None = None,
    start_index: int = 1,
    count: int = 50,
) -> tuple[list[User], int]:
    stmt = sa.select(User)
    count_stmt = sa.select(sa.func.count()).select_from(User)

    if filter_attr is not None and filter_value is not None:
        column = _user_filter_column(filter_attr)
        if column is None:
            return [], 0
        stmt = stmt.where(column == filter_value)
        count_stmt = count_stmt.where(column == filter_value)

    total = db.scalar(count_stmt) or 0
    offset = max(start_index - 1, 0)
    stmt = stmt.order_by(User.id).offset(offset).limit(max(count, 0))
    users = list(db.scalars(stmt).all())
    return users, total


def _user_filter_column(attr: str) -> Any:
    mapping: dict[str, Any] = {
        "id": User.id,
        "username": User.preferred_username,
        "externalid": User.external_id,
        "email": User.email,
    }
    return mapping.get(attr.lower())


def create_user(
    db: Session,
    *,
    external_id: str,
    preferred_username: str,
    name: str,
    email: str,
    given_name: str | None = None,
    family_name: str | None = None,
    active: bool = True,
) -> User:
    user = User(
        external_id=external_id,
        preferred_username=preferred_username,
        name=name,
        given_name=given_name,
        family_name=family_name,
        email=email,
        is_active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("SCIM create_user id=%s external_id=%s", user.id, external_id)
    return user


def update_user(
    db: Session,
    *,
    user_id: int,
    preferred_username: str | None = None,
    name: str | None = None,
    given_name: str | None = None,
    family_name: str | None = None,
    email: str | None = None,
    active: bool | None = None,
    external_id: str | None = None,
) -> User | None:
    user = db.get(User, user_id)
    if user is None:
        return None

    if preferred_username is not None:
        user.preferred_username = preferred_username
    if name is not None:
        user.name = name
    if given_name is not None:
        user.given_name = given_name
    if family_name is not None:
        user.family_name = family_name
    if email is not None:
        user.email = email
    if active is not None:
        user.is_active = active
    if external_id is not None:
        user.external_id = external_id

    db.commit()
    db.refresh(user)
    log.info("SCIM update_user id=%s", user_id)
    return user


def deactivate_user(db: Session, *, user_id: int) -> bool:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return False
    user.is_active = False
    db.commit()
    log.info("SCIM deactivate_user id=%s external_id=%s", user_id, user.external_id)
    return True


def user_to_session_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "external_id": user.external_id,
        "preferred_username": user.preferred_username,
        "name": user.name,
        "email": user.email,
        "profile": user.profile,
        "picture": user.picture,
    }


def get_user_by_username(db: Session, *, preferred_username: str) -> User | None:
    return db.scalar(sa.select(User).where(User.preferred_username == preferred_username))


def set_superuser(db: Session, *, user_id: int, value: bool) -> User | None:
    user = db.get(User, user_id)
    if user is None:
        return None
    user.is_superuser = value
    db.commit()
    db.refresh(user)
    log.info("set_superuser id=%s value=%s", user_id, value)
    return user


def sync_superuser_from_oidc_groups(
    db: Session, *, user_id: int, group_names: list[str] | None
) -> None:
    """If SUPERUSER_GROUP is configured, set the user's is_superuser flag based on
    whether the configured group name appears in the OIDC `groups` claim.
    No-op when the setting is empty."""
    target = settings.superuser_group.strip().lower()
    if not target:
        return
    names = group_names or []
    value = any(isinstance(g, str) and g.strip().lower() == target for g in names)
    user = db.get(User, user_id)
    if user is None or user.is_superuser == value:
        return
    user.is_superuser = value
    db.commit()
    log.info("auto-superuser via OIDC: user=%s value=%s", user_id, value)


def list_superusers(db: Session) -> list[User]:
    stmt = sa.select(User).where(User.is_superuser.is_(True)).order_by(User.preferred_username)
    return list(db.scalars(stmt).all())


def search_users(
    db: Session,
    *,
    query: str = "",
    page: int = 1,
    per_page: int = 20,
    only_superusers: bool = False,
    only_inactive: bool = False,
) -> tuple[list[User], int, int]:
    """Paginated user search. Returns (users, total, effective_page).

    `effective_page` is the requested page clamped into [1, total_pages]
    so callers never have to repeat the math.
    """
    stmt = sa.select(User)
    count_stmt = sa.select(sa.func.count()).select_from(User)

    q = query.strip()
    if q:
        pattern = f"%{q}%"
        text_filter = sa.or_(
            User.preferred_username.ilike(pattern),
            User.name.ilike(pattern),
        )
        stmt = stmt.where(text_filter)
        count_stmt = count_stmt.where(text_filter)

    if only_superusers:
        stmt = stmt.where(User.is_superuser.is_(True))
        count_stmt = count_stmt.where(User.is_superuser.is_(True))

    if only_inactive:
        stmt = stmt.where(User.is_active.is_(False))
        count_stmt = count_stmt.where(User.is_active.is_(False))

    total = db.scalar(count_stmt) or 0
    total_pages = max(1, ((total - 1) // per_page) + 1) if total else 1
    effective_page = min(max(page, 1), total_pages)
    offset = (effective_page - 1) * per_page
    stmt = stmt.order_by(User.preferred_username).offset(offset).limit(per_page)
    return list(db.scalars(stmt)), total, effective_page


def reactivate_user(db: Session, *, user_id: int) -> bool:
    user = db.get(User, user_id)
    if user is None or user.is_active:
        return False
    user.is_active = True
    db.commit()
    log.info("reactivate_user id=%s", user_id)
    return True


def delete_user_and_artifacts(db: Session, *, user_id: int) -> bool:
    user = db.get(User, user_id)
    if user is None:
        return False
    owned_polls = list(db.scalars(sa.select(Poll).where(Poll.created_by_id == user_id)))
    for poll in owned_polls:
        db.delete(poll)
    db.delete(user)
    db.commit()
    log.info(
        "delete_user_and_artifacts id=%s polls_deleted=%d",
        user_id,
        len(owned_polls),
    )
    return True


def upsert_user(
    db: Session,
    *,
    external_id: str,
    preferred_username: str,
    name: str,
    email: str,
    given_name: str | None = None,
    family_name: str | None = None,
    profile: str | None = None,
    picture: str | None = None,
) -> User:
    now = datetime.now(tz=UTC)
    values = {
        "external_id": external_id,
        "preferred_username": preferred_username,
        "name": name,
        "given_name": given_name,
        "family_name": family_name,
        "email": email,
        "profile": profile,
        "picture": picture,
        "last_login_at": now,
    }
    update_values = {k: v for k, v in values.items() if k != "external_id"}
    stmt = (
        pg_insert(User)
        .values(**values)
        .on_conflict_do_update(index_elements=["external_id"], set_=update_values)
        .returning(User)
    )
    user = db.scalars(stmt).one()
    db.commit()
    return user


def _download_avatar(url: str) -> bytes | None:
    parsed = urlparse(url)
    if parsed.scheme not in _AVATAR_ALLOWED_SCHEMES or not parsed.netloc:
        log.warning("Rejecting avatar URL with unsupported scheme: %s", parsed.scheme)
        return None

    if parsed.hostname is None or not _is_public_host(parsed.hostname):
        log.warning("Rejecting avatar URL pointing at non-public host: %s", parsed.hostname)
        return None

    # `allow_redirects=False` so an attacker cannot bounce us off a public
    # host into an internal one. Avatar providers serve direct image URLs.
    with requests.get(
        url, timeout=_AVATAR_TIMEOUT_SECONDS, stream=True, allow_redirects=False
    ) as response:
        if response.is_redirect or response.is_permanent_redirect:
            log.warning("Avatar URL %s redirected; refusing to follow", url)
            return None
        response.raise_for_status()

        declared = response.headers.get("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > _AVATAR_MAX_BYTES:
            log.warning("Avatar at %s exceeds size limit (Content-Length)", url)
            return None

        buf = bytearray()
        for chunk in response.iter_content(chunk_size=_AVATAR_CHUNK_BYTES):
            buf.extend(chunk)
            if len(buf) > _AVATAR_MAX_BYTES:
                log.warning("Avatar at %s exceeds size limit during streaming", url)
                return None

    return bytes(buf)


def sync_avatar(db: Session, *, user_id: int) -> None:
    user = db.get(User, user_id)
    if user is None or not user.picture:
        return

    try:
        raw = _download_avatar(user.picture)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status is not None and 400 <= status < 500:
            log.warning("Avatar fetch for user %d failed with %d, giving up", user_id, status)
            return
        raise

    if raw is None:
        return

    try:
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
    except (UnidentifiedImageError, OSError) as e:
        log.warning("Failed to process avatar for user %d: %s", user_id, e)
        return

    stmt = sa.update(User).where(User.id == user_id).values(cached_picture=buf.getvalue())
    db.execute(stmt)
    db.commit()
