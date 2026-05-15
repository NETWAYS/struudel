from __future__ import annotations

from typing import NamedTuple

from flask import abort, flash, g, redirect, render_template, request, url_for
from pydantic import ValidationError
from werkzeug.wrappers import Response

from struudel.auth import require_superuser
from struudel.blueprints.admin import bp
from struudel.blueprints.admin.forms import GroupEdit
from struudel.database import SessionLocal
from struudel.models.group import Group
from struudel.models.poll import PollStatus
from struudel.services import group as group_service
from struudel.services import poll as poll_service
from struudel.services import user as user_service


class _GroupParseResult(NamedTuple):
    edits: list[GroupEdit]
    errors: dict[int, str]
    submitted_names: dict[int, str]
    submitted_hidden: dict[int, bool]


_PER_PAGE = 20
_VALID_FILTERS = frozenset({"", "superuser", "inactive"})
_VALID_GROUP_VISIBILITIES = frozenset({"all", "visible", "hidden"})
_VALID_POLL_STATUS = frozenset({""} | {s.name for s in PollStatus})


@bp.route("/")
@require_superuser
def index() -> str:
    with SessionLocal() as db:
        user_counts = user_service.count_users(db)
        group_counts = group_service.count_groups(db)
        polls_by_status = poll_service.count_polls_by_status(db)
    poll_counts = {status.name: count for status, count in polls_by_status.items()}
    poll_counts["TOTAL"] = sum(polls_by_status.values())
    return render_template(
        "admin/index.html",
        user_counts=user_counts,
        group_counts=group_counts,
        poll_counts=poll_counts,
    )


@bp.route("/users")
@require_superuser
def users() -> str:
    return _render_users()


@bp.route("/users/<int:user_id>/superuser", methods=["POST"])
@require_superuser
def user_set_superuser(user_id: int) -> Response | str:
    value = _form_bool("value")
    if not value and user_id == g.user["id"]:
        abort(400, "Cannot revoke your own superuser status.")
    with SessionLocal() as db:
        user = user_service.set_superuser(db, user_id=user_id, value=value)
    if user is not None:
        verb = "Granted" if value else "Revoked"
        flash(f"{verb} superuser for {user.preferred_username}.", "success")
    return _action_response()


@bp.route("/users/<int:user_id>/active", methods=["POST"])
@require_superuser
def user_set_active(user_id: int) -> Response | str:
    value = _form_bool("value")
    if not value and user_id == g.user["id"]:
        abort(400, "Cannot deactivate your own account.")
    with SessionLocal() as db:
        changed = (
            user_service.reactivate_user(db, user_id=user_id)
            if value
            else user_service.deactivate_user(db, user_id=user_id)
        )
    if changed:
        flash(
            "User reactivated." if value else "User deactivated.",
            "success",
        )
    return _action_response()


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@require_superuser
def user_delete(user_id: int) -> Response | str:
    if user_id == g.user["id"]:
        abort(400, "Cannot delete your own account.")
    with SessionLocal() as db:
        deleted = user_service.delete_user_and_artifacts(db, user_id=user_id)
    if deleted:
        flash("User deleted.", "success")
    return _action_response()


def _list_params() -> tuple[str, int, str]:
    q = (request.values.get("q") or "").strip()
    try:
        page = int(request.values.get("page", "1"))
    except ValueError:
        page = 1
    filter_ = request.values.get("filter", "")
    if filter_ not in _VALID_FILTERS:
        filter_ = ""
    return q, page, filter_


def _form_bool(name: str) -> bool:
    return (request.form.get(name) or "").lower() == "on"


def _is_htmx() -> bool:
    return bool(request.headers.get("HX-Request"))


def _render_users() -> str:
    q, page, filter_ = _list_params()
    with SessionLocal() as db:
        items, total, effective_page = user_service.search_users(
            db,
            query=q,
            page=page,
            per_page=_PER_PAGE,
            only_superusers=(filter_ == "superuser"),
            only_inactive=(filter_ == "inactive"),
        )
    ctx = {
        "users": items,
        "total": total,
        "page": effective_page,
        "per_page": _PER_PAGE,
        "q": q,
        "filter": filter_,
    }
    template = "admin/_users_table.html" if _is_htmx() else "admin/users.html"
    return render_template(template, **ctx)


def _action_response() -> Response | str:
    if _is_htmx():
        return _render_users()
    q, page, filter_ = _list_params()
    return redirect(url_for("admin.users", q=q, page=page, filter=filter_))


# --------------------------------------------------------------------------- #
# Groups
# --------------------------------------------------------------------------- #


@bp.route("/groups", methods=["GET", "POST"])
@require_superuser
def groups() -> Response | str | tuple[str, int]:
    with SessionLocal() as db:
        all_groups = group_service.list_all_groups(db)

        if request.method == "GET":
            filter_q, filter_visibility = _group_filter_params()
            return render_template(
                "admin/groups.html",
                groups=all_groups,
                submitted_names={},
                submitted_hidden={},
                errors={},
                filter_q=filter_q,
                filter_visibility=filter_visibility,
            )

        result = _parse_group_edits(all_groups)
        filter_q, filter_visibility = _group_filter_params()
        if result.errors:
            return (
                render_template(
                    "admin/groups.html",
                    groups=all_groups,
                    submitted_names=result.submitted_names,
                    submitted_hidden=result.submitted_hidden,
                    errors=result.errors,
                    filter_q=filter_q,
                    filter_visibility=filter_visibility,
                ),
                400,
            )

        group_service.apply_admin_edits(db, edits=result.edits)

    flash("Group settings saved.", "success")
    return redirect(url_for("admin.groups", q=filter_q, visibility=filter_visibility))


def _group_filter_params() -> tuple[str, str]:
    q = (request.values.get("q") or "").strip()
    visibility = request.values.get("visibility", "all")
    if visibility not in _VALID_GROUP_VISIBILITIES:
        visibility = "all"
    return q, visibility


def _parse_group_edits(all_groups: list[Group]) -> _GroupParseResult:
    edits: list[GroupEdit] = []
    errors: dict[int, str] = {}

    for grp in all_groups:
        raw_name = request.form.get(f"group-{grp.id}-name", "")
        is_hidden = request.form.get(f"group-{grp.id}-hidden") == "on"
        try:
            edits.append(GroupEdit(id=grp.id, name=raw_name, hidden=is_hidden))
        except ValidationError as exc:
            errors[grp.id] = exc.errors()[0]["msg"]

    if not errors:
        return _GroupParseResult(edits=edits, errors={}, submitted_names={}, submitted_hidden={})

    submitted_names = {grp.id: request.form.get(f"group-{grp.id}-name", "") for grp in all_groups}
    submitted_hidden = {
        grp.id: request.form.get(f"group-{grp.id}-hidden") == "on" for grp in all_groups
    }
    return _GroupParseResult(
        edits=edits,
        errors=errors,
        submitted_names=submitted_names,
        submitted_hidden=submitted_hidden,
    )


# --------------------------------------------------------------------------- #
# Polls
# --------------------------------------------------------------------------- #


@bp.route("/polls")
@require_superuser
def polls() -> str:
    return _render_polls()


@bp.route("/polls/<int:poll_id>/delete", methods=["POST"])
@require_superuser
def poll_delete(poll_id: int) -> Response | str:
    with SessionLocal() as db:
        poll = poll_service.get_poll(db, poll_id=poll_id)
        if poll is None:
            abort(404)
        title = poll.title
        poll_service.delete_poll(db, poll=poll)
    flash(f"Poll “{title}” deleted.", "success")
    return _polls_action_response()


def _poll_list_params() -> tuple[str, str, str, int]:
    title = (request.values.get("title") or "").strip()
    creator = (request.values.get("creator") or "").strip()
    status = request.values.get("status", "")
    if status not in _VALID_POLL_STATUS:
        status = ""
    try:
        page = int(request.values.get("page", "1"))
    except ValueError:
        page = 1
    return title, creator, status, max(page, 1)


def _render_polls() -> str:
    title, creator, status, page = _poll_list_params()
    status_enum = PollStatus[status] if status else None
    with SessionLocal() as db:
        items, total, effective_page = poll_service.search_polls(
            db,
            title_query=title,
            creator_query=creator,
            status=status_enum,
            page=page,
            per_page=_PER_PAGE,
        )
    ctx = {
        "polls": items,
        "total": total,
        "page": effective_page,
        "per_page": _PER_PAGE,
        "title_q": title,
        "creator_q": creator,
        "status": status,
    }
    template = "admin/_polls_table.html" if _is_htmx() else "admin/polls.html"
    return render_template(template, **ctx)


def _polls_action_response() -> Response | str:
    if _is_htmx():
        return _render_polls()
    title, creator, status, page = _poll_list_params()
    return redirect(url_for("admin.polls", title=title, creator=creator, status=status, page=page))
