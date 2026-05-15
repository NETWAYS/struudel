from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from struudel.database import Base
from struudel.models.associations import user_group
from struudel.models.base import TimestampMixin

if TYPE_CHECKING:
    from struudel.models.user import User


class Group(Base, TimestampMixin):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(sa.String(), unique=True)
    name: Mapped[str] = mapped_column(sa.String())
    external_id: Mapped[str | None] = mapped_column(sa.String(), unique=True)
    hidden: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.text("false"))

    users: Mapped[list[User]] = relationship("User", secondary=user_group, back_populates="groups")

    def __repr__(self) -> str:
        return f"<Group id={self.id} canonical_name={self.canonical_name!r}>"
