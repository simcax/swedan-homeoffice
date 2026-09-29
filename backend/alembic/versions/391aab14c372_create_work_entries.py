"""create work_entries table with work_location_enum

Revision ID: 391aab14c372
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers — used by Alembic
# ---------------------------------------------------------------------------

revision: str = "391aab14c372"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Upgrade: create enum type, table, and index
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Create the work_location_enum type, work_entries table, and index."""
    # Create the PostgreSQL enum type first so the column can reference it.
    work_location_enum = sa.Enum(
        "home",
        "denmark",
        "vacation",
        "sick",
        name="work_location_enum",
    )
    work_location_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "work_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column(
            "location",
            sa.Enum(
                "home",
                "denmark",
                "vacation",
                "sick",
                name="work_location_enum",
                create_type=False,  # already created above
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_date"),
    )

    op.create_index(
        "ix_work_entries_work_date",
        "work_entries",
        ["work_date"],
        unique=False,
    )


# ---------------------------------------------------------------------------
# Downgrade: drop table, index (auto-dropped), and enum type
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Drop the work_entries table and work_location_enum type."""
    op.drop_index("ix_work_entries_work_date", table_name="work_entries")
    op.drop_table("work_entries")

    # Drop the enum type after the table is gone.
    work_location_enum = sa.Enum(
        "home",
        "denmark",
        "vacation",
        "sick",
        name="work_location_enum",
    )
    work_location_enum.drop(op.get_bind(), checkfirst=True)
