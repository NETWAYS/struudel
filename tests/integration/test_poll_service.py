from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy.orm import Session

from struudel.models.group import Group
from struudel.models.poll import (
    Poll,
    PollResponseMode,
    PollStatus,
    PollVisibility,
)
from struudel.models.poll_option import PollOption, PollOptionType
from struudel.models.poll_response import PollResponseStatus
from struudel.services import poll as poll_service
from tests.conftest import make_user


def _make_poll(
    db: Session,
    *,
    owner_id: int,
    status: PollStatus = PollStatus.ACTIVE,
    visibility: PollVisibility = PollVisibility.PRIVATE,
    response_mode: PollResponseMode = PollResponseMode.YES_NO_MAYBE,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    allow_edit_responses: bool = False,
    edit_responses_until: datetime | None = None,
    auto_delete: bool = False,
    options: list[str] | None = None,
) -> Poll:
    poll = Poll(
        title="Poll",
        status=status,
        visibility=visibility,
        response_mode=response_mode,
        starts_at=starts_at,
        ends_at=ends_at,
        allow_edit_responses=allow_edit_responses,
        edit_responses_until=edit_responses_until,
        attributes={"auto_delete": auto_delete},
        created_by_id=owner_id,
    )
    db.add(poll)
    db.flush()
    for idx, label in enumerate(options or ["A", "B"]):
        db.add(
            PollOption(
                poll_id=poll.id,
                option_type=PollOptionType.TEXT,
                sort_order=idx,
                is_custom=False,
                text_value=label,
            )
        )
    db.flush()
    db.refresh(poll)
    return poll


# ---------------------------------------------------------------------------
# user_can_view_poll
# ---------------------------------------------------------------------------


def test_owner_always_views_own_poll(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PRIVATE)
    assert poll_service.user_can_view_poll(db_session, poll=poll, user_id=owner.id) is True


def test_public_poll_viewable_by_any_user(db_session: Session) -> None:
    owner = make_user(db_session)
    other = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    assert poll_service.user_can_view_poll(db_session, poll=poll, user_id=other.id) is True


def test_private_poll_blocks_outsider(db_session: Session) -> None:
    owner = make_user(db_session)
    other = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PRIVATE)
    assert poll_service.user_can_view_poll(db_session, poll=poll, user_id=other.id) is False


def test_template_status_never_viewable(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, status=PollStatus.TEMPLATE)
    assert poll_service.user_can_view_poll(db_session, poll=poll, user_id=owner.id) is False


# ---------------------------------------------------------------------------
# user_can_vote_on_poll / VoteGuard
# ---------------------------------------------------------------------------


def test_guard_active_within_window(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, status=PollStatus.ACTIVE)
    guard = poll_service.user_can_vote_on_poll(poll, now=datetime.now(UTC))
    assert guard.can_vote is True
    assert guard.reason is None


def test_guard_draft_is_not_active(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, status=PollStatus.DRAFT)
    guard = poll_service.user_can_vote_on_poll(poll, now=datetime.now(UTC))
    assert guard.can_vote is False
    assert guard.reason == "not_active"


def test_guard_not_started(db_session: Session) -> None:
    owner = make_user(db_session)
    future = datetime.now(UTC) + timedelta(hours=1)
    poll = _make_poll(db_session, owner_id=owner.id, starts_at=future)
    guard = poll_service.user_can_vote_on_poll(poll, now=datetime.now(UTC))
    assert guard.can_vote is False
    assert guard.reason == "not_started"


def test_guard_closed_after_ends_at(db_session: Session) -> None:
    owner = make_user(db_session)
    past = datetime.now(UTC) - timedelta(hours=1)
    poll = _make_poll(db_session, owner_id=owner.id, ends_at=past)
    guard = poll_service.user_can_vote_on_poll(poll, now=datetime.now(UTC))
    assert guard.can_vote is False
    assert guard.reason == "closed"


def test_guard_can_edit_with_open_window(db_session: Session) -> None:
    owner = make_user(db_session)
    future = datetime.now(UTC) + timedelta(hours=1)
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        allow_edit_responses=True,
        edit_responses_until=future,
    )
    guard = poll_service.user_can_vote_on_poll(poll, now=datetime.now(UTC))
    assert guard.can_edit is True


# ---------------------------------------------------------------------------
# submit_response — idempotent upsert
# ---------------------------------------------------------------------------


def test_submit_response_creates_one_row(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="v@test.local")
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    opt_a, opt_b = poll.options

    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES, opt_b.id: PollResponseStatus.NO},
        comment="first",
    )
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 1


def test_submit_response_overwrites_existing(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="v@test.local")
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    opt_a, opt_b = poll.options

    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment="first",
    )
    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_b.id: PollResponseStatus.YES},
        comment="second",
    )

    assert poll_service.count_responses(db_session, poll_id=poll.id) == 1
    response = poll_service.get_user_response(db_session, poll_id=poll.id, user_id=voter.id)
    assert response is not None
    assert response.comment == "second"
    assert {ov.option_id: ov.status for ov in response.option_votes} == {
        opt_b.id: PollResponseStatus.YES
    }


def test_submit_response_drops_stale_option_ids(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="v@test.local")
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    opt_a, _ = poll.options

    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES, 99999: PollResponseStatus.YES},
        comment=None,
    )
    response = poll_service.get_user_response(db_session, poll_id=poll.id, user_id=voter.id)
    assert response is not None
    assert {ov.option_id for ov in response.option_votes} == {opt_a.id}


def test_submit_response_single_choice_rejects_multiple_yes(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="v@test.local")
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        response_mode=PollResponseMode.SINGLE_CHOICE,
        visibility=PollVisibility.PUBLIC,
    )
    opt_a, opt_b = poll.options
    with pytest.raises(poll_service.InvalidVoteError):
        poll_service.submit_response(
            db_session,
            poll=poll,
            user_id=voter.id,
            votes={opt_a.id: PollResponseStatus.YES, opt_b.id: PollResponseStatus.YES},
            comment=None,
        )


# ---------------------------------------------------------------------------
# delete_user_response, clear_responses, count_responses
# ---------------------------------------------------------------------------


def test_delete_user_response_returns_false_when_absent(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="v@test.local")
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    assert poll_service.delete_user_response(db_session, poll_id=poll.id, user_id=voter.id) is False


def test_delete_user_response_cascades_option_votes(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="v@test.local")
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    opt_a, _ = poll.options

    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment=None,
    )
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 1

    deleted = poll_service.delete_user_response(db_session, poll_id=poll.id, user_id=voter.id)
    assert deleted is True
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 0


def test_clear_responses_returns_count(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    opt_a, _ = poll.options

    for i in range(3):
        voter = make_user(db_session, email=f"v{i}@test.local")
        poll_service.submit_response(
            db_session,
            poll=poll,
            user_id=voter.id,
            votes={opt_a.id: PollResponseStatus.YES},
            comment=None,
        )

    cleared = poll_service.clear_responses(db_session, poll=poll)
    assert cleared == 3
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 0


# ---------------------------------------------------------------------------
# close_due_polls
# ---------------------------------------------------------------------------


def test_close_due_polls_transitions_active_past_ends_at(db_session: Session) -> None:
    owner = make_user(db_session)
    past = datetime.now(UTC) - timedelta(hours=1)
    poll = _make_poll(db_session, owner_id=owner.id, ends_at=past, auto_delete=True)

    closed = poll_service.close_due_polls(db_session)
    assert closed == 1
    db_session.refresh(poll)
    assert poll.status == PollStatus.CLOSED
    assert poll.auto_delete_at is not None


def test_close_due_polls_skips_future_ends_at(db_session: Session) -> None:
    owner = make_user(db_session)
    future = datetime.now(UTC) + timedelta(hours=1)
    poll = _make_poll(db_session, owner_id=owner.id, ends_at=future)

    closed = poll_service.close_due_polls(db_session)
    assert closed == 0
    db_session.refresh(poll)
    assert poll.status == PollStatus.ACTIVE


def test_close_due_polls_skips_polls_without_ends_at(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, ends_at=None)

    closed = poll_service.close_due_polls(db_session)
    assert closed == 0
    db_session.refresh(poll)
    assert poll.status == PollStatus.ACTIVE


# ---------------------------------------------------------------------------
# purge_expired_polls
# ---------------------------------------------------------------------------


def test_purge_expired_polls_removes_due(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, status=PollStatus.CLOSED)
    poll.auto_delete_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    purged = poll_service.purge_expired_polls(db_session)
    assert purged == 1
    assert db_session.get(Poll, poll.id) is None


def test_purge_expired_polls_skips_future(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, status=PollStatus.CLOSED)
    poll.auto_delete_at = datetime.now(UTC) + timedelta(days=1)
    db_session.flush()

    purged = poll_service.purge_expired_polls(db_session)
    assert purged == 0
    assert db_session.get(Poll, poll.id) is not None


# ---------------------------------------------------------------------------
# regenerate_share_token
# ---------------------------------------------------------------------------


def test_regenerate_share_token_changes_value(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id)
    old = poll.share_token

    new = poll_service.regenerate_share_token(db_session, poll=poll)
    assert new != old
    assert poll.share_token == new


# ---------------------------------------------------------------------------
# search_audience_candidates — hidden groups must not appear
# ---------------------------------------------------------------------------


def test_search_audience_candidates_excludes_hidden_groups(db_session: Session) -> None:
    visible = Group(canonical_name="visible-team", name="Visible Team")
    hidden = Group(canonical_name="hidden-team", name="Hidden Team", hidden=True)
    db_session.add_all([visible, hidden])
    db_session.flush()

    results = cast(
        "list[Group]",
        poll_service.search_audience_candidates(db_session, query="team", kind="group"),
    )
    names = [g.canonical_name for g in results]

    assert "visible-team" in names
    assert "hidden-team" not in names
