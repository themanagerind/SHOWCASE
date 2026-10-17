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

## Spec change — bookings move to wallet points (owner decision)
- SPEC §4.4/§4.5 rewritten: no real-money advance, 8-hour refund or store credit; reservations deduct the product's wallet discount in points, never refunded; PURCHASED → points go to the retailer's wallet, FORFEITED → points vanish (record kept).
- Every product now has a mandatory `wallet_discount_paise` (0 < discount ≤ price), editable even during the weekly lock; enforced in schema, service and a DB check constraint.
- Migration `0002`: adds the discount column, drops `retailers.advance_*`, `bookings`, `customer_credits`, `credit_ledger`, `payment_confirmations` (bookings are recreated for points in step 6).
- Customer with fewer points than the discount buys at full price (no partial use); admin retailer reward offers (threshold → % cash, then wallet reset) added to SPEC.
- Wallet + THE-MANAGER code redemption moved to step 6; 72 tests passing.

## Step 3 — Customer signup via retailer link/QR + favourites
- API: `POST /retailers/{slug}/join` (idempotent, keeps first source LINK/QR), customer profile + DPDP consent (`/customers/me`), favourites add/list/remove, retailer's paginated customer list (`/retailers/me/customers`).
- Rules: only live shops can be joined, no joining your own shop, unfavourite keeps the customer in the retailer's list, phone shown to retailer only with consent (masked otherwise), consent unticked by default and withdrawable.
- Frontend started: Next.js 16 PWA (manifest, service worker, icons), Hindi + English, screens for shop page, OTP login, profile/consent, favourites; join flow login → profile → join → favourites.
- E2E run in Chromium at 360px: full QR join flow, no horizontal scroll, Hindi rendering OK, service worker registered; screenshots in `docs/screenshots/step-3/`.
- 14 new backend tests (86 total) + dev demo seed script; frontend typecheck and production build clean, `npm audit` 0 vulnerabilities.
