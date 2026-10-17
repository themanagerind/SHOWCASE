# Changelog

## Step 1 — Scaffold, DB schema, OTP + JWT auth
- FastAPI backend scaffold (`backend/app`: core, db, models, schemas, services, api/v1, workers, ml), docker-compose (api, postgis, redis, celery worker/beat), `.env.example`.
- All 24 SPEC §6 tables as SQLAlchemy models + Alembic `0001` migration (PostGIS, GiST on `retailers.location`, money in paise, UUID PKs, timestamps).
- `credit_ledger`, `subscription_audit_log`, `product_swaps` are append-only at DB level (trigger blocks UPDATE/DELETE); plans seeded at ₹199/₹399/₹999.
- Phone OTP login (hashed codes in Redis, per-phone/per-IP rate limits, 5-attempt lockout) + JWT access/refresh with rotation and reuse detection.
- 34 pytest tests (OTP, tokens, RBAC basics, migration guarantees) against real Postgres+PostGIS with an injectable clock.
