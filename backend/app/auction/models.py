# app/auction/models.py
# Day 2: the Bid table.
#   L1 -> only an ENCRYPTED amount is stored (no plain amount column exists)
#   L2 -> insert-only: a saved bid can't be edited or deleted, only revised
#         by inserting a NEW row that points back to the old one (revision_of)
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKeyConstraint,Index, Integer, String, Text,
    UniqueConstraint, event,text
)
from sqlalchemy.orm import Mapped, Session, mapped_column, validates
from app.auction.db_lock import install_bid_lock, install_flags_lock
from app.database import Base


class BidLockedError(Exception):
    """Raised when code tries to UPDATE or DELETE a saved bid."""


class Bid(Base):
    __tablename__ = "bids"
    __table_args__ = (
        CheckConstraint("length(bid_hash) = 64", name="ck_bids_hash_len"),
        CheckConstraint("tender_id > 0 AND vendor_id > 0", name="ck_bids_ids_positive"),
        # PostgreSQL needs a UNIQUE target for the composite foreign key below.
        UniqueConstraint("id", "tender_id", "vendor_id", name="uq_bids_id_tender_vendor"),
        # A bid can be revised at most once -> history is one straight line, no forks.
        UniqueConstraint("revision_of", name="uq_bids_revision_of"),
        # A revision must belong to the SAME vendor and the SAME tender as the bid it
        # replaces. (If revision_of is NULL, PostgreSQL skips this check.)
        ForeignKeyConstraint(
            ["revision_of", "tender_id", "vendor_id"],
            ["bids.id", "bids.tender_id", "bids.vendor_id"],
            name="fk_bids_revision_same_owner",
        ),
        Index(
            "uq_bids_one_original_per_vendor", "tender_id", "vendor_id",
            unique=True, postgresql_where=text("revision_of IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # plain integers today; real foreign keys are added on Day 8 (see notes)
    tender_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vendor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # L1: Fernet token. There is deliberately NO plain amount column.
    bid_amount_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # L2: SHA-256 receipt (64 hex chars), unique per bid.
    bid_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # L9 fields, filled by Person 2's login/bid form on Day 8.
    device_fingerprint: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))

    # L2: a revision is a NEW row pointing at the bid it replaces
    # (same tender + same vendor, enforced by fk_bids_revision_same_owner).
    revision_of: Mapped[int | None] = mapped_column(Integer)

    # The caller supplies this so the SAME time goes into the receipt hash.
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @validates("submitted_at")
    def _require_utc(self, key, value):
        """The receipt hashes this time as text, so it must be one exact format.
        A naive or non-UTC datetime would make the receipt fail to verify later."""
        if value.utcoffset() != timedelta(0):
            raise ValueError(
                "submitted_at must be a UTC datetime, e.g. datetime.now(timezone.utc)"
            )
        return value

    def submitted_at_iso(self) -> str:
        """UTC ISO string, identical to the one used to build the receipt."""
        return self.submitted_at.astimezone(timezone.utc).isoformat()

    @property
    def token_preview(self) -> str:
        """First characters of the token, just to show it is encrypted."""
        return self.bid_amount_encrypted[:25] + "..."

# ---- Layer 2 (Day 4): whenever create_all makes the bids table, lock it too ----
@event.listens_for(Bid.__table__, "after_create")
def _lock_new_table(target, connection, **kw):
    install_bid_lock(connection)


# ---- Layer 1 (Day 2): insert-only guard in Python (raw SQL is stopped by Layer 2) ----

@event.listens_for(Bid, "before_update")
def _block_update(mapper, connection, target):
    raise BidLockedError("Bids are insert-only: submit a revision instead of editing.")


@event.listens_for(Bid, "before_delete")
def _block_delete(mapper, connection, target):
    raise BidLockedError("Bids are insert-only: a submitted bid can't be deleted.")


@event.listens_for(Session, "do_orm_execute")
def _block_bulk(state):
    """Bulk update()/delete() skip the normal events, so catch them here."""
    if (state.is_update or state.is_delete) and any(
        m.class_ is Bid for m in state.all_mappers
    ):
        raise BidLockedError("Bulk UPDATE/DELETE on bids is not allowed.")

    # ---- Day 6: the CollusionFlags table (L10). One row = one rule + one tender + one vendor or pair ----
class FlagLockedError(Exception):
    """Raised when code tries to UPDATE or DELETE a saved collusion flag."""


class CollusionFlag(Base):
    __tablename__ = "collusion_flags"
    __table_args__ = (
        CheckConstraint("rule IN ('repeated_undercutting', 'high_win_share')", name="ck_flags_rule"),
        # rule 1 is always about a PAIR of vendors, rule 2 always about ONE vendor
        CheckConstraint("(rule = 'repeated_undercutting') = (vendor_id_b IS NOT NULL)",
                        name="ck_flags_rule_shape"),
        # ids positive; a pair is stored sorted, so (501, 503) and (503, 501) can't both exist
        CheckConstraint("tender_id > 0 AND vendor_id_a > 0 AND "
                        "(vendor_id_b IS NULL OR vendor_id_a < vendor_id_b)", name="ck_flags_ids"),
        # the same flag is saved ONCE however often the scan runs. NULLs never clash in a
        # UNIQUE index, so the one-vendor rows (vendor_id_b IS NULL) get their own index.
        Index("uq_flags_pair", "rule", "tender_id", "vendor_id_a", "vendor_id_b",
              unique=True, postgresql_where=text("vendor_id_b IS NOT NULL")),
        Index("uq_flags_single", "rule", "tender_id", "vendor_id_a",
              unique=True, postgresql_where=text("vendor_id_b IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule: Mapped[str] = mapped_column(String(40), nullable=False)
    # plain integers like Bid; real foreign keys to Person 1's tables on Day 8
    tender_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vendor_id_a: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vendor_id_b: Mapped[int | None] = mapped_column(Integer, index=True)   # NULL for rule 2
    flag_reason: Mapped[str] = mapped_column(Text, nullable=False)          # evidence, no amounts
    flagged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# Layer 2 (database): whenever create_all makes collusion_flags, lock it too.
@event.listens_for(CollusionFlag.__table__, "after_create")
def _lock_new_flags_table(target, connection, **kw):
    install_flags_lock(connection)


# Layer 1 (Python): a friendly error before the database even sees the statement.
@event.listens_for(CollusionFlag, "before_update")
def _block_flag_update(mapper, connection, target):
    raise FlagLockedError("Collusion flags are insert-only: a saved flag can't be edited.")


@event.listens_for(CollusionFlag, "before_delete")
def _block_flag_delete(mapper, connection, target):
    raise FlagLockedError("Collusion flags are insert-only: a saved flag can't be deleted.")


@event.listens_for(Session, "do_orm_execute")
def _block_flag_bulk(state):
    if (state.is_update or state.is_delete) and any(
        m.class_ is CollusionFlag for m in state.all_mappers
    ):
        raise FlagLockedError("Bulk UPDATE/DELETE on collusion_flags is not allowed.")