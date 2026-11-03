"""Add the effective tender close timestamp."""
from alembic import op
import sqlalchemy as sa


revision = "0002_tender_closed_at"
down_revision = "0001_shared_database"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenders",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE tenders SET closed_at = deadline "
        "WHERE status IN ('closed', 'awarded') AND closed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("tenders", "closed_at")
