"""Tests for admin-facing user service functions.

Covers:
- `search_users` text/superuser/inactive filters, page clamping.
- `delete_user_and_artifacts` removes the owner's polls and the user.
- `get_user_auth_status` returns current flags / None.
"""

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from struudel.models.poll import Poll, PollResponseMode, PollStatus, PollVisibility
from struudel.models.poll_option import PollOption, PollOptionType
from struudel.models.poll_response import PollResponse
from struudel.models.user import User
from struudel.services import user as user_service
from tests.conftest import make_user

# ---------------------------------------------------------------------------
# search_users
# ---------------------------------------------------------------------------


def test_search_users_clamps_page_beyond_total(db_session: Session) -> None:
    for _ in range(3):
        make_user(db_session)
    db_session.flush()

    users, total, effective_page = user_service.search_users(db_session, page=999, per_page=20)

    assert total == 3
    assert effective_page == 1, "page should clamp to last existing page"
    assert len(users) == 3


def test_search_users_paginates(db_session: Session) -> None:
    for _ in range(7):
        make_user(db_session)
    db_session.flush()

    page1, total, p1 = user_service.search_users(db_session, page=1, per_page=3)
    page2, _, p2 = user_service.search_users(db_session, page=2, per_page=3)
    page3, _, p3 = user_service.search_users(db_session, page=3, per_page=3)

    assert total == 7
    assert (p1, p2, p3) == (1, 2, 3)
    assert (len(page1), len(page2), len(page3)) == (3, 3, 1)
    # No duplicates across pages
    ids = {u.id for u in page1} | {u.id for u in page2} | {u.id for u in page3}
    assert len(ids) == 7


def test_search_users_filters_only_superusers(db_session: Session) -> None:
    make_user(db_session)
    b = make_user(db_session)
    b.is_superuser = True
    db_session.flush()

    users, total, _ = user_service.search_users(db_session, only_superusers=True)
    assert total == 1
    assert users[0].id == b.id


def test_search_users_filters_only_inactive(db_session: Session) -> None:
    make_user(db_session, is_active=True)
    b = make_user(db_session, is_active=False)
    db_session.flush()

    users, total, _ = user_service.search_users(db_session, only_inactive=True)
    assert total == 1
    assert users[0].id == b.id


@pytest.mark.parametrize(
    ("query_factory", "expected_total"),
    [
        (lambda alice: "alice", 1),
        (lambda alice: alice.preferred_username, 1),
        (lambda alice: "zzz-noone", 0),
    ],
    ids=["by-name", "by-username", "no-match"],
)
def test_search_users_text_filter(
    db_session: Session,
    query_factory: Callable[[User], str],
    expected_total: int,
) -> None:
    alice = make_user(db_session, name="Alice Anderson")
    make_user(db_session, name="Bob Brown")
    db_session.flush()

    query = query_factory(alice)
    found, total, _ = user_service.search_users(db_session, query=query)

    assert total == expected_total
    if expected_total > 0:
        assert found[0].id == alice.id
    else:
        assert found == []


def test_search_users_combines_text_with_superuser_filter(db_session: Session) -> None:
    a = make_user(db_session, name="Alice Admin")
    a.is_superuser = True
    make_user(db_session, name="Alice Normal")
    db_session.flush()

    found, total, _ = user_service.search_users(db_session, query="alice", only_superusers=True)

    assert total == 1
    assert found[0].id == a.id


# ---------------------------------------------------------------------------
# delete_user_and_artifacts
# ---------------------------------------------------------------------------


def test_delete_user_and_artifacts_removes_owned_polls(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session)

    poll = Poll(
        title="To Delete",
        status=PollStatus.ACTIVE,
        visibility=PollVisibility.PRIVATE,
        response_mode=PollResponseMode.YES_NO_MAYBE,
        attributes={},
        created_by_id=owner.id,
    )
    db_session.add(poll)
    db_session.flush()
    db_session.add(
        PollOption(
            poll_id=poll.id,
            option_type=PollOptionType.TEXT,
            sort_order=0,
            is_custom=False,
            text_value="A",
        )
    )
    db_session.add(PollResponse(poll_id=poll.id, user_id=voter.id))
    db_session.flush()
    poll_id = poll.id

    deleted = user_service.delete_user_and_artifacts(db_session, user_id=owner.id)

    assert deleted is True
    assert db_session.get(User, owner.id) is None
    assert db_session.get(Poll, poll_id) is None, "owned poll cascades away"
    assert db_session.get(User, voter.id) is not None, "voter unaffected"


def test_delete_user_and_artifacts_cascades_responses_to_other_polls(
    db_session: Session,
) -> None:
    """Deleting a user removes their responses on polls owned by others."""
    owner = make_user(db_session)
    voter = make_user(db_session)

    poll = Poll(
        title="Other's Poll",
        status=PollStatus.ACTIVE,
        attributes={},
        created_by_id=owner.id,
    )
    db_session.add(poll)
    db_session.flush()
    response = PollResponse(poll_id=poll.id, user_id=voter.id)
    db_session.add(response)
    db_session.flush()
    response_id = response.id

    user_service.delete_user_and_artifacts(db_session, user_id=voter.id)

    assert db_session.get(User, voter.id) is None
    assert db_session.get(PollResponse, response_id) is None, (
        "voter's response should cascade via poll_responses.user_id"
    )
    # Poll itself remains because the owner is untouched
    assert db_session.get(Poll, poll.id) is not None


def test_delete_user_and_artifacts_returns_false_for_unknown_id(
    db_session: Session,
) -> None:
    assert user_service.delete_user_and_artifacts(db_session, user_id=999_999) is False


# ---------------------------------------------------------------------------
# get_user_auth_status
# ---------------------------------------------------------------------------


def test_get_user_auth_status_returns_flags(db_session: Session) -> None:
    user = make_user(db_session, is_active=True)
    user.is_superuser = True
    db_session.flush()

    status = user_service.get_user_auth_status(db_session, user_id=user.id)
    assert status is not None
    assert status.is_active is True
    assert status.is_superuser is True


def test_get_user_auth_status_reflects_inactive(db_session: Session) -> None:
    user = make_user(db_session, is_active=False)
    db_session.flush()

    status = user_service.get_user_auth_status(db_session, user_id=user.id)
    assert status is not None
    assert status.is_active is False
    assert status.is_superuser is False


def test_get_user_auth_status_unknown_id_returns_none(db_session: Session) -> None:
    assert user_service.get_user_auth_status(db_session, user_id=999_999) is None


# ---------------------------------------------------------------------------
# set_superuser / reactivate_user
# ---------------------------------------------------------------------------


def test_set_superuser_toggles_flag(db_session: Session) -> None:
    user = make_user(db_session)
    assert user.is_superuser is False

    user_service.set_superuser(db_session, user_id=user.id, value=True)
    db_session.refresh(user)
    assert user.is_superuser is True

    user_service.set_superuser(db_session, user_id=user.id, value=False)
    db_session.refresh(user)
    assert user.is_superuser is False


def test_reactivate_user_only_acts_on_inactive(db_session: Session) -> None:
    inactive = make_user(db_session, is_active=False)
    active = make_user(db_session, is_active=True)
    db_session.flush()

    assert user_service.reactivate_user(db_session, user_id=inactive.id) is True
    db_session.refresh(inactive)
    assert inactive.is_active is True

    # Idempotent: already-active user returns False (no-op)
    assert user_service.reactivate_user(db_session, user_id=active.id) is False
