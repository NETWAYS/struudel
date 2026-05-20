from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from struudel.config import settings

if TYPE_CHECKING:
    from struudel.blueprints.polls.forms import PollForm, PollOptionData
from struudel.models.associations import (
    poll_groups,
    poll_users,
    user_group,
)
from struudel.models.group import Group
from struudel.models.poll import Poll, PollResponseMode, PollStatus, PollVisibility
from struudel.models.poll_option import PollOption, PollOptionType
from struudel.models.poll_response import PollResponse, PollResponseOption, PollResponseStatus
from struudel.models.user import User


def get_poll(db: Session, *, poll_id: int) -> Poll | None:
    return db.get(Poll, poll_id)


def count_polls_by_status(db: Session) -> dict[PollStatus, int]:
    """Total poll count grouped by status. Statuses with zero rows are not in the dict."""
    rows = db.execute(sa.select(Poll.status, sa.func.count()).group_by(Poll.status)).all()
    return {status: count for status, count in rows}


def get_poll_by_share_token(db: Session, *, token: UUID) -> Poll | None:
    return db.scalar(sa.select(Poll).where(Poll.share_token == token))


def user_can_view_poll(db: Session, *, poll: Poll, user_id: int) -> bool:
    if poll.status == PollStatus.TEMPLATE:
        return False
    if poll.created_by_id == user_id:
        return True
    if poll.visibility == PollVisibility.PUBLIC:
        return True

    direct = db.scalar(
        sa.select(
            sa.exists().where(
                poll_users.c.poll_id == poll.id,
                poll_users.c.user_id == user_id,
            )
        )
    )
    if direct:
        return True

    via_group = db.scalar(
        sa.select(
            sa.exists().where(
                poll_groups.c.poll_id == poll.id,
                poll_groups.c.group_id.in_(
                    sa.select(user_group.c.group_id).where(user_group.c.user_id == user_id)
                ),
            )
        )
    )
    return bool(via_group)


def search_polls(
    db: Session,
    *,
    title_query: str = "",
    creator_query: str = "",
    status: PollStatus | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Poll], int, int]:
    """Paginated poll search for the admin UI. Returns (polls, total, page).

    `effective_page` is the requested page clamped into [1, total_pages].
    """
    stmt = sa.select(Poll).options(selectinload(Poll.created_by))
    count_stmt = sa.select(sa.func.count()).select_from(Poll)

    t = title_query.strip()
    if t:
        pattern = f"%{t}%"
        stmt = stmt.where(Poll.title.ilike(pattern))
        count_stmt = count_stmt.where(Poll.title.ilike(pattern))

    c = creator_query.strip()
    if c:
        pattern = f"%{c}%"
        creator_clause = Poll.created_by.has(
            sa.or_(User.name.ilike(pattern), User.preferred_username.ilike(pattern))
        )
        stmt = stmt.where(creator_clause)
        count_stmt = count_stmt.where(creator_clause)

    if status is not None:
        stmt = stmt.where(Poll.status == status)
        count_stmt = count_stmt.where(Poll.status == status)

    total = db.scalar(count_stmt) or 0
    total_pages = max(1, ((total - 1) // per_page) + 1) if total else 1
    effective_page = min(max(page, 1), total_pages)
    offset = (effective_page - 1) * per_page
    stmt = stmt.order_by(Poll.created_at.desc(), Poll.id.desc()).offset(offset).limit(per_page)
    return list(db.scalars(stmt)), total, effective_page


def list_my_polls(db: Session, *, user_id: int) -> list[Poll]:
    stmt = (
        sa.select(Poll)
        .where(Poll.created_by_id == user_id)
        .where(Poll.status != PollStatus.TEMPLATE)
        .options(selectinload(Poll.created_by))
        .order_by(Poll.created_at.desc(), Poll.id.desc())
    )
    return list(db.scalars(stmt))


def list_participating_polls(db: Session, *, user_id: int) -> list[Poll]:
    user_poll_ids = sa.select(poll_users.c.poll_id).where(poll_users.c.user_id == user_id)
    user_group_ids = sa.select(user_group.c.group_id).where(user_group.c.user_id == user_id)
    group_poll_ids = sa.select(poll_groups.c.poll_id).where(
        poll_groups.c.group_id.in_(user_group_ids)
    )

    stmt = (
        sa.select(Poll)
        .where(Poll.status != PollStatus.TEMPLATE)
        .where(sa.or_(Poll.id.in_(user_poll_ids), Poll.id.in_(group_poll_ids)))
        .options(selectinload(Poll.created_by))
        .order_by(Poll.created_at.desc(), Poll.id.desc())
    )
    return list(db.scalars(stmt))


def list_public_polls(db: Session) -> list[Poll]:
    stmt = (
        sa.select(Poll)
        .where(Poll.visibility == "PUBLIC")
        .where(Poll.status != PollStatus.TEMPLATE)
        .options(selectinload(Poll.created_by))
        .order_by(Poll.created_at.desc(), Poll.id.desc())
    )
    return list(db.scalars(stmt))


@dataclass(frozen=True)
class MyPollSummary:
    poll: Poll
    response_count: int
    audience_count: int | None


@dataclass(frozen=True)
class VotedPollEntry:
    poll: Poll
    submitted_at: datetime


@dataclass(frozen=True)
class DashboardData:
    my_active: list[MyPollSummary]
    action_required: list[Poll]
    already_voted: list[VotedPollEntry]
    public_open: list[Poll]


def _is_within_window(poll: Poll, now: datetime) -> bool:
    if poll.starts_at is not None and now < poll.starts_at:
        return False
    return not (poll.ends_at is not None and now > poll.ends_at)


def get_dashboard_data(
    db: Session, *, user_id: int, limit: int = 5, now: datetime | None = None
) -> DashboardData:
    now = now or datetime.now(UTC)

    my_active_polls = [
        p for p in list_my_polls(db, user_id=user_id) if p.status == PollStatus.ACTIVE
    ][:limit]
    my_active = [
        MyPollSummary(
            poll=p,
            response_count=count_responses(db, poll_id=p.id),
            audience_count=count_audience_members(db, poll_id=p.id) if p.is_mandatory else None,
        )
        for p in my_active_polls
    ]

    voted_poll_ids: set[int] = set(
        db.scalars(sa.select(PollResponse.poll_id).where(PollResponse.user_id == user_id)).all()
    )

    invited = list_participating_polls(db, user_id=user_id)
    action_required: list[Poll] = []
    for p in invited:
        if p.status != PollStatus.ACTIVE:
            continue
        if p.id in voted_poll_ids:
            continue
        if not _is_within_window(p, now):
            continue
        action_required.append(p)

    def _action_sort_key(p: Poll) -> tuple[int, datetime]:
        return (
            0 if p.is_mandatory else 1,
            p.ends_at or datetime.max.replace(tzinfo=UTC),
        )

    action_required.sort(key=_action_sort_key)
    action_required = action_required[:limit]

    already_voted_stmt = (
        sa.select(Poll, PollResponse.submitted_at)
        .join(PollResponse, PollResponse.poll_id == Poll.id)
        .where(PollResponse.user_id == user_id)
        .where(Poll.status != PollStatus.TEMPLATE)
        .options(selectinload(Poll.created_by))
        .order_by(PollResponse.submitted_at.desc())
        .limit(limit)
    )
    already_voted = [
        VotedPollEntry(poll=poll, submitted_at=submitted_at)
        for poll, submitted_at in db.execute(already_voted_stmt).all()
    ]

    public_open: list[Poll] = []
    for p in list_public_polls(db):
        if p.created_by_id == user_id:
            continue
        if p.status != PollStatus.ACTIVE:
            continue
        if p.id in voted_poll_ids:
            continue
        if not _is_within_window(p, now):
            continue
        public_open.append(p)
    public_open = public_open[:limit]

    return DashboardData(
        my_active=my_active,
        action_required=action_required,
        already_voted=already_voted,
        public_open=public_open,
    )


class MandatoryRequiresAudienceError(ValueError):
    """Raised when a mandatory poll is activated without any audience."""


class ActiveRequiresOptionsError(ValueError):
    """Raised when a poll is activated without any options."""


def _dispatch_activation_invitations(db: Session, *, poll: Poll) -> None:
    if poll.starts_at is not None and poll.starts_at > datetime.now(UTC):
        # Voting hasn't opened yet — dispatch_pending_invitations_task picks
        # this poll up once `starts_at` is crossed.
        return

    audience_ids = get_audience_user_ids(db, poll_id=poll.id)
    if not audience_ids:
        return

    from struudel.mail import try_claim_invitation_lock

    if not try_claim_invitation_lock(poll.id):
        return

    from struudel.tasks.mail.send_invitation import send_invitation_task

    for user_id in audience_ids:
        send_invitation_task(poll.id, user_id)


def _dispatch_close_notifications(db: Session, *, poll: Poll) -> None:
    from struudel.tasks.mail.send_poll_closed_audience import send_poll_closed_audience_task
    from struudel.tasks.mail.send_poll_closed_owner import send_poll_closed_owner_task

    send_poll_closed_owner_task(poll.id)

    if poll.attributes.get("notify_audience_on_close", True):
        audience_ids = get_audience_user_ids(db, poll_id=poll.id)
        for user_id in audience_ids:
            send_poll_closed_audience_task(poll.id, user_id)

    if poll.is_mandatory:
        from struudel.tasks.mail.send_non_responder_report import send_non_responder_report_task

        send_non_responder_report_task(poll.id)


def create_poll(db: Session, *, form: PollForm, created_by_id: int) -> Poll:
    if form.status == PollStatus.ACTIVE and not form.options:
        raise ActiveRequiresOptionsError("active polls require at least one option")

    if form.is_mandatory and form.status == PollStatus.ACTIVE:
        raise MandatoryRequiresAudienceError(
            "mandatory polls require a non-empty audience before activation"
        )

    poll = Poll(
        title=form.title,
        description_short=form.description_short,
        description_long=form.description_long,
        status=form.status,
        visibility=form.visibility,
        response_mode=form.response_mode,
        is_mandatory=form.is_mandatory,
        allow_custom_options=form.allow_custom_options,
        allow_edit_responses=form.allow_edit_responses,
        edit_responses_until=form.edit_responses_until if form.allow_edit_responses else None,
        allow_guests=form.allow_guests,
        max_guests=form.max_guests if form.allow_guests else None,
        starts_at=form.starts_at,
        ends_at=form.ends_at,
        attributes={
            "auto_delete": form.auto_delete,
            "notify_owner_on_response": form.notify_owner_on_response,
            "notify_audience_on_close": form.notify_audience_on_close,
            "anonymous_votes": form.anonymous_votes,
            "hide_results_until_close": form.hide_results_until_close,
            "max_yes_choices": form.max_yes_choices,
        },
        created_by_id=created_by_id,
    )
    _apply_auto_delete_at(poll)
    db.add(poll)
    db.flush()
    _apply_options(db, poll=poll, options=form.options)
    db.commit()
    db.refresh(poll)
    return poll


def update_poll(db: Session, *, poll: Poll, form: PollForm) -> Poll:
    if form.status == PollStatus.ACTIVE and not form.options:
        raise ActiveRequiresOptionsError("active polls require at least one option")

    if (
        form.is_mandatory
        and form.status == PollStatus.ACTIVE
        and count_poll_audience(db, poll_id=poll.id) == 0
    ):
        raise MandatoryRequiresAudienceError(
            "mandatory polls require a non-empty audience before activation"
        )

    old_status = poll.status

    poll.title = form.title
    poll.description_short = form.description_short
    poll.description_long = form.description_long
    poll.status = form.status
    poll.visibility = form.visibility
    poll.response_mode = form.response_mode
    poll.is_mandatory = form.is_mandatory
    poll.allow_custom_options = form.allow_custom_options
    poll.allow_edit_responses = form.allow_edit_responses
    poll.edit_responses_until = form.edit_responses_until if form.allow_edit_responses else None
    poll.allow_guests = form.allow_guests
    poll.max_guests = form.max_guests if form.allow_guests else None
    poll.starts_at = form.starts_at
    poll.ends_at = form.ends_at

    attributes = dict(poll.attributes or {})
    attributes["auto_delete"] = form.auto_delete
    attributes["notify_owner_on_response"] = form.notify_owner_on_response
    attributes["notify_audience_on_close"] = form.notify_audience_on_close
    attributes["anonymous_votes"] = form.anonymous_votes
    attributes["hide_results_until_close"] = form.hide_results_until_close
    attributes["max_yes_choices"] = form.max_yes_choices
    poll.attributes = attributes
    _apply_auto_delete_at(poll)

    _apply_options(db, poll=poll, options=form.options)
    db.commit()
    db.refresh(poll)

    if old_status == PollStatus.DRAFT and poll.status == PollStatus.ACTIVE:
        _dispatch_activation_invitations(db, poll=poll)
    elif old_status != PollStatus.CLOSED and poll.status == PollStatus.CLOSED:
        _dispatch_close_notifications(db, poll=poll)

    return poll


def _apply_auto_delete_at(poll: Poll) -> None:
    """Compute `auto_delete_at` from the current status and the auto_delete flag.

    Clears the timestamp if auto_delete is off or the poll is not closed.
    """
    enabled = bool(poll.attributes.get("auto_delete", True))
    if enabled and poll.status == PollStatus.CLOSED:
        poll.auto_delete_at = datetime.now(UTC) + timedelta(days=settings.poll_retention_days)
    else:
        poll.auto_delete_at = None


def delete_poll(db: Session, *, poll: Poll) -> None:
    db.delete(poll)
    db.commit()


def regenerate_share_token(db: Session, *, poll: Poll) -> UUID:
    poll.share_token = uuid4()
    db.commit()
    db.refresh(poll)
    return poll.share_token


class CustomOptionsDisabledError(ValueError):
    """Raised when a voter tries to add a custom option but the poll forbids it."""


def add_custom_option(
    db: Session,
    *,
    poll: Poll,
    user_id: int,
    option: PollOptionData,
) -> PollOption:
    if not poll.allow_custom_options:
        raise CustomOptionsDisabledError("custom options are not allowed on this poll")

    guard = user_can_vote_on_poll(poll, now=datetime.now(UTC))
    if not guard.can_vote:
        raise CustomOptionsDisabledError("voting is not currently open")

    max_order = db.scalar(
        sa.select(sa.func.coalesce(sa.func.max(PollOption.sort_order), -1)).where(
            PollOption.poll_id == poll.id
        )
    )
    next_sort_order = (max_order if max_order is not None else -1) + 1

    row = PollOption(
        poll_id=poll.id,
        option_type=option.type,
        sort_order=next_sort_order,
        is_custom=True,
        created_by_id=user_id,
        date_value=option.date_value if option.type == PollOptionType.DATE else None,
        datetime_value=option.datetime_value if option.type == PollOptionType.DATETIME else None,
        text_value=option.text_value if option.type == PollOptionType.TEXT else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def close_due_polls(db: Session) -> int:
    now = datetime.now(UTC)
    # FOR UPDATE SKIP LOCKED prevents two periodic workers from picking
    # up the same poll, flipping it to CLOSED, and enqueuing duplicate
    # close-notification mails. The second worker simply sees no rows.
    polls = list(
        db.scalars(
            sa.select(Poll)
            .where(
                Poll.status == PollStatus.ACTIVE,
                Poll.ends_at.is_not(None),
                Poll.ends_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for poll in polls:
        poll.status = PollStatus.CLOSED
        _apply_auto_delete_at(poll)
    if polls:
        db.commit()
        for poll in polls:
            _dispatch_close_notifications(db, poll=poll)
    return len(polls)


def purge_expired_polls(db: Session) -> int:
    now = datetime.now(UTC)
    polls = list(
        db.scalars(
            sa.select(Poll).where(
                Poll.auto_delete_at.is_not(None),
                Poll.auto_delete_at <= now,
            )
        )
    )
    for poll in polls:
        db.delete(poll)
    if polls:
        db.commit()
    return len(polls)


def _form_option_key(opt: PollOptionData) -> tuple[PollOptionType, Any, Any, Any]:
    return (opt.type, opt.date_value, opt.datetime_value, opt.text_value)


def _model_option_key(opt: PollOption) -> tuple[PollOptionType, Any, Any, Any]:
    return (opt.option_type, opt.date_value, opt.datetime_value, opt.text_value)


def options_have_destructive_changes(
    db: Session, *, poll: Poll, options: list[PollOptionData]
) -> bool:
    """True if applying `options` would remove any existing non-custom option
    (and thus cascade-delete its votes)."""
    existing = db.scalars(
        sa.select(PollOption).where(
            PollOption.poll_id == poll.id,
            PollOption.is_custom.is_(False),
        )
    ).all()
    new_keys = {_form_option_key(opt) for opt in options}
    return any(_model_option_key(o) not in new_keys for o in existing)


def _apply_options(db: Session, *, poll: Poll, options: list[PollOptionData]) -> None:
    existing = list(
        db.scalars(
            sa.select(PollOption).where(
                PollOption.poll_id == poll.id,
                PollOption.is_custom.is_(False),
            )
        )
    )
    existing_by_key: dict[tuple[PollOptionType, Any, Any, Any], PollOption] = {}
    for o in existing:
        existing_by_key.setdefault(_model_option_key(o), o)

    kept_ids: set[int] = set()
    for idx, opt in enumerate(options):
        match = existing_by_key.get(_form_option_key(opt))
        if match is not None and match.id not in kept_ids:
            if match.sort_order != idx:
                match.sort_order = idx
            kept_ids.add(match.id)
        else:
            db.add(
                PollOption(
                    poll_id=poll.id,
                    option_type=opt.type,
                    sort_order=idx,
                    is_custom=False,
                    date_value=opt.date_value if opt.type == PollOptionType.DATE else None,
                    datetime_value=(
                        opt.datetime_value if opt.type == PollOptionType.DATETIME else None
                    ),
                    text_value=opt.text_value if opt.type == PollOptionType.TEXT else None,
                )
            )

    to_delete = [o.id for o in existing if o.id not in kept_ids]
    if to_delete:
        db.execute(sa.delete(PollOption).where(PollOption.id.in_(to_delete)))

    db.flush()


# ---------------------------------------------------------------------------
# Audience
# ---------------------------------------------------------------------------


def search_audience_candidates(
    db: Session,
    *,
    query: str,
    kind: Literal["user", "group"],
    limit: int = 20,
) -> list[User] | list[Group]:
    pattern = f"%{query}%"
    if kind == "user":
        stmt = (
            sa.select(User)
            .where(User.is_active.is_(True))
            .where(
                sa.or_(
                    User.preferred_username.ilike(pattern),
                    User.name.ilike(pattern),
                    User.email.ilike(pattern),
                )
            )
            .order_by(User.name)
            .limit(limit)
        )
        return list(db.scalars(stmt))

    stmt_g = (
        sa.select(Group)
        .where(Group.hidden.is_(False))
        .where(sa.or_(Group.name.ilike(pattern), Group.canonical_name.ilike(pattern)))
        .order_by(Group.name)
        .limit(limit)
    )
    return list(db.scalars(stmt_g))


def get_poll_audience(db: Session, *, poll: Poll) -> tuple[list[User], list[Group]]:
    users = list(
        db.scalars(
            sa.select(User)
            .join(poll_users, poll_users.c.user_id == User.id)
            .where(poll_users.c.poll_id == poll.id)
            .order_by(User.name)
        )
    )
    groups = list(
        db.scalars(
            sa.select(Group)
            .join(poll_groups, poll_groups.c.group_id == Group.id)
            .where(poll_groups.c.poll_id == poll.id)
            .order_by(Group.name)
        )
    )
    return users, groups


def count_poll_audience(db: Session, *, poll_id: int) -> int:
    user_count = (
        db.scalar(
            sa.select(sa.func.count())
            .select_from(poll_users)
            .where(poll_users.c.poll_id == poll_id)
        )
        or 0
    )
    group_count = (
        db.scalar(
            sa.select(sa.func.count())
            .select_from(poll_groups)
            .where(poll_groups.c.poll_id == poll_id)
        )
        or 0
    )
    return user_count + group_count


def count_audience_members(db: Session, *, poll_id: int) -> int:
    direct = sa.select(poll_users.c.user_id).where(poll_users.c.poll_id == poll_id)
    via_group = (
        sa.select(user_group.c.user_id)
        .join(poll_groups, poll_groups.c.group_id == user_group.c.group_id)
        .where(poll_groups.c.poll_id == poll_id)
    )
    union = direct.union(via_group).subquery()
    return db.scalar(sa.select(sa.func.count()).select_from(union)) or 0


def get_audience_user_ids(db: Session, *, poll_id: int) -> set[int]:
    """Distinct user IDs reachable through both direct invites and group expansion.

    Only active users are returned, mirroring `get_audience_response_status` —
    inactive users don't get mail.
    """
    direct = sa.select(poll_users.c.user_id).where(poll_users.c.poll_id == poll_id)
    via_group = (
        sa.select(user_group.c.user_id)
        .join(poll_groups, poll_groups.c.group_id == user_group.c.group_id)
        .where(poll_groups.c.poll_id == poll_id)
    )
    audience_subq = direct.union(via_group).subquery()
    rows = db.scalars(
        sa.select(User.id)
        .where(User.id.in_(sa.select(audience_subq.c.user_id)))
        .where(User.is_active.is_(True))
    ).all()
    return set(rows)


def get_audience_response_status(db: Session, *, poll: Poll) -> tuple[list[User], list[User]]:
    """Split the poll's distinct audience members into responded vs pending.

    Audience = direct invites (poll_users) UNION group members (poll_groups
    expanded through user_group). Both lists are returned ordered by name.
    """
    direct = sa.select(poll_users.c.user_id).where(poll_users.c.poll_id == poll.id)
    via_group = (
        sa.select(user_group.c.user_id)
        .join(poll_groups, poll_groups.c.group_id == user_group.c.group_id)
        .where(poll_groups.c.poll_id == poll.id)
    )
    audience_ids_subq = direct.union(via_group).subquery()

    responder_ids = set(
        db.scalars(sa.select(PollResponse.user_id).where(PollResponse.poll_id == poll.id)).all()
    )

    audience = list(
        db.scalars(
            sa.select(User)
            .where(User.id.in_(sa.select(audience_ids_subq.c.user_id)))
            .where(User.is_active.is_(True))
            .order_by(User.name)
        )
    )

    responded = [u for u in audience if u.id in responder_ids]
    pending = [u for u in audience if u.id not in responder_ids]
    return responded, pending


def set_poll_audience(
    db: Session,
    *,
    poll: Poll,
    users: list[int],
    groups: list[int],
) -> None:
    if poll.is_mandatory and poll.status == PollStatus.ACTIVE and not users and not groups:
        raise MandatoryRequiresAudienceError(
            "mandatory polls require a non-empty audience while active"
        )

    old_user_ids = get_audience_user_ids(db, poll_id=poll.id)

    db.execute(sa.delete(poll_users).where(poll_users.c.poll_id == poll.id))
    db.execute(sa.delete(poll_groups).where(poll_groups.c.poll_id == poll.id))
    db.flush()

    if users:
        valid_user_ids = set(db.scalars(sa.select(User.id).where(User.id.in_(users))).all())
        rows = [{"poll_id": poll.id, "user_id": uid} for uid in users if uid in valid_user_ids]
        if rows:
            db.execute(sa.insert(poll_users), rows)

    if groups:
        valid_group_ids = set(db.scalars(sa.select(Group.id).where(Group.id.in_(groups))).all())
        rows = [{"poll_id": poll.id, "group_id": gid} for gid in groups if gid in valid_group_ids]
        if rows:
            db.execute(sa.insert(poll_groups), rows)

    db.commit()

    if poll.status == PollStatus.ACTIVE:
        if poll.starts_at is not None and poll.starts_at > datetime.now(UTC):
            # Pre-start: the full audience (including these newly added users)
            # is invited by dispatch_pending_invitations_task when starts_at fires.
            return
        new_user_ids = get_audience_user_ids(db, poll_id=poll.id)
        added = new_user_ids - old_user_ids
        if added:
            from struudel.tasks.mail.send_invitation import send_invitation_task

            for user_id in added:
                send_invitation_task(poll.id, user_id)


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------


class InvalidVoteError(ValueError):
    """Raised when a submitted vote violates the poll's response mode rules."""


@dataclass(frozen=True)
class VoteGuard:
    can_vote: bool
    can_edit: bool
    reason: str | None


@dataclass(frozen=True)
class OptionTally:
    yes: int
    yes_guests: int
    maybe: int
    no: int


@dataclass(frozen=True)
class ResponseRow:
    user: User | None
    submitted_at: datetime
    votes: dict[int, PollResponseStatus]
    option_guests: dict[int, int]
    comment: str | None


def user_can_vote_on_poll(poll: Poll, *, now: datetime) -> VoteGuard:
    if poll.status == PollStatus.CLOSED:
        return VoteGuard(can_vote=False, can_edit=False, reason="closed")
    if poll.status != PollStatus.ACTIVE:
        return VoteGuard(can_vote=False, can_edit=False, reason="not_active")
    if poll.starts_at is not None and now < poll.starts_at:
        return VoteGuard(can_vote=False, can_edit=False, reason="not_started")
    if poll.ends_at is not None and now > poll.ends_at:
        return VoteGuard(can_vote=False, can_edit=False, reason="closed")

    can_edit = poll.allow_edit_responses and (
        poll.edit_responses_until is None or now <= poll.edit_responses_until
    )
    return VoteGuard(can_vote=True, can_edit=can_edit, reason=None)


def get_user_response(db: Session, *, poll_id: int, user_id: int) -> PollResponse | None:
    return db.scalar(
        sa.select(PollResponse)
        .where(PollResponse.poll_id == poll_id, PollResponse.user_id == user_id)
        .options(selectinload(PollResponse.option_votes))
    )


def count_responses(db: Session, *, poll_id: int) -> int:
    return (
        db.scalar(
            sa.select(sa.func.count())
            .select_from(PollResponse)
            .where(PollResponse.poll_id == poll_id)
        )
        or 0
    )


def delete_user_response(db: Session, *, poll_id: int, user_id: int) -> bool:
    response = db.scalar(
        sa.select(PollResponse).where(
            PollResponse.poll_id == poll_id,
            PollResponse.user_id == user_id,
        )
    )
    if response is None:
        return False
    db.delete(response)
    db.commit()
    return True


def clear_responses(db: Session, *, poll: Poll) -> int:
    count = 0
    for response in list(poll.responses):
        db.delete(response)
        count += 1
    db.commit()
    return count


def get_response_summary(
    db: Session, *, poll: Poll
) -> tuple[dict[int, OptionTally], list[ResponseRow]]:
    anonymous = bool(poll.attributes.get("anonymous_votes", False))

    responses = list(
        db.scalars(
            sa.select(PollResponse)
            .where(PollResponse.poll_id == poll.id)
            .options(
                selectinload(PollResponse.option_votes),
                selectinload(PollResponse.user),
            )
            .order_by(PollResponse.submitted_at.asc())
        )
    )

    tallies: dict[int, OptionTally] = {}
    per_option: dict[int, dict[PollResponseStatus, int]] = {}
    guests_per_option: dict[int, int] = {}

    for resp in responses:
        for ov in resp.option_votes:
            bucket = per_option.setdefault(
                ov.option_id,
                {
                    PollResponseStatus.YES: 0,
                    PollResponseStatus.NO: 0,
                    PollResponseStatus.MAYBE: 0,
                },
            )
            bucket[ov.status] += 1
            if ov.status == PollResponseStatus.YES and ov.guest_count:
                guests_per_option[ov.option_id] = (
                    guests_per_option.get(ov.option_id, 0) + ov.guest_count
                )

    for opt in poll.options:
        bucket = per_option.get(
            opt.id,
            {
                PollResponseStatus.YES: 0,
                PollResponseStatus.NO: 0,
                PollResponseStatus.MAYBE: 0,
            },
        )
        tallies[opt.id] = OptionTally(
            yes=bucket[PollResponseStatus.YES],
            yes_guests=guests_per_option.get(opt.id, 0),
            maybe=bucket[PollResponseStatus.MAYBE],
            no=bucket[PollResponseStatus.NO],
        )

    rows: list[ResponseRow] = []
    for resp in responses:
        votes = {ov.option_id: ov.status for ov in resp.option_votes}
        option_guests = {
            ov.option_id: ov.guest_count
            for ov in resp.option_votes
            if ov.status == PollResponseStatus.YES and ov.guest_count
        }
        rows.append(
            ResponseRow(
                user=None if anonymous else resp.user,
                submitted_at=resp.submitted_at,
                votes=votes,
                option_guests={} if anonymous else option_guests,
                comment=None if anonymous else resp.comment,
            )
        )

    return tallies, rows


def submit_response(
    db: Session,
    *,
    poll: Poll,
    user_id: int,
    votes: dict[int, PollResponseStatus],
    comment: str | None,
    guest_counts: dict[int, int] | None = None,
) -> PollResponse:
    valid_option_ids = set(
        db.scalars(sa.select(PollOption.id).where(PollOption.poll_id == poll.id)).all()
    )
    if not valid_option_ids:
        raise InvalidVoteError("This poll has no options to vote on")

    filtered_votes = {oid: status for oid, status in votes.items() if oid in valid_option_ids}
    guest_counts = guest_counts or {}

    _validate_votes_against_mode(poll=poll, votes=filtered_votes)

    # Idempotent upsert via the (poll_id, user_id) unique constraint, so two
    # parallel submits from the same user collapse into one row instead of
    # racing on `get + insert` and tripping IntegrityError on the loser.
    upsert_stmt = (
        pg_insert(PollResponse)
        .values(poll_id=poll.id, user_id=user_id, comment=comment)
        .on_conflict_do_update(
            constraint="uq_poll_responses_poll_user",
            set_={"comment": comment},
        )
        .returning(PollResponse)
    )
    response = db.scalars(upsert_stmt).one()
    db.execute(sa.delete(PollResponseOption).where(PollResponseOption.response_id == response.id))
    db.flush()

    for option_id, status in filtered_votes.items():
        guests = guest_counts.get(option_id, 0)
        if not poll.allow_guests or status != PollResponseStatus.YES:
            normalized_guests = 0
        elif poll.max_guests is not None:
            normalized_guests = max(0, min(guests, poll.max_guests))
        else:
            normalized_guests = max(0, guests)
        db.add(
            PollResponseOption(
                response_id=response.id,
                option_id=option_id,
                status=status,
                guest_count=normalized_guests,
            )
        )

    db.commit()
    db.refresh(response)

    if poll.attributes.get("notify_owner_on_response"):
        from struudel.tasks.mail.send_response_notification import send_response_notification_task

        send_response_notification_task(response.id)

    return response


def _validate_votes_against_mode(*, poll: Poll, votes: dict[int, PollResponseStatus]) -> None:
    yes_count = sum(1 for s in votes.values() if s == PollResponseStatus.YES)
    maybe_count = sum(1 for s in votes.values() if s == PollResponseStatus.MAYBE)

    if poll.response_mode == PollResponseMode.SINGLE_CHOICE:
        if maybe_count > 0:
            raise InvalidVoteError("MAYBE is not allowed in single-choice polls")
        if yes_count > 1:
            raise InvalidVoteError("Only one option can be selected in a single-choice poll")

    elif poll.response_mode == PollResponseMode.MULTI_CHOICE:
        if maybe_count > 0:
            raise InvalidVoteError("MAYBE is not allowed in multi-choice polls")
        max_yes = poll.attributes.get("max_yes_choices")
        if isinstance(max_yes, int) and max_yes > 0 and yes_count > max_yes:
            raise InvalidVoteError(f"This poll allows at most {max_yes} selection(s)")
