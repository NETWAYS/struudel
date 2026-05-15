"""Tests for the admin-facing group service behaviour and the SCIM decoupling.

Covers:
- SCIM `update_group` / `patch_group` no longer overwrites the admin-managed
  `name` (alias) or the `hidden` flag.
- `apply_admin_edits` is atomic and rejects unknown ids.
- `list_all_groups` returns groups ordered by canonical_name.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from struudel.blueprints.admin.forms import GroupEdit
from struudel.models.group import Group
from struudel.services import group as group_service


def _make_group(
    db: Session,
    *,
    canonical_name: str,
    name: str | None = None,
    external_id: str | None = None,
    hidden: bool = False,
) -> Group:
    g = Group(
        canonical_name=canonical_name,
        name=name or canonical_name.title(),
        external_id=external_id,
        hidden=hidden,
    )
    db.add(g)
    db.flush()
    return g


# ---------------------------------------------------------------------------
# SCIM decoupling: name + hidden stay admin-owned
# ---------------------------------------------------------------------------


def test_scim_update_preserves_admin_alias_and_hidden(db_session: Session) -> None:
    grp = group_service.create_group(db_session, display_name="Engineering", external_id="ext-1")
    # Admin customisations
    grp.name = "Eng Team"
    grp.hidden = True
    db_session.flush()

    # SCIM rename
    group_service.update_group(
        db_session,
        group_id=grp.id,
        display_name="Engineering Squad",
    )
    db_session.refresh(grp)

    assert grp.canonical_name == "engineering squad", "SCIM should update canonical_name"
    assert grp.name == "Eng Team", "admin alias must survive SCIM update"
    assert grp.hidden is True, "admin hidden flag must survive SCIM update"


def test_scim_patch_preserves_admin_alias_and_hidden(db_session: Session) -> None:
    grp = group_service.create_group(db_session, display_name="Original", external_id="ext-2")
    grp.name = "My Alias"
    grp.hidden = True
    db_session.flush()

    group_service.patch_group(
        db_session,
        group_id=grp.id,
        display_name="Renamed",
        external_id=None,
        replace_members=None,
        add_members=[],
        remove_members=[],
    )
    db_session.refresh(grp)

    assert grp.canonical_name == "renamed"
    assert grp.name == "My Alias"
    assert grp.hidden is True


def test_scim_create_seeds_name_as_initial_alias(db_session: Session) -> None:
    grp = group_service.create_group(db_session, display_name="Marketing", external_id="ext-3")
    assert grp.canonical_name == "marketing"
    assert grp.name == "Marketing", "create seeds name from display_name"
    assert grp.hidden is False, "hidden defaults to false"


# ---------------------------------------------------------------------------
# apply_admin_edits — atomic, validates ids
# ---------------------------------------------------------------------------


def test_apply_admin_edits_writes_all_changes(db_session: Session) -> None:
    g1 = _make_group(db_session, canonical_name="alpha", name="Alpha")
    g2 = _make_group(db_session, canonical_name="beta", name="Beta")

    group_service.apply_admin_edits(
        db_session,
        edits=[
            GroupEdit(id=g1.id, name="Alpha New", hidden=True),
            GroupEdit(id=g2.id, name="Beta New", hidden=False),
        ],
    )

    db_session.refresh(g1)
    db_session.refresh(g2)
    assert g1.name == "Alpha New"
    assert g1.hidden is True
    assert g2.name == "Beta New"
    assert g2.hidden is False


def test_apply_admin_edits_raises_on_unknown_id(db_session: Session) -> None:
    g1 = _make_group(db_session, canonical_name="alpha", name="Alpha")

    with pytest.raises(ValueError, match="unknown group ids"):
        group_service.apply_admin_edits(
            db_session,
            edits=[
                GroupEdit(id=g1.id, name="kept", hidden=False),
                GroupEdit(id=999_999, name="ghost", hidden=False),
            ],
        )

    # Atomic: g1 was NOT touched because the whole batch failed pre-commit
    db_session.refresh(g1)
    assert g1.name == "Alpha", "no edits should have been applied"


def test_apply_admin_edits_empty_list_is_noop(db_session: Session) -> None:
    group_service.apply_admin_edits(db_session, edits=[])  # must not raise


# ---------------------------------------------------------------------------
# list_all_groups
# ---------------------------------------------------------------------------


def test_list_all_groups_sorted_by_canonical_name(db_session: Session) -> None:
    _make_group(db_session, canonical_name="zulu")
    _make_group(db_session, canonical_name="alpha")
    _make_group(db_session, canonical_name="mike")

    names = [g.canonical_name for g in group_service.list_all_groups(db_session)]
    assert names == sorted(names)
    assert "alpha" in names and "mike" in names and "zulu" in names
