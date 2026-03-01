"""SQLAlchemy ORM models for user authentication and permissions."""

import uuid
from datetime import datetime, timezone

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTableUUID, SQLAlchemyBaseUserTableUUID
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    """OAuth account linked to a user (Google, Microsoft, etc.)."""


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Application user with authentication and profile fields."""

    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount", lazy="joined"
    )
    group_memberships: Mapped[list["UserGroupMember"]] = relationship(
        "UserGroupMember", back_populates="user", lazy="selectin"
    )


class UserGroup(Base):
    """A named group that can be granted access to specific data sources."""

    __tablename__ = "user_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    members: Mapped[list["UserGroupMember"]] = relationship(
        "UserGroupMember", back_populates="group", lazy="selectin"
    )
    datasource_grants: Mapped[list["GroupDatasourceAccess"]] = relationship(
        "GroupDatasourceAccess", back_populates="group", lazy="selectin"
    )


class UserGroupMember(Base):
    """Many-to-many relationship between users and groups."""

    __tablename__ = "user_group_members"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="group_memberships")
    group: Mapped["UserGroup"] = relationship("UserGroup", back_populates="members")


class GroupDatasourceAccess(Base):
    """Which data sources a group is allowed to access."""

    __tablename__ = "group_datasource_access"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    datasource_key: Mapped[str] = mapped_column(
        String(255), primary_key=True, nullable=False
    )

    group: Mapped["UserGroup"] = relationship(
        "UserGroup", back_populates="datasource_grants"
    )
