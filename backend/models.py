"""SQLAlchemy ORM models for the work location tracker backend."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Index, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base — imported by Alembic for autogenerate."""


class WorkEntry(Base):
    """One logged work-location entry per calendar day."""

    __tablename__ = "work_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    location: Mapped[str] = mapped_column(
        Enum(
            "home",
            "denmark",
            "vacation",
            "sick",
            name="work_location_enum",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # B-tree index on work_date for efficient monthly range queries
        Index("ix_work_entries_work_date", "work_date"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"WorkEntry(id={self.id!r}, work_date={self.work_date!r}, "
            f"location={self.location!r})"
        )
