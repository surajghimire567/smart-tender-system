## Day 4 — Lock bids + revisions (L2)
- A trigger is a function PostgreSQL runs on every matching statement, from ANY client.
- bids_block_update_delete: BEFORE UPDATE OR DELETE, FOR EACH ROW -> RAISE (SQLSTATE 23001).
- bids_block_truncate: BEFORE TRUNCATE, FOR EACH STATEMENT (row triggers never see TRUNCATE).
- Two layers: ORM guard (friendly error, our code) + DB trigger (the real wall, everyone).
- A revision is a NEW row (revision_of = old id) with a new receipt; the old row never changes.
- Races are decided by DB constraints (uq_bids_revision_of), not by Python checks.
- Limit: owner/superuser can disable triggers or drop the table -> least-privilege API role (future).