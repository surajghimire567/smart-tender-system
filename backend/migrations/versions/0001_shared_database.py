"""Create shared users, tenders, awards, flags, and append-only audit tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_shared_database"
down_revision = None
branch_labels = None
depends_on = None


def _create_audit_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "CREATE FUNCTION reject_audit_log_mutation() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_logs are append-only'; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs "
            "FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation()"
        )
        op.execute(
            "CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs "
            "FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation()"
        )
    elif dialect in {"mysql", "mariadb"}:
        op.execute(
            "CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs "
            "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs are append-only'"
        )
        op.execute(
            "CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs "
            "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs are append-only'"
        )
    elif dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs "
            "BEGIN SELECT RAISE(ABORT, 'audit_logs are append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs "
            "BEGIN SELECT RAISE(ABORT, 'audit_logs are append-only'); END"
        )


def _drop_audit_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs")
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS reject_audit_log_mutation()")
    elif dialect in {"mysql", "mariadb"}:
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update")
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_delete")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update")
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_delete")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("registration_number", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'vendor')", name="ck_users_role"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("registration_number", name="uq_users_registration_number"),
    )
    op.create_table(
        "tenders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("base_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("ceiling_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'published', 'closed', 'awarded')", name="ck_tenders_status"),
        sa.CheckConstraint("base_price > 0 AND ceiling_price >= base_price", name="ck_tenders_price_bounds"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_tenders_created_by", "tenders", ["created_by"])
    op.create_index("ix_tenders_status_deadline", "tenders", ["status", "deadline"])

    op.create_table(
        "awards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("winning_bid_id", sa.Integer(), nullable=False),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("winning_bid_id > 0", name="ck_awards_winning_bid_positive"),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tender_id", name="uq_awards_tender"),
    )
    op.create_index("ix_awards_tender_id", "awards", ["tender_id"])

    op.create_table(
        "collusion_flags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id_a", sa.Integer(), nullable=False),
        sa.Column("vendor_id_b", sa.Integer(), nullable=False),
        sa.Column("flag_reason", sa.Text(), nullable=False),
        sa.Column("flagged_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("vendor_id_a <> vendor_id_b", name="ck_flags_distinct_vendors"),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vendor_id_a"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vendor_id_b"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_collusion_flags_tender_id", "collusion_flags", ["tender_id"])
    op.create_index("ix_collusion_flags_tender_time", "collusion_flags", ["tender_id", "flagged_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tender_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.CheckConstraint("length(trim(action)) > 0", name="ck_audit_logs_action_nonempty"),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_audit_logs_tender_id", "audit_logs", ["tender_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_action_timestamp", "audit_logs", ["action", "timestamp"])
    op.create_index("ix_audit_logs_tender_timestamp", "audit_logs", ["tender_id", "timestamp"])
    op.create_index("ix_audit_logs_actor_timestamp", "audit_logs", ["actor_id", "timestamp"])
    _create_audit_triggers()


def downgrade() -> None:
    _drop_audit_triggers()
    op.drop_table("audit_logs")
    op.drop_index("ix_collusion_flags_tender_time", table_name="collusion_flags")
    op.drop_table("collusion_flags")
    op.drop_table("awards")
    op.drop_index("ix_tenders_status_deadline", table_name="tenders")
    op.drop_table("tenders")
    op.drop_table("users")
