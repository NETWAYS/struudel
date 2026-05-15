import sqlalchemy as sa

from struudel.database import Base

user_group = sa.Table(
    "user_groups",
    Base.metadata,
    sa.Column(
        "user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    ),
    sa.Column(
        "group_id", sa.BigInteger, sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    ),
    sa.Index("ix_user_groups_group_id", "group_id"),
)


poll_users = sa.Table(
    "poll_users",
    Base.metadata,
    sa.Column(
        "poll_id", sa.BigInteger, sa.ForeignKey("polls.id", ondelete="CASCADE"), primary_key=True
    ),
    sa.Column(
        "user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    ),
    sa.Index("ix_poll_users_user_id", "user_id"),
)


poll_groups = sa.Table(
    "poll_groups",
    Base.metadata,
    sa.Column(
        "poll_id", sa.BigInteger, sa.ForeignKey("polls.id", ondelete="CASCADE"), primary_key=True
    ),
    sa.Column(
        "group_id", sa.BigInteger, sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    ),
    sa.Index("ix_poll_groups_group_id", "group_id"),
)
