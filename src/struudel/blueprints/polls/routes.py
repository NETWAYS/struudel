from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal, cast
from uuid import UUID

from flask import abort, flash, g, redirect, render_template, request, url_for
from pydantic import ValidationError
from werkzeug.wrappers import Response

from struudel.auth import require_auth
from struudel.blueprints.polls import bp
from struudel.blueprints.polls.forms import AudienceForm, PollForm, PollOptionData, VoteForm
from struudel.database import SessionLocal
from struudel.models.poll import Poll, PollStatus
from struudel.models.poll_option import PollOption, PollOptionType
from struudel.models.poll_response import PollResponse
from struudel.services import poll as poll_service
from struudel.services.poll import InvalidVoteError, VoteGuard
from struudel.timezones import to_local

log = logging.getLogger(__name__)


@bp.route("/")
@require_auth
def my() -> str:
    with SessionLocal() as db:
        polls = poll_service.list_my_polls(db, user_id=g.user["id"])
    return render_template("polls/my.html", polls=polls)


@bp.route("/participate")
@require_auth
def participate() -> str:
    with SessionLocal() as db:
        polls = poll_service.list_participating_polls(db, user_id=g.user["id"])
    return render_template("polls/participate.html", polls=polls)


@bp.route("/public")
@require_auth
def public() -> str:
    with SessionLocal() as db:
        polls = poll_service.list_public_polls(db)
    return render_template("polls/public.html", polls=polls)


@bp.route("/<int:poll_id>")
@require_auth
def detail(poll_id: int) -> str | Response:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None or poll.status == PollStatus.TEMPLATE:
            abort(404)
        if not poll_service.user_can_view_poll(db, poll=poll, user_id=g.user["id"]):
            abort(403)
        is_owner = poll.created_by_id == g.user["id"]
        if not is_owner:
            return redirect(url_for("polls.vote", poll_id=poll_id))
        options = list(poll.options)
        created_by_name = poll.created_by.name or poll.created_by.preferred_username
        response_count = poll_service.count_responses(db, poll_id=poll.id)
        # Audience response status only meaningful on PRIVATE polls (PUBLIC has
        # no fixed audience — anyone authenticated can vote).
        if poll.visibility == "PRIVATE":
            responded, pending = poll_service.get_audience_response_status(db, poll=poll)
        else:
            responded, pending = [], []
    return render_template(
        "polls/detail.html",
        poll=poll,
        options=options,
        is_owner=is_owner,
        created_by_name=created_by_name,
        response_count=response_count,
        audience_responded=responded,
        audience_pending=pending,
    )


@bp.route("/s/<uuid:token>")
@require_auth
def share(token: UUID) -> Response:
    with SessionLocal() as db:
        poll = poll_service.get_poll_by_share_token(db, token=token)
        if poll is None or poll.status == PollStatus.TEMPLATE:
            abort(404)
        if not poll_service.user_can_view_poll(db, poll=poll, user_id=g.user["id"]):
            abort(403)
        poll_id = poll.id
    return redirect(url_for("polls.detail", poll_id=poll_id))


@bp.route("/new", methods=["GET", "POST"])
@require_auth
def new() -> str | Response | tuple[str, int]:
    if request.method == "GET":
        return render_template(
            "polls/edit.html",
            poll=None,
            form_data={},
            poll_options=[],
            errors=[],
        )

    try:
        form = PollForm.model_validate(dict(request.form))
    except ValidationError as exc:
        return (
            render_template(
                "polls/edit.html",
                poll=None,
                form_data=request.form,
                poll_options=_form_options_fallback(request.form.get("options", "")),
                errors=exc.errors(),
            ),
            400,
        )

    downgraded_to_draft = False
    if form.is_mandatory and form.status == PollStatus.ACTIVE:
        form = form.model_copy(update={"status": PollStatus.DRAFT})
        downgraded_to_draft = True

    with SessionLocal() as db:
        poll = poll_service.create_poll(db, form=form, created_by_id=g.user["id"])
        poll_id = poll.id

    if downgraded_to_draft:
        flash(
            "Saved as draft. Invite your audience here, then set status to Active in Edit.",
            "info",
        )
        return redirect(url_for("polls.audience", poll_id=poll_id))

    return redirect(url_for("polls.edit", poll_id=poll_id))


@bp.route("/<int:poll_id>/edit", methods=["GET", "POST"])
@require_auth
def edit(poll_id: int) -> str | Response | tuple[str, int]:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None:
            abort(404)
        if poll.created_by_id != g.user["id"]:
            abort(403)

        if request.method == "GET":
            return render_template(
                "polls/edit.html",
                poll=poll,
                form_data=_poll_to_form_data(poll),
                poll_options=_poll_options_to_dicts(poll.options),
                errors=[],
            )

        try:
            form = PollForm.model_validate(dict(request.form))
        except ValidationError as exc:
            return (
                render_template(
                    "polls/edit.html",
                    poll=poll,
                    form_data=request.form,
                    poll_options=_form_options_fallback(
                        request.form.get("options", ""),
                        fallback=_poll_options_to_dicts(poll.options),
                    ),
                    errors=exc.errors(),
                ),
                400,
            )

        response_count = poll_service.count_responses(db, poll_id=poll.id)
        if response_count > 0 and request.form.get("confirm_destructive") != "1":
            return render_template(
                "polls/edit.html",
                poll=poll,
                form_data=request.form,
                poll_options=_form_options_fallback(
                    request.form.get("options", ""),
                    fallback=_poll_options_to_dicts(poll.options),
                ),
                errors=[],
                destructive_warning={"response_count": response_count},
            )

        try:
            poll_service.update_poll(db, poll=poll, form=form)
        except poll_service.MandatoryRequiresAudienceError as exc:
            return (
                render_template(
                    "polls/edit.html",
                    poll=poll,
                    form_data=request.form,
                    poll_options=_form_options_fallback(
                        request.form.get("options", ""),
                        fallback=_poll_options_to_dicts(poll.options),
                    ),
                    errors=[{"loc": ("is_mandatory",), "msg": str(exc)}],
                ),
                400,
            )

    return redirect(url_for("polls.edit", poll_id=poll_id))


@bp.route("/<int:poll_id>/vote", methods=["GET", "POST"])
@require_auth
def vote(poll_id: int) -> str | Response | tuple[str, int]:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None or poll.status == PollStatus.TEMPLATE:
            abort(404)
        if not poll_service.user_can_view_poll(db, poll=poll, user_id=g.user["id"]):
            abort(403)

        now = datetime.now(UTC)
        guard = poll_service.user_can_vote_on_poll(poll, now=now)
        is_owner = poll.created_by_id == g.user["id"]

        if request.method == "POST":
            existing = poll_service.get_user_response(db, poll_id=poll.id, user_id=g.user["id"])
            has_existing = existing is not None
            allowed = (guard.can_vote and not has_existing) or (has_existing and guard.can_edit)
            if not allowed:
                abort(409)

            try:
                form = VoteForm.model_validate(dict(request.form))
            except ValidationError as exc:
                return _render_vote(
                    db,
                    poll=poll,
                    guard=guard,
                    is_owner=is_owner,
                    errors=exc.errors(),
                ), 400

            try:
                poll_service.submit_response(
                    db,
                    poll=poll,
                    user_id=g.user["id"],
                    votes={v.option_id: v.status for v in form.votes},
                    guest_counts={v.option_id: v.guest_count for v in form.votes},
                    comment=form.comment,
                )
            except InvalidVoteError as exc:
                return _render_vote(
                    db,
                    poll=poll,
                    guard=guard,
                    is_owner=is_owner,
                    errors=[{"loc": ("votes",), "msg": str(exc)}],
                ), 400

            return redirect(url_for("polls.vote", poll_id=poll_id))

        return _render_vote(db, poll=poll, guard=guard, is_owner=is_owner, errors=[])


@bp.route("/<int:poll_id>/vote/withdraw", methods=["POST"])
@require_auth
def vote_withdraw(poll_id: int) -> Response:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None or poll.status == PollStatus.TEMPLATE:
            abort(404)
        if not poll_service.user_can_view_poll(db, poll=poll, user_id=g.user["id"]):
            abort(403)

        existing = poll_service.get_user_response(db, poll_id=poll.id, user_id=g.user["id"])
        if existing is None:
            return redirect(url_for("polls.vote", poll_id=poll_id))

        guard = poll_service.user_can_vote_on_poll(poll, now=datetime.now(UTC))
        if not guard.can_edit:
            abort(409)

        poll_service.delete_user_response(db, poll_id=poll.id, user_id=g.user["id"])

    return redirect(url_for("polls.vote", poll_id=poll_id))


@bp.route("/<int:poll_id>/options/add", methods=["POST"])
@require_auth
def add_custom_option(poll_id: int) -> str | Response | tuple[str, int]:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None or poll.status == PollStatus.TEMPLATE:
            abort(404)
        if not poll_service.user_can_view_poll(db, poll=poll, user_id=g.user["id"]):
            abort(403)
        if not poll.allow_custom_options:
            abort(403)

        guard = poll_service.user_can_vote_on_poll(poll, now=datetime.now(UTC))
        is_owner = poll.created_by_id == g.user["id"]

        try:
            option = PollOptionData.model_validate(dict(request.form))
        except ValidationError as exc:
            return _render_vote(
                db, poll=poll, guard=guard, is_owner=is_owner, errors=exc.errors()
            ), 400

        try:
            poll_service.add_custom_option(db, poll=poll, user_id=g.user["id"], option=option)
        except poll_service.CustomOptionsDisabledError as exc:
            return _render_vote(
                db,
                poll=poll,
                guard=guard,
                is_owner=is_owner,
                errors=[{"loc": ("option",), "msg": str(exc)}],
            ), 409

    return redirect(url_for("polls.vote", poll_id=poll_id))


@bp.route("/<int:poll_id>/responses/clear", methods=["POST"])
@require_auth
def responses_clear(poll_id: int) -> Response:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None or poll.status == PollStatus.TEMPLATE:
            abort(404)
        if poll.created_by_id != g.user["id"]:
            abort(403)
        poll_service.clear_responses(db, poll=poll)

    return redirect(url_for("polls.detail", poll_id=poll_id))


@bp.route("/<int:poll_id>/share/regenerate", methods=["POST"])
@require_auth
def share_regenerate(poll_id: int) -> Response:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None or poll.status == PollStatus.TEMPLATE:
            abort(404)
        if poll.created_by_id != g.user["id"]:
            abort(403)
        poll_service.regenerate_share_token(db, poll=poll)

    return redirect(url_for("polls.detail", poll_id=poll_id))


@bp.route("/<int:poll_id>/delete", methods=["POST"])
@require_auth
def delete(poll_id: int) -> Response:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None:
            abort(404)
        if poll.created_by_id != g.user["id"]:
            abort(403)
        poll_service.delete_poll(db, poll=poll)

    return redirect(url_for("polls.my"))


@bp.route("/<int:poll_id>/audience", methods=["GET", "POST"])
@require_auth
def audience(poll_id: int) -> str | Response | tuple[str, int]:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None:
            abort(404)
        if poll.created_by_id != g.user["id"]:
            abort(403)

        if request.method == "GET":
            users, groups = poll_service.get_poll_audience(db, poll=poll)
            return render_template(
                "polls/audience.html",
                poll=poll,
                is_owner=True,
                initial_users=_audience_users_to_dicts(users),
                initial_groups=_audience_groups_to_dicts(groups),
                errors=[],
            )

        try:
            form = AudienceForm.model_validate(dict(request.form))
        except ValidationError as exc:
            users, groups = poll_service.get_poll_audience(db, poll=poll)
            return (
                render_template(
                    "polls/audience.html",
                    poll=poll,
                    is_owner=True,
                    initial_users=_audience_users_to_dicts(users),
                    initial_groups=_audience_groups_to_dicts(groups),
                    errors=exc.errors(),
                ),
                400,
            )

        try:
            poll_service.set_poll_audience(
                db,
                poll=poll,
                users=[m.id for m in form.users],
                groups=[m.id for m in form.groups],
            )
        except poll_service.MandatoryRequiresAudienceError as exc:
            users, groups = poll_service.get_poll_audience(db, poll=poll)
            return (
                render_template(
                    "polls/audience.html",
                    poll=poll,
                    is_owner=True,
                    initial_users=_audience_users_to_dicts(users),
                    initial_groups=_audience_groups_to_dicts(groups),
                    errors=[{"loc": ("audience",), "msg": str(exc)}],
                ),
                400,
            )

    return redirect(url_for("polls.audience", poll_id=poll_id))


@bp.route("/<int:poll_id>/audience/search")
@require_auth
def audience_search(poll_id: int) -> str | tuple[str, int]:
    q = (request.args.get("q") or "").strip()
    kind = request.args.get("kind", "user")

    if kind not in {"user", "group"}:
        abort(400)

    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None:
            abort(404)
        if poll.created_by_id != g.user["id"]:
            abort(403)

        if len(q) < 2:
            results: list[Any] = []
        else:
            kind_literal = cast(Literal["user", "group"], kind)
            results = list(poll_service.search_audience_candidates(db, query=q, kind=kind_literal))

    return render_template(
        "polls/_audience_search_results.html",
        kind=kind,
        query=q,
        results=results,
    )


def _poll_to_form_data(poll: Poll) -> dict[str, Any]:
    """Project a Poll onto the shape PollForm expects, driven by the form's
    declared fields. New PollForm columns are picked up automatically as
    long as they have a same-named attribute on Poll (or live in
    `attributes` JSONB and are special-cased here)."""
    data: dict[str, Any] = {}
    bool_attribute_defaults: dict[str, bool] = {
        "auto_delete": True,
        "notify_owner_on_response": False,
        "notify_audience_on_close": True,
        "anonymous_votes": False,
        "hide_results_until_close": False,
    }
    passthrough_attributes: set[str] = {"max_yes_choices"}
    for name in PollForm.model_fields:
        if name == "options":
            continue  # rendered separately via _poll_options_to_dicts
        if name in bool_attribute_defaults:
            data[name] = bool(poll.attributes.get(name, bool_attribute_defaults[name]))
            continue
        if name in passthrough_attributes:
            raw = poll.attributes.get(name)
            data[name] = "" if raw is None else raw
            continue
        value = getattr(poll, name, None)
        if isinstance(value, datetime):
            data[name] = _iso_local(value)
        elif isinstance(value, Enum):
            data[name] = value.value
        elif value is None:
            data[name] = ""
        else:
            data[name] = value
    return data


def _iso_local(value: datetime | None) -> str:
    if value is None:
        return ""
    return to_local(value).strftime("%Y-%m-%dT%H:%M")


def _poll_options_to_dicts(options: Iterable[PollOption]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for o in options:
        if o.is_custom:
            continue
        entry: dict[str, Any] = {"type": o.option_type.value}
        if o.option_type == PollOptionType.DATE and o.date_value is not None:
            entry["date_value"] = o.date_value.isoformat()
        elif o.option_type == PollOptionType.DATETIME and o.datetime_value is not None:
            entry["datetime_value"] = to_local(o.datetime_value).strftime("%Y-%m-%dT%H:%M")
        elif o.option_type == PollOptionType.TEXT:
            entry["text_value"] = o.text_value or ""
        result.append(entry)
    return result


def _render_vote(
    db: Any,
    *,
    poll: Poll,
    guard: VoteGuard,
    is_owner: bool,
    errors: list[Any],
) -> str:
    my_response = poll_service.get_user_response(db, poll_id=poll.id, user_id=g.user["id"])
    summary_tallies, summary_rows = poll_service.get_response_summary(db, poll=poll)
    options = list(poll.options)

    hide_results = bool(poll.attributes.get("hide_results_until_close", False)) and (
        poll.status != PollStatus.CLOSED
    )
    anonymous = bool(poll.attributes.get("anonymous_votes", False))
    max_yes = poll.attributes.get("max_yes_choices")

    options_json = [
        {
            "id": o.id,
            "label": _option_label(o),
            "is_custom": o.is_custom,
        }
        for o in options
    ]

    summary_rows_json = [
        {
            "user": (r.user.name or r.user.preferred_username) if r.user else None,
            "submitted_at": r.submitted_at.strftime("%Y-%m-%d %H:%M"),
            "votes": {oid: status.value for oid, status in r.votes.items()},
            "option_guests": r.option_guests,
            "comment": r.comment,
        }
        for r in summary_rows
    ]

    return render_template(
        "polls/vote.html",
        poll=poll,
        guard=guard,
        is_owner=is_owner,
        options=options,
        options_json=options_json,
        my_response=my_response,
        initial_votes=_response_to_initial_votes(my_response),
        initial_guests=_response_to_initial_guests(my_response),
        summary_tallies=summary_tallies,
        summary_rows=summary_rows_json,
        hide_results=hide_results,
        anonymous=anonymous,
        max_yes=max_yes,
        errors=errors,
    )


def _response_to_initial_votes(response: PollResponse | None) -> dict[int, str]:
    if response is None:
        return {}
    return {ov.option_id: ov.status.value for ov in response.option_votes}


def _response_to_initial_guests(response: PollResponse | None) -> dict[int, int]:
    if response is None:
        return {}
    return {ov.option_id: ov.guest_count for ov in response.option_votes if ov.guest_count}


def _option_label(opt: PollOption) -> str:
    if opt.option_type == PollOptionType.DATE and opt.date_value is not None:
        return opt.date_value.strftime("%Y-%m-%d")
    if opt.option_type == PollOptionType.DATETIME and opt.datetime_value is not None:
        return opt.datetime_value.strftime("%Y-%m-%d %H:%M")
    return opt.text_value or ""


def _audience_users_to_dicts(users: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": user.id,
            "label": user.name or user.preferred_username,
            "sublabel": user.email,
        }
        for user in users
    ]


def _audience_groups_to_dicts(groups: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": group.id,
            "label": group.name,
            "sublabel": "",
        }
        for group in groups
    ]


def _form_options_fallback(
    raw: str, fallback: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        log.debug("invalid options payload on form re-render, using fallback")
        return fallback or []
    if not isinstance(parsed, list):
        return fallback or []
    return parsed
