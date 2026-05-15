from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from struudel.database import Base
from struudel.models.associations import poll_groups, poll_users
from struudel.models.base import TimestampMixin

if TYPE_CHECKING:
    from struudel.models.group import Group
    from struudel.models.poll_option import PollOption
    from struudel.models.poll_response import PollResponse
    from struudel.models.user import User


class PollStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    TEMPLATE = "TEMPLATE"


class PollVisibility(StrEnum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class PollResponseMode(StrEnum):
    YES_NO_MAYBE = "YES_NO_MAYBE"
    SINGLE_CHOICE = "SINGLE_CHOICE"
    MULTI_CHOICE = "MULTI_CHOICE"


class Poll(Base, TimestampMixin):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    share_token: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        unique=True,
        index=True,
        default=uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )

    title: Mapped[str] = mapped_column(sa.String())
    description_short: Mapped[str | None] = mapped_column(sa.String())
    description_long: Mapped[str | None] = mapped_column(sa.Text())

    status: Mapped[PollStatus] = mapped_column(
        sa.Enum(
            PollStatus,
            name="poll_status",
            values_callable=lambda e: [v.value for v in e],
        ),
        default=PollStatus.DRAFT,
        server_default=PollStatus.DRAFT.value,
        index=True,
    )
    visibility: Mapped[PollVisibility] = mapped_column(
        sa.Enum(
            PollVisibility,
            name="poll_visibility",
            values_callable=lambda e: [v.value for v in e],
        ),
        default=PollVisibility.PRIVATE,
        server_default=PollVisibility.PRIVATE.value,
    )
    response_mode: Mapped[PollResponseMode] = mapped_column(
        sa.Enum(
            PollResponseMode,
            name="poll_response_mode",
            values_callable=lambda e: [v.value for v in e],
        ),
        default=PollResponseMode.YES_NO_MAYBE,
        server_default=PollResponseMode.YES_NO_MAYBE.value,
    )

    created_by_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )

    starts_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), index=True)

    allow_edit_responses: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.text("false")
    )
    edit_responses_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    auto_delete_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), index=True)

    allow_custom_options: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.text("false")
    )
    is_mandatory: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.text("false")
    )

    allow_guests: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.text("false")
    )
    max_guests: Mapped[int | None] = mapped_column(sa.Integer, default=None)

    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )

    created_by: Mapped[User] = relationship("User", foreign_keys=[created_by_id])
    options: Mapped[list[PollOption]] = relationship(
        "PollOption",
        back_populates="poll",
        cascade="all, delete-orphan",
        order_by="PollOption.sort_order",
    )
    responses: Mapped[list[PollResponse]] = relationship(
        "PollResponse",
        back_populates="poll",
        cascade="all, delete-orphan",
    )
    invited_users: Mapped[list[User]] = relationship("User", secondary=poll_users)
    invited_groups: Mapped[list[Group]] = relationship("Group", secondary=poll_groups)

    def __repr__(self) -> str:
        return f"<Poll id={self.id} title={self.title!r} status={self.status.value}>"
