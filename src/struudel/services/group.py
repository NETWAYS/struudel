import logging
from typing import TYPE_CHECKING, Any, NamedTuple

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from struudel.models.associations import user_group
from struudel.models.group import Group
from struudel.models.user import User

if TYPE_CHECKING:
    from struudel.blueprints.admin.forms import GroupEdit

log = logging.getLogger(__name__)


class GroupCounts(NamedTuple):
    total: int
    hidden: int


def count_groups(db: Session) -> GroupCounts:
    row = db.execute(
        sa.select(
            sa.func.count().label("total"),
            sa.func.count().filter(Group.hidden.is_(True)).label("hidden"),
        ).select_from(Group)
    ).one()
    return GroupCounts(total=row.total, hidden=row.hidden)


def get_group_by_id(db: Session, *, group_id: int) -> Group | None:
    return db.scalar(
        sa.select(Group).where(Group.id == group_id).options(selectinload(Group.users))
    )


def get_group_by_external_id(db: Session, *, external_id: str) -> Group | None:
    return db.scalar(
        sa.select(Group).where(Group.external_id == external_id).options(selectinload(Group.users))
    )


def list_groups(
    db: Session,
    *,
    filter_attr: str | None = None,
    filter_value: str | None = None,
    start_index: int = 1,
    count: int = 50,
) -> tuple[list[Group], int]:
    stmt = sa.select(Group).options(selectinload(Group.users))
    count_stmt = sa.select(sa.func.count()).select_from(Group)

    if filter_attr is not None and filter_value is not None:
        column = _group_filter_column(filter_attr)
        if column is None:
            return [], 0
        value = filter_value.lower() if filter_attr.lower() == "displayname" else filter_value
        stmt = stmt.where(column == value)
        count_stmt = count_stmt.where(column == value)

    total = db.scalar(count_stmt) or 0
    offset = max(start_index - 1, 0)
    stmt = stmt.order_by(Group.id).offset(offset).limit(max(count, 0))
    groups = list(db.scalars(stmt).all())
    return groups, total


def _group_filter_column(attr: str) -> Any:
    mapping: dict[str, Any] = {
        "id": Group.id,
        "displayname": Group.canonical_name,
        "externalid": Group.external_id,
    }
    return mapping.get(attr.lower())


def create_group(
    db: Session,
    *,
    display_name: str,
    external_id: str | None = None,
    member_user_ids: list[int] | None = None,
) -> Group:
    group = Group(
        name=display_name,
        canonical_name=display_name.lower(),
        external_id=external_id,
    )
    db.add(group)
    db.flush()

    if member_user_ids:
        _add_members(db, group_id=group.id, user_ids=member_user_ids)

    db.commit()
    log.info("SCIM create_group id=%s external_id=%s", group.id, external_id)
    return _reload_group(db, group_id=group.id)


def update_group(
    db: Session,
    *,
    group_id: int,
    display_name: str | None = None,
    external_id: str | None = None,
    member_user_ids: list[int] | None = None,
) -> Group | None:
    group = db.get(Group, group_id)
    if group is None:
        return None

    _apply_scalars(group, display_name=display_name, external_id=external_id)
    if member_user_ids is not None:
        _replace_members(db, group_id=group_id, user_ids=member_user_ids)

    db.commit()
    log.info("SCIM update_group id=%s", group_id)
    return _reload_group(db, group_id=group_id)


def patch_group(
    db: Session,
    *,
    group_id: int,
    display_name: str | None,
    external_id: str | None,
    replace_members: list[int] | None,
    add_members: list[int],
    remove_members: list[int],
) -> Group | None:
    group = db.get(Group, group_id)
    if group is None:
        return None

    _apply_scalars(group, display_name=display_name, external_id=external_id)

    if replace_members is not None:
        _replace_members(db, group_id=group_id, user_ids=replace_members)
    if add_members:
        _add_members(db, group_id=group_id, user_ids=add_members)
    if remove_members:
        _remove_members(db, group_id=group_id, user_ids=remove_members)

    db.commit()
    log.info(
        "SCIM patch_group id=%s add=%d remove=%d replace=%s",
        group_id,
        len(add_members),
        len(remove_members),
        replace_members is not None,
    )
    return _reload_group(db, group_id=group_id)


def list_all_groups(db: Session) -> list[Group]:
    stmt = sa.select(Group).order_by(Group.canonical_name)
    return list(db.scalars(stmt).all())


def apply_admin_edits(db: Session, *, edits: list["GroupEdit"]) -> None:
    """Atomically apply all admin edits (alias + hidden) to the listed groups.

    Raises ValueError if any id does not exist. Commits once at the end.
    """
    if not edits:
        return
    ids = [e.id for e in edits]
    groups_by_id: dict[int, Group] = {
        g.id: g for g in db.scalars(sa.select(Group).where(Group.id.in_(ids))).all()
    }
    missing = set(ids) - groups_by_id.keys()
    if missing:
        raise ValueError(f"unknown group ids: {sorted(missing)}")

    for edit in edits:
        g = groups_by_id[edit.id]
        g.name = edit.name
        g.hidden = edit.hidden
    db.commit()
    log.info("apply_admin_edits count=%d", len(edits))


def delete_group(db: Session, *, group_id: int) -> bool:
    group = db.get(Group, group_id)
    if group is None:
        return False
    external_id = group.external_id
    db.delete(group)
    db.commit()
    log.info("SCIM delete_group id=%s external_id=%s", group_id, external_id)
    return True


def _reload_group(db: Session, *, group_id: int) -> Group:
    group = get_group_by_id(db, group_id=group_id)
    assert group is not None
    return group


def _apply_scalars(group: Group, *, display_name: str | None, external_id: str | None) -> None:
    if display_name is not None:
        group.canonical_name = display_name.lower()
    if external_id is not None:
        group.external_id = external_id


def _replace_members(db: Session, *, group_id: int, user_ids: list[int]) -> None:
    db.execute(sa.delete(user_group).where(user_group.c.group_id == group_id))
    if user_ids:
        _add_members(db, group_id=group_id, user_ids=user_ids)


def _add_members(db: Session, *, group_id: int, user_ids: list[int]) -> None:
    requested = set(user_ids)
    valid = set(db.scalars(sa.select(User.id).where(User.id.in_(requested))).all())
    invalid = requested - valid
    if invalid:
        log.info("SCIM add_members skipped unknown ids group=%s ids=%s", group_id, sorted(invalid))

    if valid:
        db.execute(
            pg_insert(user_group)
            .values([{"group_id": group_id, "user_id": uid} for uid in sorted(valid)])
            .on_conflict_do_nothing(index_elements=["user_id", "group_id"])
        )


def _remove_members(db: Session, *, group_id: int, user_ids: list[int]) -> None:
    if not user_ids:
        return
    db.execute(
        sa.delete(user_group).where(
            user_group.c.group_id == group_id,
            user_group.c.user_id.in_(user_ids),
        )
    )
