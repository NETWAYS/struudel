from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from struudel.database import Base
from struudel.models.associations import user_group
from struudel.models.base import TimestampMixin

if TYPE_CHECKING:
    from struudel.models.group import Group


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    preferred_username: Mapped[str] = mapped_column(sa.String(), unique=True)
    external_id: Mapped[str] = mapped_column(sa.String(), unique=True)
    name: Mapped[str] = mapped_column(sa.String())
    given_name: Mapped[str | None] = mapped_column(sa.String())
    family_name: Mapped[str | None] = mapped_column(sa.String())
    email: Mapped[str] = mapped_column(sa.String(), unique=True)
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=sa.text("true")
    )
    is_superuser: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.text("false")
    )
    profile: Mapped[str | None] = mapped_column(sa.String())
    picture: Mapped[str | None] = mapped_column(sa.String())
    cached_picture: Mapped[bytes | None] = mapped_column(sa.LargeBinary, deferred=True)
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    groups: Mapped[list[Group]] = relationship(
        "Group", secondary=user_group, back_populates="users"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} preferred_username={self.preferred_username!r}>"
