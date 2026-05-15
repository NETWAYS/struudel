"""initial schema

Revision ID: 3f8a1b2c5d7e
Revises:
Create Date: 2026-04-17 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3f8a1b2c5d7e"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


POLL_STATUS = ("DRAFT", "ACTIVE", "CLOSED", "TEMPLATE")
POLL_VISIBILITY = ("PUBLIC", "PRIVATE")
POLL_RESPONSE_MODE = ("YES_NO_MAYBE", "SINGLE_CHOICE", "MULTI_CHOICE")
POLL_OPTION_TYPE = ("DATE", "DATETIME", "TEXT")
POLL_RESPONSE_STATUS = ("YES", "NO", "MAYBE")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("preferred_username", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("given_name", sa.String(), nullable=True),
        sa.Column("family_name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("profile", sa.String(), nullable=True),
        sa.Column("picture", sa.String(), nullable=True),
        sa.Column("cached_picture", sa.LargeBinary(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preferred_username"),
        sa.UniqueConstraint("external_id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "groups",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_name"),
        sa.UniqueConstraint("external_id"),
    )

    op.create_table(
        "user_groups",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "group_id"),
        sa.Index("ix_user_groups_group_id", "group_id"),
    )

    poll_status = postgresql.ENUM(*POLL_STATUS, name="poll_status", create_type=False)
    poll_visibility = postgresql.ENUM(*POLL_VISIBILITY, name="poll_visibility", create_type=False)
    poll_response_mode = postgresql.ENUM(
        *POLL_RESPONSE_MODE, name="poll_response_mode", create_type=False
    )
    poll_option_type = postgresql.ENUM(
        *POLL_OPTION_TYPE, name="poll_option_type", create_type=False
    )
    poll_response_status = postgresql.ENUM(
        *POLL_RESPONSE_STATUS, name="poll_response_status", create_type=False
    )

    postgresql.ENUM(*POLL_STATUS, name="poll_status").create(op.get_bind(), checkfirst=False)
    postgresql.ENUM(*POLL_VISIBILITY, name="poll_visibility").create(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(*POLL_RESPONSE_MODE, name="poll_response_mode").create(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(*POLL_OPTION_TYPE, name="poll_option_type").create(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(*POLL_RESPONSE_STATUS, name="poll_response_status").create(
        op.get_bind(), checkfirst=False
    )

    op.create_table(
        "polls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "share_token",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description_short", sa.String(), nullable=True),
        sa.Column("description_long", sa.Text(), nullable=True),
        sa.Column("status", poll_status, server_default="DRAFT", nullable=False),
        sa.Column("visibility", poll_visibility, server_default="PRIVATE", nullable=False),
        sa.Column(
            "response_mode", poll_response_mode, server_default="YES_NO_MAYBE", nullable=False
        ),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "allow_edit_responses", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("edit_responses_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_delete_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "allow_custom_options", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("is_mandatory", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("allow_guests", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("max_guests", sa.Integer(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_polls_share_token", "share_token", unique=True),
        sa.Index("ix_polls_status", "status"),
        sa.Index("ix_polls_created_by_id", "created_by_id"),
        sa.Index("ix_polls_starts_at", "starts_at"),
        sa.Index("ix_polls_ends_at", "ends_at"),
        sa.Index("ix_polls_auto_delete_at", "auto_delete_at"),
    )

    op.create_table(
        "poll_options",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("option_type", poll_option_type, nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("date_value", sa.Date(), nullable=True),
        sa.Column("datetime_value", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text_value", sa.String(), nullable=True),
        sa.Column("is_custom", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["poll_id"], ["polls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_poll_options_poll_id", "poll_id"),
        sa.Index("ix_poll_options_poll_id_sort_order", "poll_id", "sort_order"),
        sa.CheckConstraint(
            "("
            "(option_type = 'DATE' AND date_value IS NOT NULL "
            "AND datetime_value IS NULL AND text_value IS NULL) "
            "OR (option_type = 'DATETIME' AND datetime_value IS NOT NULL "
            "AND date_value IS NULL AND text_value IS NULL) "
            "OR (option_type = 'TEXT' AND text_value IS NOT NULL "
            "AND date_value IS NULL AND datetime_value IS NULL)"
            ")",
            name="ck_poll_options_value_matches_type",
        ),
    )

    op.create_table(
        "poll_responses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["poll_id"], ["polls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("poll_id", "user_id", name="uq_poll_responses_poll_user"),
        sa.Index("ix_poll_responses_poll_id", "poll_id"),
        sa.Index("ix_poll_responses_user_id", "user_id"),
    )

    op.create_table(
        "poll_response_options",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("response_id", sa.BigInteger(), nullable=False),
        sa.Column("option_id", sa.BigInteger(), nullable=False),
        sa.Column("status", poll_response_status, nullable=False),
        sa.Column("guest_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["response_id"], ["poll_responses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["option_id"], ["poll_options.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "response_id", "option_id", name="uq_poll_response_options_response_option"
        ),
        sa.CheckConstraint("guest_count >= 0", name="ck_poll_response_options_guest_count_nonneg"),
        sa.Index("ix_poll_response_options_response_id", "response_id"),
        sa.Index("ix_poll_response_options_option_id", "option_id"),
    )

    op.create_table(
        "poll_users",
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["polls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("poll_id", "user_id"),
        sa.Index("ix_poll_users_user_id", "user_id"),
    )

    op.create_table(
        "poll_groups",
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["polls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("poll_id", "group_id"),
        sa.Index("ix_poll_groups_group_id", "group_id"),
    )

    for table in ("users", "groups", "polls", "poll_options", "poll_responses"):
        op.execute(
            f"""
            CREATE TRIGGER set_updated_at_{table}
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    op.drop_table("poll_groups")
    op.drop_table("poll_users")
    op.drop_table("poll_response_options")
    op.drop_table("poll_responses")
    op.drop_table("poll_options")
    op.drop_table("polls")

    for enum_name in (
        "poll_response_status",
        "poll_option_type",
        "poll_response_mode",
        "poll_visibility",
        "poll_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name};")

    op.drop_table("user_groups")
    op.drop_table("groups")
    op.drop_table("users")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
