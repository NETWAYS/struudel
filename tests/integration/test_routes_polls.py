import json
from datetime import UTC, datetime, timedelta

from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from struudel.models.poll import Poll, PollResponseMode, PollStatus, PollVisibility
from struudel.models.poll_option import PollOption, PollOptionType
from struudel.models.poll_response import PollResponseStatus
from struudel.services import poll as poll_service
from tests.conftest import login_as, make_user


def _make_active_poll(
    db: Session,
    *,
    owner_id: int,
    visibility: PollVisibility = PollVisibility.PUBLIC,
    allow_edit_responses: bool = True,
    edit_responses_until: datetime | None = None,
) -> Poll:
    poll = Poll(
        title="Route Test",
        status=PollStatus.ACTIVE,
        visibility=visibility,
        response_mode=PollResponseMode.YES_NO_MAYBE,
        allow_edit_responses=allow_edit_responses,
        edit_responses_until=edit_responses_until,
        attributes={"auto_delete": False},
        created_by_id=owner_id,
    )
    db.add(poll)
    db.flush()
    for idx, label in enumerate(["A", "B"]):
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
# GET /polls/<id>/vote
# ---------------------------------------------------------------------------


def test_vote_get_renders_for_authorized_user(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    poll = _make_active_poll(db_session, owner_id=owner.id)
    login_as(client, owner)

    resp = client.get(f"/polls/{poll.id}/vote")
    assert resp.status_code == 200


def test_vote_get_403_for_outsider_on_private(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    other = make_user(db_session, email="other@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id, visibility=PollVisibility.PRIVATE)
    login_as(client, other)

    resp = client.get(f"/polls/{poll.id}/vote")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /polls/<id>/vote
# ---------------------------------------------------------------------------


def test_vote_post_persists_response(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="voter@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id)
    opt_a, opt_b = poll.options
    login_as(client, voter)

    payload = {
        "comment": "tasty",
        "votes": json.dumps(
            [
                {"option_id": opt_a.id, "status": "YES"},
                {"option_id": opt_b.id, "status": "NO"},
            ]
        ),
    }
    resp = client.post(f"/polls/{poll.id}/vote", data=payload)
    assert resp.status_code == 302

    response = poll_service.get_user_response(db_session, poll_id=poll.id, user_id=voter.id)
    assert response is not None
    assert response.comment == "tasty"
    assert {ov.option_id: ov.status for ov in response.option_votes} == {
        opt_a.id: PollResponseStatus.YES,
        opt_b.id: PollResponseStatus.NO,
    }


# ---------------------------------------------------------------------------
# POST /polls/<id>/vote/withdraw
# ---------------------------------------------------------------------------


def test_vote_withdraw_removes_response(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="voter@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id)
    opt_a, _ = poll.options
    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment=None,
    )
    login_as(client, voter)

    resp = client.post(f"/polls/{poll.id}/vote/withdraw")
    assert resp.status_code == 302
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 0


def test_vote_withdraw_idempotent_when_no_response(
    db_session: Session, client: FlaskClient
) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="voter@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id)
    login_as(client, voter)

    resp = client.post(f"/polls/{poll.id}/vote/withdraw")
    assert resp.status_code == 302


def test_vote_post_409_when_editing_disabled_and_existing(
    db_session: Session, client: FlaskClient
) -> None:
    """Active poll without allow_edit_responses: voter cannot overwrite via re-submit."""
    owner = make_user(db_session)
    voter = make_user(db_session, email="voter@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id, allow_edit_responses=False)
    opt_a, _ = poll.options
    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment="locked",
    )
    login_as(client, voter)

    payload = {
        "comment": "changed",
        "votes": json.dumps([{"option_id": opt_a.id, "status": "NO"}]),
    }
    resp = client.post(f"/polls/{poll.id}/vote", data=payload)
    assert resp.status_code == 409

    response = poll_service.get_user_response(db_session, poll_id=poll.id, user_id=voter.id)
    assert response is not None
    assert response.comment == "locked"


def test_vote_withdraw_409_when_editing_disabled(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="voter@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id, allow_edit_responses=False)
    opt_a, _ = poll.options
    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment=None,
    )
    login_as(client, voter)

    resp = client.post(f"/polls/{poll.id}/vote/withdraw")
    assert resp.status_code == 409
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 1


def test_vote_withdraw_409_outside_edit_window(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="voter@test.local")
    past = datetime.now(UTC) - timedelta(hours=1)
    poll = _make_active_poll(
        db_session,
        owner_id=owner.id,
        allow_edit_responses=True,
        edit_responses_until=past,
    )
    poll.ends_at = past
    db_session.flush()
    opt_a, _ = poll.options
    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment=None,
    )
    login_as(client, voter)

    resp = client.post(f"/polls/{poll.id}/vote/withdraw")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /polls/<id>/responses/clear
# ---------------------------------------------------------------------------


def test_responses_clear_owner_can_reset(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="voter@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id)
    opt_a, _ = poll.options
    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment=None,
    )
    login_as(client, owner)

    resp = client.post(f"/polls/{poll.id}/responses/clear")
    assert resp.status_code == 302
    assert poll_service.count_responses(db_session, poll_id=poll.id) == 0


def test_responses_clear_non_owner_403(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    other = make_user(db_session, email="other@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id)
    login_as(client, other)

    resp = client.post(f"/polls/{poll.id}/responses/clear")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /polls/<id>/share/regenerate
# ---------------------------------------------------------------------------


def test_share_regenerate_owner_rotates_token(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    poll = _make_active_poll(db_session, owner_id=owner.id)
    old_token = poll.share_token
    login_as(client, owner)

    resp = client.post(f"/polls/{poll.id}/share/regenerate")
    assert resp.status_code == 302
    db_session.refresh(poll)
    assert poll.share_token != old_token


def test_share_regenerate_non_owner_403(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    other = make_user(db_session, email="other@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id)
    login_as(client, other)

    resp = client.post(f"/polls/{poll.id}/share/regenerate")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /polls/<id>/edit — confirm_destructive gate
# ---------------------------------------------------------------------------


def _edit_form_payload(poll: Poll, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": poll.title,
        "status": poll.status.value,
        "visibility": poll.visibility.value,
        "response_mode": poll.response_mode.value,
        "options": json.dumps([{"type": "TEXT", "text_value": o.text_value} for o in poll.options]),
    }
    payload.update(overrides)
    return payload


def test_edit_with_responses_requires_confirm(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="voter@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id)
    opt_a, _ = poll.options
    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment=None,
    )
    login_as(client, owner)

    resp = client.post(f"/polls/{poll.id}/edit", data=_edit_form_payload(poll))
    assert resp.status_code == 200
    assert b"already submitted" in resp.data


def test_edit_with_confirm_destructive_proceeds(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    voter = make_user(db_session, email="voter@test.local")
    poll = _make_active_poll(db_session, owner_id=owner.id)
    opt_a, _ = poll.options
    poll_service.submit_response(
        db_session,
        poll=poll,
        user_id=voter.id,
        votes={opt_a.id: PollResponseStatus.YES},
        comment=None,
    )
    login_as(client, owner)

    resp = client.post(
        f"/polls/{poll.id}/edit",
        data=_edit_form_payload(poll, confirm_destructive="1", title="Renamed"),
    )
    assert resp.status_code == 302
    db_session.refresh(poll)
    assert poll.title == "Renamed"


def test_edit_without_responses_no_warning(db_session: Session, client: FlaskClient) -> None:
    owner = make_user(db_session)
    poll = _make_active_poll(db_session, owner_id=owner.id)
    login_as(client, owner)

    resp = client.post(f"/polls/{poll.id}/edit", data=_edit_form_payload(poll, title="Renamed"))
    assert resp.status_code == 302
