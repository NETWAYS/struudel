"""add poll option groups

Revision ID: 9d4e1f6a2b58
Revises: 7a2c4f9e8b13
Create Date: 2026-09-04 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d4e1f6a2b58"
down_revision: str | None = "7a2c4f9e8b13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "poll_option_groups",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("max_selections", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["poll_id"], ["polls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_poll_option_groups_poll_id", "poll_id"),
        sa.CheckConstraint(
            "max_selections IS NULL OR max_selections >= 1",
            name="ck_poll_option_groups_max_selections_positive",
        ),
    )
    op.add_column("poll_options", sa.Column("group_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_poll_options_group_id_poll_option_groups",
        "poll_options",
        "poll_option_groups",
        ["group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_poll_options_group_id", "poll_options", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_poll_options_group_id", table_name="poll_options")
    op.drop_constraint(
        "fk_poll_options_group_id_poll_option_groups", "poll_options", type_="foreignkey"
    )
    op.drop_column("poll_options", "group_id")
    op.drop_table("poll_option_groups")
