# Database setup

Run these commands from `backend/` after copying the repository `.env.example`
to the repository root as `.env`, then setting `DATABASE_URL`, `FERNET_KEY`,
and `RECEIPT_SALT`:

```powershell
python -m pip install -r requirements.txt
alembic upgrade head
```

To create local demo users and a draft tender, set `SEED_ADMIN_EMAIL`,
`SEED_ADMIN_PASSWORD`, `SEED_VENDOR_EMAIL`, and `SEED_VENDOR_PASSWORD` in
the environment, then run:

```powershell
python -m scripts.seed_data
```

Seed passwords use the same bcrypt format as the vendor authentication module.
The script is idempotent and never prints passwords. `SEED_DEMO_TENDER=0` skips
the sample tender. It is clearly marked as demo data and starts in `draft`.

The `/admin/audit-logs` endpoint is admin-only and supports `limit`, `offset`,
`tender_id`, `actor_id`, and `action` filters. Request middleware stores the
method, matched route template, tender ID when available, response status,
duration, actor ID when a verified token is available, and client IP. It never
stores request bodies, tokens, or query-string values. Audit events are
protected from update and deletion by ORM guards and database triggers on
PostgreSQL, MySQL/MariaDB, and SQLite.

The initial migration covers the shared Person 4 tables. The `bids` table stays
with the auction module; that module must add its own migration before its
endpoints are deployed. Alembic registers `app/auction/models.py` for
autogeneration when present. The shared `Award` model stores the winning bid ID
and the award service validates that bid against the tender before creating the
award.

For a closed-tender collusion demo after migrations, run:

    python -m scripts.demo_seed --admin-password "choose-a-demo-password" --vendor-password "choose-a-demo-password"

This creates one admin, three vendors, and three closed tenders. The same vendor
pair is 1.50%, 1.60%, and 1.80% apart across the tenders. The fixed demo emails
are printed with the tender IDs. Rerunning the seed reuses the dataset and does
not create duplicate tenders.

Run the Week 6 authenticated API flow and edge cases in a disposable PostgreSQL
schema with:

    python -m scripts.week6_e2e

The test runner drops its temporary schema when it finishes.

For a fresh database, apply the shared schema and create the auction tables
before starting the API:

    alembic upgrade head
    python -m scripts.create_tables

The second command creates the bids table and installs its database lock. It
also verifies the collusion-flag locks.

The repository root .env must also define JWT_SECRET; the backend refuses to
start when that secret is missing.
