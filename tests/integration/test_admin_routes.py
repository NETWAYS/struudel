"""Tests for admin-route safety invariants.

Covers:
- `@require_superuser` rejects unauthenticated and non-superuser callers.
- Self-protection: admin cannot revoke/deactivate/delete their own account.
- `before_request` clears the session when a user becomes inactive.
"""

from __future__ import annotations

from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from struudel.models.poll import Poll, PollResponseMode, PollStatus, PollVisibility
from struudel.models.user import User
from tests.conftest import login_as, make_user


def _make_superuser(db: Session) -> User:
    user = make_user(db)
    user.is_superuser = True
    db.flush()
    return user


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_admin_users_requires_login(client: FlaskClient) -> None:
    response = client.get("/admin/users", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in (response.location or "")


def test_admin_users_forbidden_for_non_superuser(db_session: Session, client: FlaskClient) -> None:
    user = make_user(db_session)  # not superuser
    login_as(client, user)

    response = client.get("/admin/users")
    assert response.status_code == 403


def test_admin_users_ok_for_superuser(db_session: Session, client: FlaskClient) -> None:
    admin = _make_superuser(db_session)
    login_as(client, admin)

    response = client.get("/admin/users")
    assert response.status_code == 200


def test_admin_groups_forbidden_for_non_superuser(db_session: Session, client: FlaskClient) -> None:
    user = make_user(db_session)
    login_as(client, user)

    response = client.get("/admin/groups")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Self-protection on destructive admin actions
# ---------------------------------------------------------------------------


def test_cannot_revoke_own_superuser(db_session: Session, client: FlaskClient) -> None:
    admin = _make_superuser(db_session)
    login_as(client, admin)

    response = client.post(f"/admin/users/{admin.id}/superuser", data={"value": "off"})
    assert response.status_code == 400

    db_session.refresh(admin)
    assert admin.is_superuser is True, "self-revoke must not change the flag"


def test_can_grant_own_superuser_is_noop(db_session: Session, client: FlaskClient) -> None:
    """Granting yourself superuser is allowed (self-block only guards revoke).

    Already-superusers passing value=on is effectively a no-op.
    """
    admin = _make_superuser(db_session)
    login_as(client, admin)

    response = client.post(f"/admin/users/{admin.id}/superuser", data={"value": "on"})
    assert response.status_code in (200, 302)  # success or redirect
    db_session.refresh(admin)
    assert admin.is_superuser is True


def test_cannot_deactivate_self(db_session: Session, client: FlaskClient) -> None:
    admin = _make_superuser(db_session)
    login_as(client, admin)

    response = client.post(f"/admin/users/{admin.id}/active", data={"value": "off"})
    assert response.status_code == 400

    db_session.refresh(admin)
    assert admin.is_active is True


def test_cannot_delete_self(db_session: Session, client: FlaskClient) -> None:
    admin = _make_superuser(db_session)
    login_as(client, admin)

    response = client.post(f"/admin/users/{admin.id}/delete")
    assert response.status_code == 400

    assert db_session.get(User, admin.id) is not None


def test_superuser_can_deactivate_other_user(db_session: Session, client: FlaskClient) -> None:
    admin = _make_superuser(db_session)
    target = make_user(db_session)
    login_as(client, admin)

    response = client.post(f"/admin/users/{target.id}/active", data={"value": "off"})
    assert response.status_code in (200, 302)
    db_session.refresh(target)
    assert target.is_active is False


# ---------------------------------------------------------------------------
# before_request clears stale sessions for inactive users
# ---------------------------------------------------------------------------


def test_inactive_user_session_is_cleared_on_next_request(
    db_session: Session, client: FlaskClient
) -> None:
    user = make_user(db_session, is_active=False)
    login_as(client, user)

    response = client.get("/", follow_redirects=False)

    # before_request sees is_active=False, clears session, dashboard requires
    # auth → redirect to /auth/login.
    assert response.status_code == 302
    assert "/auth/login" in (response.location or "")


# ---------------------------------------------------------------------------
# /admin/polls — authorization + delete
# ---------------------------------------------------------------------------


def _make_poll(db: Session, *, owner_id: int, title: str = "Test poll") -> Poll:
    poll = Poll(
        title=title,
        status=PollStatus.ACTIVE,
        visibility=PollVisibility.PRIVATE,
        response_mode=PollResponseMode.YES_NO_MAYBE,
        attributes={},
        created_by_id=owner_id,
    )
    db.add(poll)
    db.flush()
    return poll


def test_admin_polls_requires_login(client: FlaskClient) -> None:
    response = client.get("/admin/polls", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in (response.location or "")


def test_admin_polls_forbidden_for_non_superuser(db_session: Session, client: FlaskClient) -> None:
    user = make_user(db_session)
    login_as(client, user)

    response = client.get("/admin/polls")
    assert response.status_code == 403


def test_admin_polls_ok_for_superuser(db_session: Session, client: FlaskClient) -> None:
    admin = _make_superuser(db_session)
    login_as(client, admin)

    response = client.get("/admin/polls")
    assert response.status_code == 200


def test_admin_can_delete_any_poll(db_session: Session, client: FlaskClient) -> None:
    admin = _make_superuser(db_session)
    other = make_user(db_session)
    poll = _make_poll(db_session, owner_id=other.id, title="Not mine")
    poll_id = poll.id
    login_as(client, admin)

    response = client.post(f"/admin/polls/{poll_id}/delete")

    assert response.status_code in (200, 302)
    # Route used a separate SessionLocal()-backed session for the delete; drop
    # our identity-map cache so the next read hits the DB through the savepoint.
    db_session.expire_all()
    assert db_session.get(Poll, poll_id) is None


def test_admin_poll_delete_unknown_id_returns_404(db_session: Session, client: FlaskClient) -> None:
    admin = _make_superuser(db_session)
    login_as(client, admin)

    response = client.post("/admin/polls/999999/delete")
    assert response.status_code == 404
