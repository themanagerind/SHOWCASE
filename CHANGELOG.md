# Changelog

## Step 1 — Scaffold, DB schema, OTP + JWT auth
- FastAPI backend scaffold (`backend/app`: core, db, models, schemas, services, api/v1, workers, ml), docker-compose (api, postgis, redis, celery worker/beat), `.env.example`.
- All 24 SPEC §6 tables as SQLAlchemy models + Alembic `0001` migration (PostGIS, GiST on `retailers.location`, money in paise, UUID PKs, timestamps).
- `credit_ledger`, `subscription_audit_log`, `product_swaps` are append-only at DB level (trigger blocks UPDATE/DELETE); plans seeded at ₹199/₹399/₹999.
- Phone OTP login (hashed codes in Redis, per-phone/per-IP rate limits, 5-attempt lockout) + JWT access/refresh with rotation and reuse detection.
- 34 pytest tests (OTP, tokens, RBAC basics, migration guarantees) against real Postgres+PostGIS with an injectable clock.

## Step 2 — Retailer profile, products, plan limits, weekly slot-swap
- Retailer shop: create (one per phone), view/edit profile, public storefront `/api/v1/retailers/{slug}` (only with TRIAL/ACTIVE/GRACE subscription), share link, WhatsApp `wa.me` link, downloadable QR PNG.
- Products: add / edit / hide / atomic multi-slot swap; plan limits BASIC 5, PRO 20, PREMIUM unlimited, enforced under a row lock so parallel requests cannot exceed the limit.
- Weekly lock: first-time listing is free; afterwards every add/remove/replace is a swap that locks for 7 days (PREMIUM never locks); price/MRP/stock/photos/description editable during lock; swap history recorded.
- Downgrade handling: public page shows the most recent N products until the retailer picks which to keep (`/products/keep`, not a swap); `require_plan(feature)` dependency returns 403.
- 36 new tests (70 total): every SPEC §11 plan-limit / weekly-swap boundary, RBAC between retailers, expired shops, concurrency.
