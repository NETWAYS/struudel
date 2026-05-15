"""Tests for the admin-facing poll search service.

Covers `search_polls`:
- Title ILIKE filter
- Creator-name / creator-username ILIKE filter (via `Poll.created_by.has`)
- Status filter
- Combined filters (AND-semantics)
- Pagination + page clamping
"""

import pytest
from sqlalchemy.orm import Session

from struudel.models.poll import Poll, PollResponseMode, PollStatus, PollVisibility
from struudel.services import poll as poll_service
from tests.conftest import make_user


def _make_poll(
    db: Session,
    *,
    owner_id: int,
    title: str = "Poll",
    status: PollStatus = PollStatus.ACTIVE,
    visibility: PollVisibility = PollVisibility.PRIVATE,
) -> Poll:
    poll = Poll(
        title=title,
        status=status,
        visibility=visibility,
        response_mode=PollResponseMode.YES_NO_MAYBE,
        attributes={},
        created_by_id=owner_id,
    )
    db.add(poll)
    db.flush()
    return poll


# ---------------------------------------------------------------------------
# Title filter
# ---------------------------------------------------------------------------


def test_search_polls_filters_by_title(db_session: Session) -> None:
    owner = make_user(db_session)
    a = _make_poll(db_session, owner_id=owner.id, title="Lunch poll")
    _make_poll(db_session, owner_id=owner.id, title="Sprint planning")
    db_session.flush()

    found, total, _ = poll_service.search_polls(db_session, title_query="lunch")

    assert total == 1
    assert found[0].id == a.id


# ---------------------------------------------------------------------------
# Creator filter
# ---------------------------------------------------------------------------


def test_search_polls_filters_by_creator_name(db_session: Session) -> None:
    alice = make_user(db_session, name="Alice Anderson")
    bob = make_user(db_session, name="Bob Brown")
    a = _make_poll(db_session, owner_id=alice.id, title="A1")
    _make_poll(db_session, owner_id=bob.id, title="B1")
    db_session.flush()

    found, total, _ = poll_service.search_polls(db_session, creator_query="alice")

    assert total == 1
    assert found[0].id == a.id


def test_search_polls_filters_by_creator_preferred_username(db_session: Session) -> None:
    alice = make_user(db_session, name="Alice")
    bob = make_user(db_session, name="Bob")
    a = _make_poll(db_session, owner_id=alice.id, title="A1")
    _make_poll(db_session, owner_id=bob.id, title="B1")
    db_session.flush()

    found, total, _ = poll_service.search_polls(db_session, creator_query=alice.preferred_username)

    assert total == 1
    assert found[0].id == a.id


# ---------------------------------------------------------------------------
# Status filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [PollStatus.DRAFT, PollStatus.ACTIVE, PollStatus.CLOSED, PollStatus.TEMPLATE],
)
def test_search_polls_filters_by_status(db_session: Session, status: PollStatus) -> None:
    owner = make_user(db_session)
    target = _make_poll(db_session, owner_id=owner.id, title="X", status=status)
    # Add one poll of every *other* status as noise
    for other in (
        PollStatus.DRAFT,
        PollStatus.ACTIVE,
        PollStatus.CLOSED,
        PollStatus.TEMPLATE,
    ):
        if other == status:
            continue
        _make_poll(db_session, owner_id=owner.id, title="noise", status=other)
    db_session.flush()

    found, total, _ = poll_service.search_polls(db_session, status=status)

    assert total == 1
    assert found[0].id == target.id
    assert all(p.status == status for p in found)


# ---------------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------------


def test_search_polls_combines_title_creator_status(db_session: Session) -> None:
    alice = make_user(db_session, name="Alice")
    bob = make_user(db_session, name="Bob")
    # Match: title "Lunch", creator Alice, status ACTIVE
    target = _make_poll(db_session, owner_id=alice.id, title="Lunch meet", status=PollStatus.ACTIVE)
    # Same title, different creator
    _make_poll(db_session, owner_id=bob.id, title="Lunch meet", status=PollStatus.ACTIVE)
    # Same creator, different status
    _make_poll(db_session, owner_id=alice.id, title="Lunch meet", status=PollStatus.DRAFT)
    # Same creator+status, different title
    _make_poll(db_session, owner_id=alice.id, title="Dinner meet", status=PollStatus.ACTIVE)
    db_session.flush()

    found, total, _ = poll_service.search_polls(
        db_session,
        title_query="lunch",
        creator_query="alice",
        status=PollStatus.ACTIVE,
    )

    assert total == 1
    assert found[0].id == target.id


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_search_polls_paginates(db_session: Session) -> None:
    owner = make_user(db_session)
    for i in range(7):
        _make_poll(db_session, owner_id=owner.id, title=f"Poll {i}")
    db_session.flush()

    page1, total, p1 = poll_service.search_polls(db_session, page=1, per_page=3)
    page2, _, p2 = poll_service.search_polls(db_session, page=2, per_page=3)
    page3, _, p3 = poll_service.search_polls(db_session, page=3, per_page=3)

    assert total == 7
    assert (p1, p2, p3) == (1, 2, 3)
    assert (len(page1), len(page2), len(page3)) == (3, 3, 1)
    ids = {p.id for p in page1} | {p.id for p in page2} | {p.id for p in page3}
    assert len(ids) == 7


def test_search_polls_clamps_page_beyond_total(db_session: Session) -> None:
    owner = make_user(db_session)
    for _ in range(3):
        _make_poll(db_session, owner_id=owner.id)
    db_session.flush()

    found, total, effective_page = poll_service.search_polls(db_session, page=999, per_page=20)

    assert total == 3
    assert effective_page == 1
    assert len(found) == 3
