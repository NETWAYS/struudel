from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from struudel.database import Base
from struudel.models.base import TimestampMixin

if TYPE_CHECKING:
    from struudel.models.poll import Poll
    from struudel.models.poll_option import PollOption
    from struudel.models.user import User


class PollResponseStatus(StrEnum):
    YES = "YES"
    NO = "NO"
    MAYBE = "MAYBE"


class PollResponse(Base, TimestampMixin):
    __tablename__ = "poll_responses"
    __table_args__ = (
        sa.UniqueConstraint("poll_id", "user_id", name="uq_poll_responses_poll_user"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    poll_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("polls.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
    comment: Mapped[str | None] = mapped_column(sa.Text())

    poll: Mapped[Poll] = relationship("Poll", back_populates="responses")
    user: Mapped[User] = relationship("User")
    option_votes: Mapped[list[PollResponseOption]] = relationship(
        "PollResponseOption",
        back_populates="response",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<PollResponse id={self.id} poll_id={self.poll_id} user_id={self.user_id}>"


class PollResponseOption(Base):
    __tablename__ = "poll_response_options"
    __table_args__ = (
        sa.UniqueConstraint(
            "response_id", "option_id", name="uq_poll_response_options_response_option"
        ),
        sa.CheckConstraint("guest_count >= 0", name="ck_poll_response_options_guest_count_nonneg"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    response_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("poll_responses.id", ondelete="CASCADE"),
        index=True,
    )
    option_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("poll_options.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[PollResponseStatus] = mapped_column(
        sa.Enum(
            PollResponseStatus,
            name="poll_response_status",
            values_callable=lambda e: [v.value for v in e],
        ),
    )
    guest_count: Mapped[int] = mapped_column(sa.Integer, default=0, server_default=sa.text("0"))

    response: Mapped[PollResponse] = relationship("PollResponse", back_populates="option_votes")
    option: Mapped[PollOption] = relationship("PollOption", back_populates="response_votes")

    def __repr__(self) -> str:
        return (
            f"<PollResponseOption id={self.id} response_id={self.response_id} "
            f"option_id={self.option_id} status={self.status.value}>"
        )
