import json
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from struudel.blueprints.polls.forms import PollForm
from struudel.models.group import Group
from struudel.models.poll import (
    Poll,
    PollResponseMode,
    PollStatus,
    PollVisibility,
)
from struudel.models.poll_option import PollOption, PollOptionGroup, PollOptionType
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


def test_guard_can_edit_with_allow_edit_set(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        allow_edit_responses=True,
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


# ---------------------------------------------------------------------------
# PrivateRequiresAudienceError — guards against unreachable PRIVATE polls
# ---------------------------------------------------------------------------


def _private_active_form() -> PollForm:
    return PollForm.model_validate(
        {
            "title": "Spaghettieis",
            "status": "ACTIVE",
            "visibility": "PRIVATE",
            "options": json.dumps([{"type": "TEXT", "text_value": "Yes"}]),
        }
    )


def test_create_poll_private_active_raises_without_audience(db_session: Session) -> None:
    owner = make_user(db_session)
    with pytest.raises(poll_service.PrivateRequiresAudienceError):
        poll_service.create_poll(db_session, form=_private_active_form(), created_by_id=owner.id)


def test_update_poll_blocks_activation_of_private_without_audience(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        status=PollStatus.DRAFT,
        visibility=PollVisibility.PRIVATE,
    )

    with pytest.raises(poll_service.PrivateRequiresAudienceError):
        poll_service.update_poll(db_session, poll=poll, form=_private_active_form())


def test_update_poll_allows_activation_of_private_with_audience(db_session: Session) -> None:
    owner = make_user(db_session)
    invitee = make_user(db_session)
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        status=PollStatus.DRAFT,
        visibility=PollVisibility.PRIVATE,
    )
    poll_service.set_poll_audience(db_session, poll=poll, users=[invitee.id], groups=[])

    poll_service.update_poll(db_session, poll=poll, form=_private_active_form())
    assert poll.status == PollStatus.ACTIVE


def test_set_poll_audience_rejects_empty_for_active_private(db_session: Session) -> None:
    owner = make_user(db_session)
    invitee = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PRIVATE)
    poll_service.set_poll_audience(db_session, poll=poll, users=[invitee.id], groups=[])

    with pytest.raises(poll_service.PrivateRequiresAudienceError):
        poll_service.set_poll_audience(db_session, poll=poll, users=[], groups=[])


def test_set_poll_audience_allows_empty_for_draft_private(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        status=PollStatus.DRAFT,
        visibility=PollVisibility.PRIVATE,
    )
    # Should not raise — DRAFT can have empty audience.
    poll_service.set_poll_audience(db_session, poll=poll, users=[], groups=[])


def test_set_poll_audience_allows_empty_for_active_public(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    # PUBLIC polls ignore the audience for access control — empty is fine.
    poll_service.set_poll_audience(db_session, poll=poll, users=[], groups=[])


def test_create_poll_private_draft_ok(db_session: Session) -> None:
    owner = make_user(db_session)
    form = PollForm.model_validate(
        {
            "title": "Draft",
            "status": "DRAFT",
            "visibility": "PRIVATE",
            "options": json.dumps([{"type": "TEXT", "text_value": "Yes"}]),
        }
    )
    poll = poll_service.create_poll(db_session, form=form, created_by_id=owner.id)
    assert poll.status == PollStatus.DRAFT


def test_create_poll_public_active_ok_without_audience(db_session: Session) -> None:
    owner = make_user(db_session)
    form = PollForm.model_validate(
        {
            "title": "Public",
            "status": "ACTIVE",
            "visibility": "PUBLIC",
            "options": json.dumps([{"type": "TEXT", "text_value": "Yes"}]),
        }
    )
    poll = poll_service.create_poll(db_session, form=form, created_by_id=owner.id)
    assert poll.status == PollStatus.ACTIVE


# ---------------------------------------------------------------------------
# Forward-only status lifecycle
# ---------------------------------------------------------------------------


def _form_with_status(status: str) -> PollForm:
    return PollForm.model_validate(
        {
            "title": "T",
            "status": status,
            "visibility": "PUBLIC",
            "options": json.dumps([{"type": "TEXT", "text_value": "Yes"}]),
        }
    )


def test_create_poll_rejects_closed_status(db_session: Session) -> None:
    owner = make_user(db_session)
    with pytest.raises(poll_service.InvalidStatusTransitionError):
        poll_service.create_poll(
            db_session, form=_form_with_status("CLOSED"), created_by_id=owner.id
        )


def test_update_poll_rejects_active_to_draft(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        status=PollStatus.ACTIVE,
        visibility=PollVisibility.PUBLIC,
    )
    with pytest.raises(poll_service.InvalidStatusTransitionError):
        poll_service.update_poll(db_session, poll=poll, form=_form_with_status("DRAFT"))


def test_update_poll_rejects_draft_to_closed(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        status=PollStatus.DRAFT,
        visibility=PollVisibility.PUBLIC,
    )
    with pytest.raises(poll_service.InvalidStatusTransitionError):
        poll_service.update_poll(db_session, poll=poll, form=_form_with_status("CLOSED"))


def test_update_poll_rejects_closed_reopen(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        status=PollStatus.CLOSED,
        visibility=PollVisibility.PUBLIC,
    )
    with pytest.raises(poll_service.InvalidStatusTransitionError):
        poll_service.update_poll(db_session, poll=poll, form=_form_with_status("ACTIVE"))


def test_update_poll_allows_active_to_closed(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        status=PollStatus.ACTIVE,
        visibility=PollVisibility.PUBLIC,
    )
    poll_service.update_poll(db_session, poll=poll, form=_form_with_status("CLOSED"))
    assert poll.status == PollStatus.CLOSED


def test_draft_to_active_with_inline_audience_invites_each_user_once(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: activating a DRAFT poll while adding audience in the same
    update_poll() call previously triggered two send_invitation_task calls per
    user — once from set_poll_audience (because poll.status was already
    flipped to ACTIVE) and once from _dispatch_activation_invitations.
    """
    sent: list[tuple[int, int]] = []

    def fake_send(poll_id: int, user_id: int) -> None:
        sent.append((poll_id, user_id))

    monkeypatch.setattr("struudel.tasks.mail.send_invitation.send_invitation_task", fake_send)
    # The invitation lock lives in Redis; clear/claim deterministically.
    monkeypatch.setattr("struudel.mail.try_claim_invitation_lock", lambda poll_id: True)

    owner = make_user(db_session)
    invitee = make_user(db_session, email="invitee@test.local")
    poll = _make_poll(
        db_session,
        owner_id=owner.id,
        status=PollStatus.DRAFT,
        visibility=PollVisibility.PRIVATE,
    )

    poll_service.update_poll(
        db_session,
        poll=poll,
        form=_private_active_form(),
        audience_user_ids=[invitee.id],
        audience_group_ids=[],
    )

    assert poll.status == PollStatus.ACTIVE
    assert sent.count((poll.id, invitee.id)) == 1


# ---------------------------------------------------------------------------
# Option groups — per-group selection caps
# ---------------------------------------------------------------------------


def _group_options(
    db: Session, *, poll: Poll, options: list[PollOption], max_selections: int | None
) -> PollOptionGroup:
    group = PollOptionGroup(poll_id=poll.id, name="G", max_selections=max_selections)
    db.add(group)
    db.flush()
    for o in options:
        o.group_id = group.id
    db.flush()
    return group


def _grouped_form(*, group_key: str, max_selections: int | None) -> PollForm:
    return PollForm.model_validate(
        {
            "title": "Spaghettieis",
            "options": json.dumps(
                [
                    {"type": "TEXT", "text_value": "A", "group_client_key": group_key},
                    {"type": "TEXT", "text_value": "B", "group_client_key": group_key},
                ]
            ),
            "groups": json.dumps(
                [{"client_key": group_key, "name": "G", "max_selections": max_selections}]
            ),
        }
    )


def test_submit_response_group_cap_rejects_too_many_yes(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    opt_a, opt_b = poll.options
    _group_options(db_session, poll=poll, options=[opt_a, opt_b], max_selections=1)

    with pytest.raises(poll_service.InvalidVoteError):
        poll_service.submit_response(
            db_session,
            poll=poll,
            user_id=voter.id,
            votes={opt_a.id: PollResponseStatus.YES, opt_b.id: PollResponseStatus.YES},
            comment=None,
        )


def test_submit_response_group_cap_ignores_maybe(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    opt_a, opt_b = poll.options
    _group_options(db_session, poll=poll, options=[opt_a, opt_b], max_selections=1)

    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES, opt_b.id: PollResponseStatus.MAYBE},
        comment=None,
    )
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 1


def test_submit_response_ungrouped_options_are_uncapped(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session)
    poll = _make_poll(
        db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC, options=["A", "B", "C"]
    )
    opt_a, opt_b, opt_c = poll.options
    _group_options(db_session, poll=poll, options=[opt_a], max_selections=1)

    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={
            opt_a.id: PollResponseStatus.YES,
            opt_b.id: PollResponseStatus.YES,
            opt_c.id: PollResponseStatus.YES,
        },
        comment=None,
    )
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 1


def test_submit_response_group_without_max_is_unlimited(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PUBLIC)
    opt_a, opt_b = poll.options
    _group_options(db_session, poll=poll, options=[opt_a, opt_b], max_selections=None)

    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES, opt_b.id: PollResponseStatus.YES},
        comment=None,
    )
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 1


def test_update_poll_keeps_group_id_and_changes_cap(db_session: Session) -> None:
    owner = make_user(db_session)
    poll = poll_service.create_poll(
        db_session, form=_grouped_form(group_key="new-x", max_selections=1), created_by_id=owner.id
    )
    (group,) = poll.option_groups
    group_id = group.id

    poll_service.update_poll(
        db_session, poll=poll, form=_grouped_form(group_key=str(group_id), max_selections=2)
    )

    (group,) = poll.option_groups
    assert group.id == group_id
    assert group.max_selections == 2
    assert {o.group_id for o in poll.options} == {group_id}


def test_update_poll_removing_group_ungroups_options_and_keeps_votes(db_session: Session) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session)
    poll = poll_service.create_poll(
        db_session, form=_grouped_form(group_key="new-x", max_selections=1), created_by_id=owner.id
    )
    opt_a, opt_b = poll.options
    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment=None,
    )
    ungrouped_form = PollForm.model_validate(
        {
            "title": "Spaghettieis",
            "options": json.dumps(
                [{"type": "TEXT", "text_value": "A"}, {"type": "TEXT", "text_value": "B"}]
            ),
        }
    )

    poll_service.update_poll(db_session, poll=poll, form=ungrouped_form)

    assert poll.option_groups == []
    assert [(o.id, o.group_id) for o in poll.options] == [(opt_a.id, None), (opt_b.id, None)]
    response = poll_service.get_user_response(db_session, poll_id=poll.id, user_id=voter.id)
    assert response is not None
    assert {ov.option_id for ov in response.option_votes} == {opt_a.id}


def test_deleting_group_row_sets_option_group_id_null(db_session: Session) -> None:
    """The migration's ON DELETE SET NULL, independent of _apply_options."""
    owner = make_user(db_session)
    poll = _make_poll(db_session, owner_id=owner.id)
    opt_a, _ = poll.options
    group = _group_options(db_session, poll=poll, options=[opt_a], max_selections=1)

    db_session.execute(sa.delete(PollOptionGroup).where(PollOptionGroup.id == group.id))
    db_session.refresh(opt_a)

    assert opt_a.group_id is None


def test_create_poll_treats_non_ascii_digit_group_key_as_new(db_session: Session) -> None:
    owner = make_user(db_session)
    form = PollForm.model_validate(
        {
            "title": "Spaghettieis",
            "options": json.dumps(
                [{"type": "TEXT", "text_value": "Yes", "group_client_key": "²"}]
            ),
            "groups": json.dumps([{"client_key": "²", "name": "G", "max_selections": 1}]),
        }
    )

    poll = poll_service.create_poll(db_session, form=form, created_by_id=owner.id)

    assert [g.name for g in poll.option_groups] == ["G"]
    assert poll.options[0].group_id == poll.option_groups[0].id
