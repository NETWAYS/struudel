from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from struudel.database import Base
from struudel.models.base import TimestampMixin

if TYPE_CHECKING:
    from struudel.models.poll import Poll
    from struudel.models.poll_response import PollResponseOption
    from struudel.models.user import User


class PollOptionType(StrEnum):
    DATE = "DATE"
    DATETIME = "DATETIME"
    TEXT = "TEXT"


class PollOption(Base, TimestampMixin):
    __tablename__ = "poll_options"
    __table_args__ = (
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

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    poll_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("polls.id", ondelete="CASCADE"),
        index=True,
    )
    option_type: Mapped[PollOptionType] = mapped_column(
        sa.Enum(
            PollOptionType,
            name="poll_option_type",
            values_callable=lambda e: [v.value for v in e],
        ),
    )
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0, server_default=sa.text("0"))

    date_value: Mapped[date | None] = mapped_column(sa.Date())
    datetime_value: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    text_value: Mapped[str | None] = mapped_column(sa.String())

    is_custom: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.text("false")
    )
    created_by_id: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="SET NULL"),
    )

    poll: Mapped[Poll] = relationship("Poll", back_populates="options")
    created_by: Mapped[User | None] = relationship("User", foreign_keys=[created_by_id])
    response_votes: Mapped[list[PollResponseOption]] = relationship(
        "PollResponseOption",
        back_populates="option",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<PollOption id={self.id} poll_id={self.poll_id} "
            f"type={self.option_type.value} sort_order={self.sort_order}>"
        )
