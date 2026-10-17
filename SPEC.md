# PROJECT: SHOWCASE — Online storefront platform for offline retailers in India

> Is file ko AI coding tool (Claude Code, Cursor, etc.) ko do aur bolo: "SPEC.md padho aur sirf step N banao."
> Business rule badalna ho to yahin edit karo.

## 1. Overview

Build "Showcase", a PWA (Progressive Web App) that helps offline/brick-and-mortar retailers in India establish an online presence. Each retailer gets their own storefront page where they list their best products. Customers join a retailer via a shared link/QR, the retailer is auto-added to the customer's favourites, and customers can chat on WhatsApp, book products with a partial advance payment (to be collected at the shop), or order online with courier delivery.

Revenue model: SUBSCRIPTION ONLY. No commission. There is NO free plan.

## 2. Tech Stack

- Backend: FastAPI (Python), SQLAlchemy 2.x, Alembic migrations, Pydantic v2
- Database: PostgreSQL with PostGIS extension
- Background jobs: Celery + Redis (booking timers, reminders, subscription lifecycle)
- Auth: Phone number + OTP login, JWT access/refresh tokens
- Frontend: Next.js (React) configured as a PWA (service worker, manifest, Add to Home Screen, push notifications), mobile-first, Hindi + English i18n ready
- Payments: Retailer's own payment link/UPI (no platform split); Razorpay Subscriptions for retailer plan billing; webhook-ready design
- Courier: Aggregator integration (Shiprocket/Delhivery etc.) behind an abstract CourierService interface
- Media: S3-compatible storage / Cloudinary with image compression

## 3. User Roles

1. **Customer**: browses nearby shops, joins shops, favourites, books, orders, rates.
2. **Retailer**: manages shop profile, products, customers, bookings, credits, analytics, leads.
3. **Platform Admin**: manages retailers, plans, trials, pricing, offers, grace periods, couriers, disputes.

## 4. Core Features

### 4.1 Retailer Storefront

- Own page at `/{slug}` with: shop name, photos, category, full address, pincode, city, map location (lat/lng), timings, phone, WhatsApp number, payment link, rating summary.
- Retailer can add their WhatsApp number; customers get a "Chat on WhatsApp" button (`wa.me` deep link).
- Retailer gets a unique shareable link and downloadable QR code.

### 4.2 Customer Onboarding via Retailer Link

- Retailer sends their store link to any customer (WhatsApp share).
- Customer signs up (phone OTP) through that link, and the retailer is automatically added to the customer's Favourites list. Store the source (`LINK` / `QR`).
- Each retailer has their own customer list (`retailer_customers`).

### 4.3 Product Listing and Weekly Slot-Swap Rule

- Retailers list only their "best products" (limited by plan).
- **Plan limits**:
  - BASIC: max 5 active products, visible only in the retailer's own PINCODE area
  - PRO: max 20 active products, visible across the whole CITY
  - PREMIUM: unlimited products, visible ALL INDIA
- **Weekly slot-swap (Option A)**: A retailer may swap/change their product set ONCE per week. In a swap action they can replace as many of their slots as they want in one go. After a swap, the product set is LOCKED for 7 days (`products_locked_until`). During the lock, retailers CANNOT add/remove/replace products, but CAN still edit price, stock, photos, and description of existing products. Premium plan: no lock (change anytime).
- Plan limits are stored in `plans.features` JSONB, e.g.:

```json
{
  "max_products": 5,
  "weekly_swap": true,
  "visibility_scope": "PINCODE",
  "analytics": false,
  "ml_leads": false,
  "broadcast": false,
  "courier": true
}
```

(`max_products: null` = unlimited; `visibility_scope`: PINCODE | CITY | INDIA)

- **Swap clarifications (approved):**
  - First-time listing is free: until the retailer's first swap, they may fill empty slots (up to the plan limit) with no lock. After that, any add/remove/replace is a swap and starts the 7-day lock.
  - Hiding/deactivating a product counts as a "remove" (blocked during lock). Setting stock to 0 is a stock edit (allowed).
  - During the lock, product name and category cannot be changed (that would effectively replace the product); outside the lock they can be edited without counting as a swap.
  - Plan downgrade with too many active products (e.g. PRO 20 → BASIC 5): the retailer chooses which products stay active; until they do, only the most recently activated N products are shown publicly. This does not count as a swap.
- One phone number = one retailer shop. The same user may also be a customer of other shops.
- Seed plan prices (monthly, admin-editable): BASIC ₹199, PRO ₹399, PREMIUM ₹999.

### 4.4 Booking with Partial Payment (core rule)

- Customer pays a partial advance (retailer-set % or fixed amount) through the retailer's payment link/UPI, and pays the remainder at the shop.
- **Booking state machine**:
  - `PENDING_PAYMENT → CONFIRMED → COLLECTED`
  - `CONFIRMED → CANCELLED_REFUNDED` (cancelled within 8 hours)
  - `CONFIRMED → CREDIT_ISSUED` (8 hours passed, no cancellation)
  - `CREDIT_ISSUED → CREDIT_USED` or `→ CREDIT_SETTLED`
- Payment confirmation: customer submits UTR/screenshot and/or retailer taps "Payment received". Design a pluggable PaymentVerifier so gateway webhooks can be added later without schema changes.
- **8-hour rule**:
  - Within 8 hours of booking confirmation: customer can cancel from the app, or via call/WhatsApp to the retailer (retailer can cancel on their behalf). Full advance is refunded BY THE RETAILER; the platform only records status `CANCELLED_REFUNDED`.
  - After 8 hours: NO refund. The advance becomes store CREDIT for that retailer. The customer must purchase some product from that shop.
  - Celery job: send customer reminder at the 6-hour mark ("2 hours left for free cancellation"), and auto-convert to `CREDIT_ISSUED` at 8 hours (`cancel_deadline`).

### 4.5 Customer Credit (ledger, no expiry)

- Credit is retailer-specific and NEVER expires. It stays until the customer visits the shop and uses it.
- Customer account shows credit balances per retailer (e.g., "Sharma Electronics: ₹500").
- Table `customer_credits (id, customer_id, retailer_id, booking_id, amount, used_amount, status[ACTIVE/USED/SETTLED], created_at, used_at, settled_at, settled_note)`.
- Retailer can: (a) "Use credit" against a purchase (full or partial), (b) mark credit as "Settled/Refunded" at their discretion when the customer no longer wants it (record who/when/note; keep a customer-visible record).
- Maintain an immutable credit ledger/audit trail.

### 4.6 Online Orders and Courier

- Customer can order a product for delivery (full payment + shipping charge).
- Courier handled by the platform via aggregators (Delhivery and others): pincode serviceability, rate check, create shipment, AWB, label, tracking webhook updates.
- Abstract `CourierService` interface so providers can be swapped. Platform may add a shipping markup (configurable).

### 4.7 Ratings

- Customers can rate retailers (1-5 + optional comment), only after a completed booking/order/credit use. One review per transaction. Retailer can view, and flag abusive reviews to admin.

### 4.8 Location-based Discovery

- Use PostGIS: `retailers.location GEOGRAPHY(Point,4326)` with GiST index.
- Customers see nearby retailers based on their location (browser Geolocation, with pincode fallback). Default radius 5 km; the customer can increase the radius from Settings.
- Discovery query must combine: subscription status, plan `visibility_scope`, and customer's radius. Rules:
  - Status in (TRIAL, ACTIVE, GRACE) only
  - INDIA scope: visible anywhere (within radius filter if customer set one); CITY scope: same city as customer; PINCODE scope: same pincode as customer
- Ranking: distance first, then rating; plan priority only as a tie-break.

### 4.9 Retailer Analytics (plan-gated)

- Event tracking table `shop_events (id, retailer_id, customer_id nullable, anon_id, event_type[shop_view, product_view, favourite_add, whatsapp_click, call_click, booking_start, booking_confirmed], meta JSONB, lat, lng, created_at)`.
- Dashboard: daily/weekly/monthly visitors, unique vs repeat, top products, WhatsApp/call clicks, booking conversion.

### 4.10 Lead Generation (ML, Premium)

- Stage 1 (rule-based scoring): score = product_views*1 + favourite*3 + whatsapp/call click*5 + repeat_visits*2; "hot lead" above a threshold. Show retailer: "Customer X viewed your product Y 3 times".
- Stage 2 (ML, once enough data): XGBoost/LogisticRegression predicting booking probability per (customer, retailer). Design `ml/` module with training script, scoring service, and a `leads` table (`retailer_id, customer_id, score, reason, status`).
- Only generate/share leads for customers who gave consent at signup ("retailer may contact me"). Comply with India's DPDP Act 2023 (consent, data deletion, minimal data).

### 4.11 THE-MANAGER wallet redemption (external integration)

- THE-MANAGER (sister society-management product): a resident transfers wallet points to the Platform Owner's Master Wallet there and receives an 8-character code. Showcase verifies the code with one server-to-server call:
  - `POST {THE_MANAGER_BASE_URL}/api/v1/wallet-redemptions/verify`
  - Header: `X-Store-Api-Key: <shared secret>` (only auth; no OAuth/JWT/session). Body (JSON, NOT headers): `{"code": "AB3DEFGH", "request_id": "showcase-redeem-<uuid>"}`
  - `code`: send exactly as the customer typed it (THE-MANAGER normalises case/whitespace).
  - `request_id` (string, max 100 chars, always sent): ONE id per redemption attempt, stored in Showcase before the call. On timeout / no response, retry with the SAME `request_id` → THE-MANAGER replays the original `200`. Never generate a new id for the same attempt. A different or missing `request_id` on a used code → `409`.
  - Success `200`: `{"amount_paise": 15000, "used_at": "2026-10-17T16:43:31.530385+00:00"}` — `amount_paise` is an integer; never parse it as float.
  - Errors: `401` key missing/wrong (config problem, not shown to customer as "invalid code"), `404` code doesn't exist → "invalid code", `409` already redeemed → no points credited, `503` integration not live on THE-MANAGER side.
- No database access and no resident/society data is shared — only `amount_paise` and `used_at`.
- Shared secret lives only in `.env` (`THE_MANAGER_API_KEY`, same value as THE-MANAGER's `ECOM_STORE_API_KEY`), never in git.
- **Business rules (decided):**
  - The CUSTOMER enters the code in the Showcase customer app. The FULL redeemed amount is credited to the customer's Showcase wallet as points (1 point = 1 paisa internally, shown as ₹).
  - The RETAILER sets a wallet discount (fixed ₹ amount) on each product, together with its price. The discount must not exceed the price.
  - On a full-payment purchase (online order, or in-shop purchase), the product's discount is deducted from the customer's wallet and credited to the retailer's Showcase wallet; the customer pays price − discount. The rest of the customer's points stay in their wallet.
  - The discount is the retailer's cost. Showcase records every wallet movement in an immutable ledger; no real money moves through the platform.
  - Wallet integration is built together with step 9 (orders).
- **Open (do not build until answered):** whether bookings/reservations change to points-only (see question to owner — conflicts with §4.4), what retailer-wallet points can be used for, and what happens when the customer has fewer points than the discount.

## 5. Subscription System (Admin-controlled)

- Plans: BASIC, PRO, PREMIUM. No free plan. Prices, features and limits are all editable by admin.
- **Admin settings** (store in `platform_settings` JSONB + per-retailer overrides):
  1. Free trial: enable/disable, duration in days/months, which plan the trial gives
  2. Increase/decrease base price of any plan (apply to new retailers only or all)
  3. Personalised offer for a specific retailer (percent discount / fixed discount / custom price, with validity dates and reason)
  4. Extend a specific retailer's grace period (default grace days is also a global setting)
- **Final price resolution order**: (1) subscription `price_override` → (2) active `retailer_offer` → (3) `plan.base_price`.
- **Lifecycle**: `TRIAL → ACTIVE → GRACE → EXPIRED` (also CANCELLED). When the period ends, status becomes GRACE and all features continue until `grace_ends_at`; when grace ends, status becomes EXPIRED. Celery daily job handles transitions and sends reminders 3 days before expiry (push + WhatsApp-ready notification).
- Audit log for every admin change (`subscription_audit_log`: admin, action, old/new value, timestamp).

### Status behaviour matrix

| Status | Shop publicly visible | Add/swap products | New bookings/orders | Redeem/settle existing credit |
|---|---|---|---|---|
| TRIAL / ACTIVE / GRACE | Yes (within plan scope) | Yes (per plan rules) | Yes | Yes |
| EXPIRED | **NO** | No | No | **YES** |

- **Expired retailer exception**: public discovery hides the shop, BUT any customer who has an ACTIVE credit with that retailer still sees the shop in their "My Credits/Favourites" with a limited view (address, contact, WhatsApp, credit balance). Expired retailers keep limited login access ONLY to redeem and settle credits and complete existing bookings. No data is deleted; renewing restores everything.

## 6. Database Tables (minimum)

users, retailers, customers, retailer_customers (favourites/source), products, product_swaps (swap history), bookings, customer_credits (+ credit_ledger), orders, shipments, reviews, shop_events, leads, plans, platform_settings, subscriptions, retailer_offers, subscription_payments, subscription_audit_log, notifications, admin_users.

Use UUID primary keys, created_at/updated_at on all tables, soft deletes where needed, proper indexes (GiST on location, composite on retailer_id+status, etc.), and Alembic migrations.

## 7. API Structure (FastAPI)

All endpoints are served under the `/api/v1` prefix.

```
app/
  api/        auth, retailers, products, bookings, credits, orders, reviews,
              discovery, analytics, leads, subscriptions, admin
  models/     SQLAlchemy models
  schemas/    Pydantic schemas
  services/   booking_service, credit_service, subscription_service,
              visibility_service, product_swap_service, courier_service, lead_scoring
  workers/    Celery tasks (booking_expiry, reminders, subscription_lifecycle)
  ml/         training, scoring
  core/       config, security, dependencies (require_plan, get_current_user, etc.)
```

- Implement a reusable dependency `require_plan(feature)` that checks subscription status and plan features, and `check_product_limit` / `check_weekly_lock` guards.
- Role-based access control (customer / retailer / admin).
- All business rules (8-hour window, credit ledger, plan limits, visibility) must live in the service layer, with unit tests.

## 8. Non-functional Requirements

- Mobile-first, fast on low-end Android phones and 3G/4G; image compression and lazy loading; offline-friendly caching of browsed pages (PWA).
- Hindi + English UI, structure ready for Gujarati, Marathi, Tamil, etc.
- Security: OTP rate limiting, input validation, signed media URLs, no secrets in code, audit logs for money-related state changes.
- Money in paise (integers), all timestamps in UTC, display in IST.
- Dockerized setup (docker-compose: api, postgres+postgis, redis, celery worker/beat), env-based config, OpenAPI docs.

## 9. Build Order

1. Project scaffold, DB models and migrations (with PostGIS), auth (OTP+JWT)
2. Retailer profile, products with plan limits and weekly slot-swap lock
3. Customer signup via retailer link/QR + favourites
4. Discovery with PostGIS and plan-based visibility
5. Subscription system + admin controls (trial, pricing, offers, grace) + lifecycle jobs
6. Booking flow with 8-hour rule + credit ledger + settle/redeem
7. Expired-retailer limited access behaviour
8. Ratings, analytics events and dashboard
9. Courier integration (abstract service + one provider)
10. Lead scoring (rule-based first, then ML)
11. PWA polish, i18n, push notifications

## 10. Instructions to the AI Assistant

Start with step 1 and 2. First show me the complete database schema (SQL/SQLAlchemy models) and the project folder structure for review, then proceed step by step. Ask me before making any assumption that changes a business rule above.

## 11. Testing Requirements (mandatory)

Write automated tests (pytest) for all business rules in the service layer. Do not mark a step complete until these pass. Test boundaries exactly, and use a controllable clock (freezegun or an injectable `now()`) instead of real time.

**Booking and 8-hour rule**
- Cancel at 7h 59m after confirmation → full refund status `CANCELLED_REFUNDED`
- Cancel at exactly 8h 00m and at 8h 01m → NO refund, advance becomes credit (`CREDIT_ISSUED`)
- Retailer cancels on behalf of customer inside 8h → refund; outside 8h → rejected
- 6-hour reminder is sent once only; auto-conversion to credit at 8h runs once only (idempotent)
- Booking cannot be confirmed twice; duplicate payment confirmation is ignored

**Credit ledger**
- Partial use of credit leaves the correct remaining balance
- Credit cannot be used beyond its balance, cannot be used at a different retailer, never expires
- After retailer marks credit "Settled", it cannot be used again, and the customer sees the settled record
- Ledger entries are immutable and always add up to the balance

**Subscription and plans**
- Price resolution order: `price_override` → active `retailer_offer` → `plan.base_price`
- Trial → Active → Grace → Expired transitions happen on the correct dates; admin-extended grace period is respected
- Admin changes (trial, price, offer, grace) are written to `subscription_audit_log`
- No free plan exists; a retailer without an active plan cannot publish

**Plan limits and weekly swap**
- BASIC: 6th active product is rejected; PRO: 21st is rejected; PREMIUM: unlimited
- After a swap, add/remove/replace is rejected for 7 days; price/stock/photo edits are still allowed
- Swap is allowed again exactly after the lock ends; PREMIUM has no lock

**Visibility**
- PINCODE-scope shop is not shown to a customer in a different pincode; CITY-scope not shown outside the city; INDIA-scope shown anywhere within the customer's radius
- EXPIRED retailer is absent from public discovery, but IS shown (limited view) to a customer holding ACTIVE credit with them
- Expired retailer can redeem/settle credit but cannot add products or take new bookings
- Ranking is by distance, then rating; plan priority only as tie-break

**Security and data**
- A customer cannot read another customer's bookings or credits; a retailer cannot access another retailer's data
- Feature gating (`require_plan`) returns 403 for features outside the plan
- No secrets in the repo; `.env.example` is provided

**UI / PWA (screenshots)**
- Take screenshots at mobile width (about 360px) for: retailer page, product list, booking flow, credit screen, discovery list. Check layout, Hindi text rendering, and that PWA install works. Screenshots do NOT replace the backend tests above.

## 12. Git and Security Rules

- Private repo. Add `.gitignore` in the very first commit (`.env`, `__pycache__/`, `venv/`, `node_modules/`, `.next/`, uploads).
- Never commit secrets (Razorpay keys, JWT secret, DB password, courier/S3 keys). Use `.env` and commit only `.env.example`.
- One build step = one branch = one PR (e.g., `step-2-products-and-weekly-swap`). Exception: when the Claude Code session is restricted to one branch, each step goes there as separate commits. Use clear commit messages (`feat: ...`, `fix: ...`).
- After each step, append a 5-line summary to `CHANGELOG.md`.

## 13. Working Rules for Claude Code (read every session)

- Read `SPEC.md` at the start of every session. It is the single source of truth for this project.
- To change any business rule: update `SPEC.md` first, then update code and tests. Keep all three in ONE commit. Use a commit message like `spec: change cancel window to 12h`.
- If code and `SPEC.md` disagree, ask me. Do not silently change either one.
- One build step = one branch = one PR. Branch name: `step-N-short-name`.
- Do ONLY the step I ask for. Do not build later steps on your own.
- Before writing code for a step, show me the plan/schema and wait for my approval.
- Write unit tests for all money, credit, booking, subscription, visibility and plan-limit logic (see Section 11). Run them before every commit.
- Never commit `.env` or any secret. Only `.env.example` goes in the repo.
- After each step, add a 5-line summary to `CHANGELOG.md`.
- If you must make an assumption about a business rule, ask me first.
- Keep this file and `CLAUDE.md` in the repo root. `CLAUDE.md` only needs one line: "Read SPEC.md first, and follow Section 13."
