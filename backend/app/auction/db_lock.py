# app/auction/db_lock.py
# Day 4 (L2, Layer 2): make PostgreSQL ITSELF refuse UPDATE, DELETE and TRUNCATE
# on the bids table. Works against everyone: our API, psql, pgAdmin, other scripts.
# The Day 2 ORM guard (models.py) is Layer 1; keep both.
from sqlalchemy import text

TABLE = "bids"
FUNCTION = "bids_insert_only"
ROW_TRIGGER = "bids_block_update_delete"
TRUNCATE_TRIGGER = "bids_block_truncate"

# One trigger function for both triggers. TG_OP is 'UPDATE', 'DELETE' or 'TRUNCATE'.
# The message is built with || (no % anywhere): the Python driver treats % as a placeholder.
# restrict_violation = SQLSTATE 23001 -> psycopg2 / SQLAlchemy raise IntegrityError.
LOCK_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = '{TABLE} is insert-only: ' || TG_OP || ' is not allowed',
        ERRCODE = 'restrict_violation',
        HINT    = 'To change a bid, INSERT a revision row (revision_of = old bid id).';
END;
$$ LANGUAGE plpgsql
"""

# name -> when it fires. Row triggers never see TRUNCATE, so it needs its own trigger.
LOCK_TRIGGERS = {
    ROW_TRIGGER: "BEFORE UPDATE OR DELETE ON bids FOR EACH ROW",
    TRUNCATE_TRIGGER: "BEFORE TRUNCATE ON bids FOR EACH STATEMENT",
}


def install_bid_lock(connection) -> None:
    """Create the function + both triggers. Safe to run any number of times.
    `connection` is a SQLAlchemy Connection; the caller commits (engine.begin())."""
    connection.execute(text(LOCK_FUNCTION))
    for name, when in LOCK_TRIGGERS.items():
        connection.execute(text(f"DROP TRIGGER IF EXISTS {name} ON {TABLE}"))
        connection.execute(text(f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION {FUNCTION}()"))


def lock_status(connection) -> dict[str, str]:
    """{'trigger name': 'ON' | 'OFF' | 'MISSING'} read from PostgreSQL's catalog.
    tgenabled: 'O' / 'A' = fires normally. 'D' = someone ran ALTER TABLE ... DISABLE TRIGGER.
    'R' = fires only in replica mode, so for normal sessions it is OFF too."""
    rows = connection.execute(text(
        "SELECT tgname, tgenabled FROM pg_trigger "
        "WHERE tgrelid = to_regclass(:t) AND NOT tgisinternal"), {"t": TABLE}).all()
    found = {name: flag for name, flag in rows}
    return {
        name: "MISSING" if name not in found else ("ON" if found[name] in ("O", "A") else "OFF")
        for name in LOCK_TRIGGERS
    }