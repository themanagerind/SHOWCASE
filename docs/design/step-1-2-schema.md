# Step 1 + 2 — Proposed folder structure and database schema (FOR REVIEW)

> **Note (2026-10-17):** bookings, customer_credits, credit_ledger and payment_confirmations below are SUPERSEDED by the wallet-points model (SPEC §4.4, §4.5, migration 0002). The new booking/wallet tables will be designed in step 6.

Status: **approved** (answers recorded in SPEC.md §4.3). Frontend starts with step 3; steps 1–2 are backend only.

Conventions used everywhere below:

- PK `id UUID DEFAULT gen_random_uuid()`; every table has `created_at`, `updated_at` (`TIMESTAMPTZ`, UTC).
- `deleted_at TIMESTAMPTZ NULL` = soft delete (marked **SD**).
- Money = `BIGINT` paise, column names end in `_paise`.
- Enums are Postgres native enums (listed inline).
- All tables in SPEC §6 are created in the step-1 migration so the FK graph is stable; later steps only
  add columns/indexes through new Alembic revisions. Business logic for later steps is NOT built now.

---

## 1. Folder structure

```
SHOWCASE/
├── SPEC.md  CLAUDE.md  CHANGELOG.md  README.md
├── .gitignore  .env.example
├── docker-compose.yml            # api, db (postgis/postgis:16), redis, worker, beat
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml            # fastapi, sqlalchemy 2, alembic, pydantic v2, celery, pytest, freezegun
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/             # 0001_initial_schema.py (enables postgis + pgcrypto)
│   ├── app/
│   │   ├── main.py               # FastAPI app, routers, OpenAPI
│   │   ├── core/
│   │   │   ├── config.py         # pydantic-settings, env-based
│   │   │   ├── security.py       # JWT encode/decode, OTP hashing
│   │   │   ├── clock.py          # injectable now() — used by ALL business rules (testable time)
│   │   │   ├── dependencies.py   # get_db, get_current_user, require_role, require_plan(feature),
│   │   │   │                     # check_product_limit, check_weekly_lock
│   │   │   ├── rate_limit.py     # Redis-backed OTP rate limiting
│   │   │   └── errors.py
│   │   ├── db/                   # engine, session, Base, mixins (UUID/timestamps/soft-delete)
│   │   ├── models/               # one module per aggregate (user, retailer, product, plan, subscription, booking, credit, order, review, event, lead, notification, admin)
│   │   ├── schemas/              # Pydantic v2 request/response models
│   │   ├── api/                  # auth, retailers, products, bookings, credits, orders, reviews,
│   │   │                         # discovery, analytics, leads, subscriptions, admin
│   │   ├── services/             # otp_service, auth_service, retailer_service, product_service,
│   │   │                         # product_swap_service, plan_service (feature lookup), + later steps
│   │   ├── workers/              # celery_app.py (tasks added in later steps)
│   │   └── ml/                   # placeholder (step 10)
│   └── tests/
│       ├── conftest.py           # test DB (postgis) + transactional fixtures + frozen clock
│       ├── unit/                 # service-layer business-rule tests
│       └── api/                  # endpoint + RBAC tests
└── frontend/                     # Next.js PWA — scaffolded in a later step (see question Q6)
```

---

## 2. Entity overview

```
users 1─1 customers ─┐                     plans 1─* subscriptions *─1 retailers
users 1─1 retailers ─┼─ retailer_customers (favourites, source)    retailers 1─* retailer_offers
users 1─1 admin_users│                                              subscriptions 1─* subscription_payments
                     │                                              subscription_audit_log (append-only)
retailers 1─* products        retailers 1─* product_swaps
customers/retailers/products ─ bookings 1─0..1 customer_credits 1─* credit_ledger (append-only)
bookings 1─* payment_confirmations
orders 1─0..1 shipments      reviews (one per booking/order/credit-use)
shop_events, leads, notifications, platform_settings, refresh_tokens
```

---

## 3. Tables

### Identity & auth (step 1)

**users** (SD)
| column | type | notes |
|---|---|---|
| phone | VARCHAR(15) UNIQUE NOT NULL | E.164, e.g. `+919876543210` |
| name | VARCHAR(120) NULL | |
| preferred_language | VARCHAR(8) DEFAULT 'en' | `en`, `hi`, … |
| is_active | BOOL DEFAULT true | |
| last_login_at | TIMESTAMPTZ NULL | |

Roles are derived from which profile rows exist (`customers`, `retailers`, `admin_users`) and are placed in the JWT.

**refresh_tokens** — `user_id FK`, `jti UNIQUE`, `expires_at`, `revoked_at NULL`, `user_agent`. Rotation on every refresh; reuse of a revoked token revokes the whole family.

OTPs are **not** stored in Postgres: hashed code in Redis with 5-min TTL, max 5 verify attempts, send rate limit per phone (e.g. 3 / 10 min, 10 / day) and per IP. Dev mode logs the OTP; SMS provider sits behind an `SmsSender` interface.

**admin_users** — `user_id FK UNIQUE`, `role ENUM(SUPER_ADMIN, SUPPORT)`, `is_active`.

**customers** (SD)
| column | type | notes |
|---|---|---|
| user_id | UUID FK UNIQUE | |
| pincode | CHAR(6) NULL | |
| city | VARCHAR(80) NULL | stored normalised (lower-case, trimmed) for CITY matching |
| location | GEOGRAPHY(Point,4326) NULL | last known |
| search_radius_km | SMALLINT DEFAULT 5 | |
| contact_consent | BOOL DEFAULT false | "retailer may contact me" (DPDP) |
| consent_at | TIMESTAMPTZ NULL | |

### Retailer & products (step 2)

**retailers** (SD)
| column | type | notes |
|---|---|---|
| user_id | UUID FK UNIQUE | one shop per user (see Q2) |
| slug | VARCHAR(60) UNIQUE | `/{slug}`; reserved words blocked |
| shop_name, category, description | | |
| photos | JSONB DEFAULT '[]' | list of media keys |
| address_line, city, state | | city normalised as above |
| pincode | CHAR(6) NOT NULL | |
| location | GEOGRAPHY(Point,4326) NOT NULL | **GiST index** |
| timings | JSONB | `{"mon":[["10:00","20:00"]], ...}` |
| phone, whatsapp_number | VARCHAR(15) | |
| payment_link, upi_id | TEXT / VARCHAR(80) | retailer's own |
| advance_type | ENUM(PERCENT, FIXED) | used in step 6 |
| advance_value | INT | percent (1–100) or paise |
| products_locked_until | TIMESTAMPTZ NULL | weekly-swap lock |
| rating_avg NUMERIC(3,2), rating_count INT | | denormalised, step 8 |

Indexes: GiST(location), (pincode), (city).

**retailer_customers** — `retailer_id FK`, `customer_id FK`, `source ENUM(LINK, QR, DISCOVERY)`, `is_favourite BOOL DEFAULT true`, `joined_at`. UNIQUE(retailer_id, customer_id).

**products** (SD)
| column | type | notes |
|---|---|---|
| retailer_id | UUID FK | |
| name, description, category | | editable during lock |
| price_paise | BIGINT NOT NULL CHECK ≥ 0 | editable during lock |
| mrp_paise | BIGINT NULL | editable during lock |
| stock_qty | INT DEFAULT 0 | editable during lock |
| photos | JSONB DEFAULT '[]' | editable during lock |
| is_active | BOOL DEFAULT true | counts toward plan slot limit |
| activated_at, deactivated_at | TIMESTAMPTZ | |

Indexes: (retailer_id, is_active). Slot limit enforced in `product_service` inside a transaction with `SELECT … FOR UPDATE` on the retailer row (prevents two parallel adds both getting slot #5).

**product_swaps** (append-only history)
| column | type | notes |
|---|---|---|
| retailer_id | UUID FK | |
| performed_by_user_id | UUID FK | |
| added_product_ids | UUID[] | |
| removed_product_ids | UUID[] | |
| plan_code | VARCHAR(20) | plan at time of swap |
| locked_until | TIMESTAMPTZ NULL | NULL for PREMIUM |

Swap rule implementation: `POST /retailers/me/products/swap` takes `{remove: [ids], add: [new products]}` and applies it atomically, checks the plan limit on the resulting set, writes `product_swaps`, sets `products_locked_until = now + 7d` (skipped if `features.weekly_swap = false`). Swap allowed again when `now >= products_locked_until` (exact boundary).

### Subscriptions (tables in step 1, logic in step 5)

**plans** — `code VARCHAR UNIQUE (BASIC/PRO/PREMIUM)`, `name`, `base_price_paise`, `billing_period ENUM(MONTHLY, YEARLY)`, `features JSONB` (shape from SPEC §4.3), `priority SMALLINT` (discovery tie-break), `is_active`. Seeded: BASIC 5/PINCODE, PRO 20/CITY, PREMIUM null/INDIA, `weekly_swap` false only for PREMIUM. Prices seeded as placeholders (see Q5).

**platform_settings** — `key VARCHAR PK`, `value JSONB`, `updated_by_admin_id`. Keys: `trial` (`{enabled, duration_value, duration_unit, plan_code}`), `grace_days_default`, `shipping_markup`.

**subscriptions** — `retailer_id FK UNIQUE` (one current row per retailer), `plan_id FK`, `status ENUM(TRIAL, ACTIVE, GRACE, EXPIRED, CANCELLED)`, `trial_ends_at`, `current_period_start`, `current_period_end`, `grace_days_override INT NULL`, `grace_ends_at`, `price_override_paise NULL`, `price_override_reason`, `razorpay_subscription_id`, `cancelled_at`. Index (status, current_period_end).

**retailer_offers** — `retailer_id FK`, `plan_id FK NULL`, `offer_type ENUM(PERCENT, FIXED_DISCOUNT, CUSTOM_PRICE)`, `value BIGINT`, `valid_from`, `valid_until`, `reason`, `created_by_admin_id`, `revoked_at`.

**subscription_payments** — `subscription_id FK`, `amount_paise`, `period_start`, `period_end`, `status ENUM(CREATED, PAID, FAILED, REFUNDED)`, `gateway`, `gateway_payment_id UNIQUE`, `raw_payload JSONB`, `paid_at`.

**subscription_audit_log** (append-only, DB trigger blocks UPDATE/DELETE) — `admin_user_id`, `retailer_id NULL`, `subscription_id NULL`, `action`, `old_value JSONB`, `new_value JSONB`.

### Bookings & credit (tables in step 1, logic in step 6)

**bookings** — `booking_no` (human-readable, unique), `customer_id`, `retailer_id`, `product_id`, `quantity`, `unit_price_paise` (snapshot), `total_paise`, `advance_paise`, `balance_paise`, `status ENUM(PENDING_PAYMENT, CONFIRMED, COLLECTED, CANCELLED_REFUNDED, CREDIT_ISSUED, CREDIT_USED, CREDIT_SETTLED)`, `confirmed_at`, `cancel_deadline` (= confirmed_at + 8h), `reminder_sent_at`, `cancelled_at`, `cancelled_by_user_id`, `credit_issued_at`, `collected_at`, `version INT` (optimistic lock). Indexes: (retailer_id, status), (customer_id, status), (status, cancel_deadline).

**payment_confirmations** (PaymentVerifier output) — `booking_id FK`, `method ENUM(CUSTOMER_UTR, CUSTOMER_SCREENSHOT, RETAILER_MARKED, GATEWAY_WEBHOOK)`, `reference`, `proof_media_key`, `payload JSONB`, `submitted_by_user_id`. UNIQUE(booking_id, method, reference) → duplicate confirmations ignored.

**customer_credits** — exactly SPEC §4.5: `customer_id`, `retailer_id`, `booking_id UNIQUE`, `amount_paise`, `used_amount_paise`, `status ENUM(ACTIVE, USED, SETTLED)`, `used_at`, `settled_at`, `settled_by_user_id`, `settled_note`. CHECK `0 ≤ used_amount_paise ≤ amount_paise`. No expiry column (never expires). Index (customer_id, retailer_id, status).

**credit_ledger** (append-only, DB trigger blocks UPDATE/DELETE) — `credit_id FK`, `customer_id`, `retailer_id`, `entry_type ENUM(ISSUE, USE, SETTLE)`, `amount_paise` (signed: +issue, −use, −settle), `balance_after_paise`, `reference_type`, `reference_id`, `performed_by_user_id`, `note`. Invariant tested: `SUM(amount_paise) = amount − used − settled`.

### Later-step tables (created now, minimal columns)

- **orders** — customer, retailer, product, qty, `item_total_paise`, `shipping_paise`, `shipping_markup_paise`, `total_paise`, status, delivery address JSONB, payment reference.
- **shipments** — `order_id UNIQUE`, `provider`, `awb`, `label_url`, `status`, `tracking_events JSONB`, `rate_paise`.
- **reviews** — customer, retailer, `rating SMALLINT CHECK 1..5`, comment, `source_type ENUM(BOOKING, ORDER, CREDIT_USE)`, `source_id`, `is_flagged`, `flag_reason`; UNIQUE(source_type, source_id).
- **shop_events** — exactly SPEC §4.9; indexes (retailer_id, created_at), (retailer_id, event_type, created_at).
- **leads** — retailer, customer, `score NUMERIC`, `reason TEXT`, `status ENUM(NEW, CONTACTED, CONVERTED, DISMISSED)`, `model_version`; UNIQUE(retailer_id, customer_id).
- **notifications** — user, `channel ENUM(PUSH, WHATSAPP, SMS, IN_APP)`, `template`, `payload JSONB`, `dedupe_key UNIQUE` (makes 6-h reminder / 3-day reminder idempotent), `sent_at`, `status`.

---

## 4. Step 1 + 2 API surface

- `POST /auth/otp/request`, `POST /auth/otp/verify` (→ access+refresh JWT, creates user on first login), `POST /auth/refresh`, `POST /auth/logout`
- `POST /retailers` (become a retailer), `GET/PATCH /retailers/me`, `GET /retailers/{slug}` (public), `GET /retailers/me/qr` (PNG)
- `GET/POST /retailers/me/products`, `PATCH /retailers/me/products/{id}` (price/stock/photos/description — allowed during lock), `DELETE /retailers/me/products/{id}` (remove — blocked during lock), `POST /retailers/me/products/swap`
- Guards: `require_role`, `require_plan(feature)`, `check_product_limit`, `check_weekly_lock`.

## 5. Tests planned for step 1 + 2

OTP rate limit / expiry / wrong-code attempts; JWT refresh rotation; RBAC (retailer A cannot touch retailer B's products);
BASIC 6th / PRO 21st active product rejected, PREMIUM unlimited; after swap add/remove/replace rejected for 7 days while
price/stock/photo/description edits pass; swap allowed at exactly `locked_until`, rejected at `locked_until − 1s`; PREMIUM never locked;
parallel adds cannot exceed the limit; retailer without an active subscription cannot publish (`require_plan` 403).

---

## 6. Open questions (business rules — need your answer before coding)

- **Q1 Initial listing vs swap.** Does the first-time listing count as a swap? Proposal: until the retailer's first swap, they may add products freely into empty slots (up to the plan limit) with no lock. After that, any add/remove/replace is a "swap" and starts the 7-day lock.
- **Q2 One shop per phone.** Proposal: one user = one retailer shop, and the same phone can also be a customer of other shops.
- **Q3 Hiding a product.** Proposal: deactivating (hiding) a product counts as a "remove" and is blocked during the lock. Setting stock to 0 is allowed (it's a stock edit).
- **Q4 Downgrade with too many products** (e.g. PRO 20 → BASIC 5). Proposal: the retailer must pick which 5 stay active; until they do, only the 5 most recently activated are shown publicly. This does not count as a swap.
- **Q5 Plan prices.** What base prices (₹/month) should be seeded for BASIC / PRO / PREMIUM? (Admin can change them later.)
- **Q6 Frontend timing.** Proposal: steps 1–2 are backend only; Next.js PWA scaffold starts with step 3.
- **Q7 Branch naming.** This session can only push to `claude/new-session-jtj8ev`. Step 1 and step 2 will go there as separate commits, unless you allow `step-1-...` / `step-2-...` branches.
