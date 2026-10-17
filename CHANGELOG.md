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

## Step 4 — Discovery with PostGIS and plan-based visibility
- `GET /api/v1/discovery/shops`: live subscriptions only; PINCODE/CITY/INDIA scope from the plan; `ST_DWithin` radius filter + `ST_Distance` on the GiST-indexed geography column; works logged-out (GPS + optional pincode/city) and logged-in (profile pincode/city/radius always win).
- Ranking (owner decision): radius split into 6 rings → ring, rating, plan priority, exact distance. No-GPS fallback: profile pincode/city, ordered by rating then plan.
- Customer profile gets a saved search radius (2/5/10/25/50 km, default 5); category filter; favourite flag per result.
- Frontend: "आस-पास की दुकानें" screen (GPS with fallback, radius chips, category filter, favourite heart, load more); radius in profile; logout moved to profile; home/PWA start on discovery.
- 24 new tests (110 total) incl. exact radius boundary (4990 m in / 5010 m out), every scope, expired/no-plan hidden, ring ranking; browser e2e at 360px with and without GPS; screenshots in `docs/screenshots/step-4/`.

## Step 4b — Product search (PREMIUM all India, PRO in city)
- `GET /api/v1/discovery/products?q=`: PREMIUM products from all over India (no radius), PRO products only in the customer's city and radius, BASIC never (owner decision; SPEC §4.8a).
- Spelling-tolerant Hindi/English search with `pg_trgm` (migration `0003`: trigram index on product name + category index); downgrade limit and live-subscription rules respected.
- Ranking: word match → contains → fuzzy, then distance ring (far PREMIUM shops after nearer ones), then rating, then plan.
- Two-phase query (index-only id lookup, then ranking on that set) after profiling: ~9 ms per search on 50k products / 200 shops; very generic words (matching every product) ~0.5 s — candidate cap 2,000.
- Frontend: "दुकानें | प्रोडक्ट्स" tabs on the discovery screen; 18 new tests (128 total); e2e screenshot `docs/screenshots/step-4/4-product-search-hi.png`.

## Retailer screens (before step 5)
- Retailer signup: create shop (name, auto shop-link, category, address, pincode/city, WhatsApp, UPI, payment link, GPS shop location).
- Dashboard: plan + status, active products vs plan limit, customer count, lock status banner (first listing free / 7-day lock / locked until … / no lock on PREMIUM), "no plan" warning.
- Products: add (rupees → paise, discount ≤ price checked), edit (name locked during the weekly lock), hide, multi-slot swap with lock confirmation; hidden products listed.
- Share & QR (copy link, WhatsApp share, QR download) and customer list (phone only with consent). Header shows "मेरी दुकान" for retailers.
- API: `/retailers/me` now also returns `swap_locks`, `first_listing_free`, `active_products`, `max_products`, `customers_count`. Browser e2e of the whole retailer journey at 360px; screenshots in `docs/screenshots/retailer/`.
