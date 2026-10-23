"""add travel to work_location_enum

Revision ID: 8c17f2b6d9a1
Revises: 391aab14c372
Create Date: 2026-10-23 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "8c17f2b6d9a1"
down_revision: str | None = "391aab14c372"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow work entries to be marked as travel."""
    op.execute("ALTER TYPE work_location_enum ADD VALUE 'travel'")


def downgrade() -> None:
    """Remove travel from the enum after converting the column back."""
    op.execute(
        "UPDATE work_entries SET location = 'denmark' WHERE location = 'travel'"
    )
    op.execute(
        "CREATE TYPE work_location_enum_old AS ENUM "
        "('home', 'denmark', 'vacation', 'sick')"
    )
    op.execute(
        "ALTER TABLE work_entries ALTER COLUMN location TYPE work_location_enum_old "
        "USING location::text::work_location_enum_old"
    )
    op.execute("DROP TYPE work_location_enum")
    op.execute("ALTER TYPE work_location_enum_old RENAME TO work_location_enum")
