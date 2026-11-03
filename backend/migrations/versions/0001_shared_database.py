"""Create shared users, tenders, awards, flags, and append-only audit tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_shared_database"
down_revision = None
branch_labels = None
depends_on = None

_ADOPTION_TABLE = "_smart_tender_migration_adoptions"
_REVISION = "0001_shared_database"


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _adoption_table() -> sa.Table:
    return sa.Table(
        _ADOPTION_TABLE,
        sa.MetaData(),
        sa.Column("revision", sa.String(length=50), primary_key=True),
        sa.Column("object_name", sa.String(length=100), primary_key=True),
    )


def _remember_adopted_flags() -> None:
    if not _has_table(_ADOPTION_TABLE):
        op.create_table(
            _ADOPTION_TABLE,
            sa.Column("revision", sa.String(length=50), nullable=False),
            sa.Column("object_name", sa.String(length=100), nullable=False),
            sa.PrimaryKeyConstraint("revision", "object_name"),
        )
    table = _adoption_table()
    bind = op.get_bind()
    exists = bind.execute(
        sa.select(table.c.object_name).where(
            table.c.revision == _REVISION,
            table.c.object_name == "collusion_flags",
        )
    ).first()
    if exists is None:
        op.bulk_insert(
            table,
            [{"revision": _REVISION, "object_name": "collusion_flags"}],
        )


def _flags_were_adopted() -> bool:
    if not _has_table(_ADOPTION_TABLE):
        return False
    table = _adoption_table()
    return (
        op.get_bind()
        .execute(
            sa.select(table.c.object_name).where(
                table.c.revision == _REVISION,
                table.c.object_name == "collusion_flags",
            )
        )
        .first()
        is not None
    )


def _drop_adoption_marker() -> None:
    if not _has_table(_ADOPTION_TABLE):
        return
    table = _adoption_table()
    bind = op.get_bind()
    bind.execute(
        sa.delete(table).where(
            table.c.revision == _REVISION,
            table.c.object_name == "collusion_flags",
        )
    )
    if bind.execute(sa.select(table.c.object_name).limit(1)).first() is None:
        op.drop_table(_ADOPTION_TABLE)


def _create_flag_indexes() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {
        index["name"]
        for index in inspector.get_indexes("collusion_flags")
    }
    for name, column in (
        ("ix_collusion_flags_tender_id", "tender_id"),
        ("ix_collusion_flags_vendor_id_a", "vendor_id_a"),
        ("ix_collusion_flags_vendor_id_b", "vendor_id_b"),
    ):
        if name not in existing:
            op.create_index(name, "collusion_flags", [column])

    dialect = op.get_bind().dialect.name
    where_args = {}
    if dialect == "postgresql":
        where_args = {"postgresql_where": sa.text("vendor_id_b IS NOT NULL")}
    elif dialect == "sqlite":
        where_args = {"sqlite_where": sa.text("vendor_id_b IS NOT NULL")}
    if "uq_flags_pair" not in existing:
        op.create_index(
            "uq_flags_pair",
            "collusion_flags",
            ["rule", "tender_id", "vendor_id_a", "vendor_id_b"],
            unique=True,
            **where_args,
        )

    single_where = {}
    if dialect == "postgresql":
        single_where = {"postgresql_where": sa.text("vendor_id_b IS NULL")}
    elif dialect == "sqlite":
        single_where = {"sqlite_where": sa.text("vendor_id_b IS NULL")}
    if "uq_flags_single" not in existing and dialect in {"postgresql", "sqlite"}:
        op.create_index(
            "uq_flags_single",
            "collusion_flags",
            ["rule", "tender_id", "vendor_id_a"],
            unique=True,
            **single_where,
        )


def _ensure_existing_flags_are_compatible() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]: column
        for column in inspector.get_columns("collusion_flags")
    }
    required = {
        "id",
        "rule",
        "tender_id",
        "vendor_id_a",
        "vendor_id_b",
        "flag_reason",
        "flagged_at",
    }
    missing = sorted(required - columns.keys())
    if missing or not columns.get("vendor_id_b", {}).get("nullable", False):
        detail = ", ".join(missing) if missing else "vendor_id_b must allow NULL"
        raise RuntimeError(
            "Existing collusion_flags is not compatible with the auction model: "
            f"{detail}. Back up and migrate that legacy table before upgrading."
        )
    _create_flag_indexes()
    _remember_adopted_flags()


def _create_collusion_flags() -> None:
    op.create_table(
        "collusion_flags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule", sa.String(length=40), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id_a", sa.Integer(), nullable=False),
        sa.Column("vendor_id_b", sa.Integer(), nullable=True),
        sa.Column("flag_reason", sa.Text(), nullable=False),
        sa.Column(
            "flagged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rule IN ('repeated_undercutting', 'high_win_share')",
            name="ck_flags_rule",
        ),
        sa.CheckConstraint(
            "(rule = 'repeated_undercutting') = (vendor_id_b IS NOT NULL)",
            name="ck_flags_rule_shape",
        ),
        sa.CheckConstraint(
            "tender_id > 0 AND vendor_id_a > 0 AND "
            "(vendor_id_b IS NULL OR vendor_id_a < vendor_id_b)",
            name="ck_flags_ids",
        ),
    )
    _create_flag_indexes()


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

    if _has_table("collusion_flags"):
        _ensure_existing_flags_are_compatible()
    else:
        _create_collusion_flags()

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
    if _flags_were_adopted():
        # Existing collusion flags are evidence. Keep the table and its rows on downgrade.
        _drop_adoption_marker()
    else:
        indexes = {
            index["name"]
            for index in sa.inspect(op.get_bind()).get_indexes("collusion_flags")
        }
        for name in (
            "uq_flags_pair",
            "uq_flags_single",
            "ix_collusion_flags_vendor_id_b",
            "ix_collusion_flags_vendor_id_a",
            "ix_collusion_flags_tender_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="collusion_flags")
        if op.get_bind().dialect.name == "postgresql":
            op.execute("DROP TRIGGER IF EXISTS flags_block_update_delete ON collusion_flags")
            op.execute("DROP TRIGGER IF EXISTS flags_block_truncate ON collusion_flags")
            op.execute("DROP FUNCTION IF EXISTS collusion_flags_insert_only()")
        op.drop_table("collusion_flags")
    op.drop_table("awards")
    op.drop_index("ix_tenders_status_deadline", table_name="tenders")
    op.drop_table("tenders")
    op.drop_table("users")
