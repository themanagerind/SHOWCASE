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
- Auth: Phone number + OTP login (no passwords), JWT access/refresh tokens. **Sessions (owner decision 2026-10-18):** one session per device/browser; logout ends the session on the server immediately (access tokens carry the session id and are checked on every request); users see their logged-in devices in Profile and can log out one device or all other devices; customers/retailers stay logged in while they use the app and are logged out after 30 days without use; admins are logged out 12 hours after login even if active (`ADMIN_SESSION_HOURS`).
- Frontend: Next.js (React) configured as a PWA (service worker, manifest, Add to Home Screen, push notifications), mobile-first, multilingual (English default; see §8)
- Payments: Retailer's own payment link/UPI (no platform split); Razorpay (Orders + Checkout, webhook-verified) for retailer plan billing — UPI autopay/Subscriptions can be added later behind the same gateway interface; admin can also record offline payments
- Courier: Aggregator integration (Shiprocket/Delhivery etc.) behind an abstract CourierService interface
- Media: S3-compatible storage / Cloudinary with image compression

## 3. User Roles

1. **Customer**: browses nearby shops, joins shops, favourites, books, orders, rates.
2. **Retailer**: manages shop profile, products, customers, bookings, wallet, analytics, leads.
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
- Joining is idempotent: re-joining keeps the original source. Only shops with a TRIAL/ACTIVE/GRACE subscription can be joined; a retailer cannot join their own shop.
- Removing a shop from favourites does NOT remove the customer from that retailer's customer list (marked "not favourite"); removal from the list happens only when the customer deletes their account (DPDP).
- At signup the customer gives name, pincode, city, language and an optional, unticked-by-default consent "shops I join may contact me". The retailer sees the customer's full phone number ONLY with this consent; otherwise it is masked (e.g. `91XXXXXX89`). Consent can be withdrawn any time (its timestamp is cleared).

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
- Seed plan prices (admin-editable, GST-inclusive): monthly BASIC ₹199, PRO ₹399, PREMIUM ₹999; yearly ("4 months free", ~33% off) BASIC ₹1,599, PRO ₹3,199, PREMIUM ₹7,999.

### 4.4 Booking / Reservation with Wallet Points (core rule)

> Changed by owner on 2026-10-17: bookings use ONLY wallet points. There is no real-money advance, no UPI advance, no 8-hour refund window and no store credit.

- Every product has a mandatory wallet discount (`wallet_discount_paise`, > 0 and ≤ price), set by the retailer together with the price.
- To reserve a product, the customer must have at least that product's discount in their Showcase wallet (§4.5). No balance → cannot reserve.
- On reservation, exactly the discount amount is deducted from the customer's wallet immediately.
- Points deducted for a booking are NEVER returned to the customer.
- **Booking state machine**:
  - `RESERVED → PURCHASED`: customer buys the product at the shop and **the CUSTOMER confirms it by tapping "I bought it" in their app** (owner decision 2026-10-18; no code, and the retailer cannot mark a booking purchased — this prevents retailers claiming points for sales that did not happen). The booking's points become the purchase discount (not deducted again): customer pays price − discount at the shop, and the points are credited to the retailer's wallet.
  - `RESERVED → FORFEITED`: customer does not buy. The points disappear (credited to nobody), but the full record stays visible to customer, retailer and admin.
  - `RESERVED → CANCELLED_BY_RETAILER`: retailer cannot honour the booking (e.g. out of stock). The points ARE returned to the customer's wallet (the customer did nothing wrong).
- A reservation is valid for **24 hours** from creation. If not PURCHASED by then, a Celery job marks it FORFEITED (idempotent; the boundary is exact: at 24h 00m it is forfeited).
- A reservation holds 1 unit of stock (per quantity booked); stock is released on FORFEITED or CANCELLED_BY_RETAILER, and consumed on PURCHASED. No stock → cannot reserve.
- The platform never handles the shop payment.
- One booking = 1 unit. A customer may hold **multiple bookings, including several of the same product** (owner decision 2026-10-18); each booking deducts its own points and holds its own unit of stock.
- **In-shop purchase without a prior booking** uses the same flow: at the counter the customer taps "Use wallet discount" (creates the booking) and then "I bought it" (owner decision 2026-10-18).
- The forfeit job runs every 5 minutes.

### 4.4a Wallet discount on items that are not listed online (owner decision 2026-10-18)

- Retailers list only some products online; a customer may buy something else in the shop. Whether to give a wallet discount on such an item, and how much, is **the retailer's choice**.
- Flow: the retailer enters the customer's mobile number, the discount amount and a short note (e.g. "school bag") → the customer gets a request in the app ("Sharma Electronics offers ₹100 off") → the customer taps **Confirm** (or Decline) → the amount moves from the customer's wallet to the retailer's wallet, recorded in the ledger. Without the customer's confirmation nothing is deducted.
- A request expires after 30 minutes. If the customer has fewer points than the amount, it cannot be confirmed (the retailer is not shown the customer's balance).
- Like product discounts, these points count towards retailer reward offers (§4.5).

### 4.5 Wallets and Points Ledger

- **Customer wallet**: filled only by redeeming THE-MANAGER codes (§4.11); full code value is credited. Spent on reservations and purchases (product discount). Balance shown in the app.
- **Retailer wallet**: receives the discount points of every completed purchase (including purchases that started as a booking) and of confirmed discounts on unlisted items (§4.4a).
- 1 point = 1 paisa internally, displayed as ₹. Integers only.
- Every movement (code redeemed, reservation deduction, purchase discount transfer, forfeit, admin reset) is an append-only ledger entry; a wallet's balance always equals the sum of its ledger entries and can never go negative.
- **Retailer reward offers (Platform Owner / admin)**: admin can create an offer for a period (e.g. a week or month): "every retailer who collects ≥ X points in this period gets Y% of their total wallet balance as cash". At the end of the period the system lists qualifying retailers and their payout; the cash is paid by the platform owner outside the app and recorded (who, amount, date, reference). After the payout, the participating retailers' wallet balances are reset to 0 via ledger entries (history kept).
- Retailers must ACCEPT (opt in to) an offer to participate. Only opted-in retailers who qualify and receive the payout have their wallet reset to 0; everyone else keeps their balance.
- Reward offer details (owner decisions 2026-10-18):
  - Only one offer at a time: offer periods may not overlap (so the same points can never earn cash twice). Created / cancelled by SUPER_ADMIN only; a cancelled offer pays nothing. An offer with recorded payouts cannot be cancelled.
  - "Points collected in the period" = points the retailer RECEIVED between start and end: completed purchases (BOOKING_PURCHASED) + confirmed discounts on unlisted items (SHOP_DISCOUNT_RECEIVED). Points from the whole period count, even if the retailer joined mid-way.
  - Joining needs a live plan (TRIAL/ACTIVE/GRACE); join or leave any time until the offer ends. If the plan expires before the end, a qualifying retailer is still paid.
  - Qualifies when collected points ≥ threshold (exact threshold qualifies).
  - Payout is based on the wallet balance AT THE END of the offer (not the day the cash is paid): payout = floor(balance_at_end × percent). Percent is stored in basis points (2000 = 20%).
  - When the payout is recorded (amount, date, reference — SUPER_ADMIN or SUPPORT, after the offer ends, once per retailer per offer), exactly balance_at_end points are deducted from the retailer wallet (REWARD_RESET). Points earned after the offer ended stay; with no new points the wallet becomes 0.

### 4.6 Online Orders and Courier

- Customer can order a product for delivery (full payment + shipping charge).
- Courier handled by the platform via aggregators (Delhivery and others): pincode serviceability, rate check, create shipment, AWB, label, tracking webhook updates.
- Abstract `CourierService` interface so providers can be swapped. Platform may add a shipping markup (configurable).

### 4.7 Ratings

- Customers can rate retailers (1-5 + optional comment), only after a completed purchase (booking PURCHASED or delivered order). One review per transaction. Retailer can view, and flag abusive reviews to admin.

### 4.8 Location-based Discovery

- Use PostGIS: `retailers.location GEOGRAPHY(Point,4326)` with GiST index.
- Customers see nearby retailers based on their location (browser Geolocation, with pincode fallback). Default radius 5 km; the customer can increase the radius from Settings.
- Discovery query must combine: subscription status, plan `visibility_scope`, and customer's radius. Rules:
  - Status in (TRIAL, ACTIVE, GRACE) only
  - INDIA scope: visible anywhere (within radius filter if customer set one); CITY scope: same city as customer; PINCODE scope: same pincode as customer
- Ranking: distance first, then rating; plan priority only as a tie-break. Distance is compared in **rings**: the customer's radius is split into 6 equal concentric rings (5 km → rings of ~833 m). Shops are ordered by ring, then rating (high first), then plan priority, then exact distance.
- The customer's pincode and city come from their PROFILE (entered by the customer). GPS (browser location) is used only to measure distance and apply the radius. Radius options: 2, 5, 10, 25, 50 km (default 5), saved in the profile.
- Without GPS: no radius/distance. PINCODE-scope shops in the customer's pincode and CITY/INDIA-scope shops in the customer's city are shown, ordered by rating then plan priority. Without GPS and without pincode/city, the customer is asked for location or to complete the profile.
- Logged-out visitors can browse discovery with GPS; they see shops whose scope matches the pincode/city they pass (otherwise INDIA-scope only).

### 4.8a Product Search (owner decision 2026-10-17)

- Customers (logged in or not) can search PRODUCTS by name/category across shops, in Hindi or English, tolerant to small spelling mistakes (`pg_trgm`).
- Who appears in product search:
  - **PREMIUM** retailers' products: **all India**, no radius limit — the main benefit of PREMIUM.
  - **PRO** retailers' products: only in the customer's city AND within the customer's radius (without GPS: customer's city).
  - **BASIC** retailers' products: NOT in product search (they remain visible on the shop page and shop discovery).
  - Only live subscriptions (TRIAL/ACTIVE/GRACE), active non-deleted products, and after a downgrade only the products the public shop page shows.
- Ranking: text match first (name starts with the query → name contains it → spelling-tolerant match), then distance ring (radius / 6; shops beyond the radius come after, nearest first), then shop rating, then plan priority. Without GPS: text match, then the customer's own city first, then rating, then plan.

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
  - Wallet + code redemption is built in step 6 (bookings need it); purchase-by-order uses it in step 9.
- Booking uses points only (§4.4); retailer points are used for reward offers (§4.5).
- Customer with fewer points than the product's discount: the purchase is still allowed, but with NO discount (full price, no points deducted, no partial use). Any concession the retailer gives in that case is their own decision outside the app and is not recorded in wallets. (Reservations still require the full discount in points, §4.4.)

### 4.12 THE-MANAGER → Showcase resident signup prefill (design APPROVED 2026-10-18 — Showcase side built)

- THE-MANAGER's Resident dashboard gets a "Shop Now" button that opens Showcase with a one-time prefill token. **No SSO**: the resident still verifies their mobile with OTP on Showcase; the THE-MANAGER session is never shared. Customers arriving directly keep the normal signup.
- Prefill only saves typing: name, mobile, email (optional), society address (name, city, state, pincode), flat number + floor. The resident reviews/edits before saving; nothing is auto-submitted.
- The token is verified by the Showcase BACKEND with THE-MANAGER using the shared store key, is short-lived and single-use (replay-safe).
- Approved decisions: opaque random token (no data in the URL) redeemed server-to-server; name/address/flat revealed only after OTP for the same mobile; token valid 5 minutes, single use; landing URL `/welcome?prefill=`; address/flat/society saved to the profile only if the resident saves the form; **email is not stored** (no use for it yet, DPDP minimal data).
- Build order: after step 5 (owner decision). Contract for THE-MANAGER: `docs/integrations/the-manager-prefill.md`.
- Build details (owner decisions 2026-10-18):
  - `signup_source` (DIRECT | THE_MANAGER) is set to THE_MANAGER only for an account created through the prefill flow; an existing customer keeps their first source.
  - Society pincode/city fill the customer's pincode/city (used by discovery) only when those are empty; after saving, the resident lands on Discover (nearby shops).
  - `/prefill/start` is limited to 20 attempts per hour per IP (token guessing). `/welcome` without a token goes to the normal login.
  - A resident can always sign up directly with OTP; the account is identified by the mobile number, so a later "Shop Now" opens the same account and only fills empty fields.

## 5. Subscription System (Admin-controlled)

- Plans: BASIC, PRO, PREMIUM. No free plan. Prices, features and limits are all editable by admin.
- **Admin settings** (store in `platform_settings` JSONB + per-retailer overrides):
  1. Free trial: enable/disable, duration in days/months, which plan the trial gives
  2. Increase/decrease base price of any plan (apply to new retailers only or all)
  3. Personalised offer for a specific retailer (percent discount / fixed discount / custom price, with validity dates and reason)
  4. Extend a specific retailer's grace period (default grace days is also a global setting)
- **Final price resolution order**: (1) subscription `price_override` → (2) active `retailer_offer` → (3) `plan.base_price` (monthly) / `plan.yearly_price` (yearly).
- **Owner decisions (2026-10-18):**
  - Billing cycles: **monthly or yearly — the retailer chooses**. Yearly default = "4 months free". Prices are **GST-inclusive** (18%, shown separately on the receipt).
  - Payment: **Razorpay** (keys added to `.env` when the account is ready). Until then, and for retailers who pay by UPI/cash, an admin records the payment manually ("Mark paid"). Every payment, either way, is recorded with its period.
  - Free trial default: **enabled, 30 days, PRO plan**; given once per retailer, started automatically when the shop is created.
  - Trial ending without payment → **GRACE** (default 7 days) → EXPIRED, same as a paid period.
  - **Plan change** (e.g. BASIC → PRO) by the retailer takes effect **from the next renewal** (the paid period starts when the current one ends). An admin can change the plan **immediately**.
  - Paying before the current period/trial ends adds the new period after it (no days lost).
  - Base-price change "new retailers only": existing subscriptions keep their current price as a recorded `price_override` (grandfathered) for the same plan and cycle.
  - Admin roles: SUPER_ADMIN (everything) and SUPPORT (view, extend grace, record payments — no price/offer/plan/settings changes).
  - The lifecycle job runs **hourly** (more precise than daily); reminders 3 days before expiry are de-duplicated.
- **Lifecycle**: `TRIAL → ACTIVE → GRACE → EXPIRED` (also CANCELLED). When the period ends, status becomes GRACE and all features continue until `grace_ends_at`; when grace ends, status becomes EXPIRED. Celery daily job handles transitions and sends reminders 3 days before expiry (push + WhatsApp-ready notification).
- Audit log for every admin change (`subscription_audit_log`: admin, action, old/new value, timestamp).

### Status behaviour matrix

| Status | Shop publicly visible | Add/swap products | New bookings/orders | Complete existing bookings |
|---|---|---|---|---|
| TRIAL / ACTIVE / GRACE | Yes (within plan scope) | Yes (per plan rules) | Yes | Yes |
| EXPIRED | **NO** | No | No | **YES** |

- **Expired retailer exception**: public discovery hides the shop, BUT any customer who has an open RESERVED booking with that retailer still sees the shop in their "My Bookings/Favourites" with a limited view (address, contact, WhatsApp, booking). Expired retailers keep limited login access ONLY to complete existing bookings. No data is deleted; renewing restores everything.
- Expired-state details (owner decisions 2026-10-18):
  - Limited view = shop name, address, phone, WhatsApp, timings, map link and the customer's own open bookings — no product list. Shown only while the customer has an open RESERVED booking; it disappears when the booking closes (bought / forfeited / cancelled).
  - Favourites: an expired shop stays in the list, greyed, "currently unavailable", with no details (unless the limited view applies). It returns to normal when the plan is renewed.
  - Expired retailer can use: Dashboard (wallet balance and reward payouts visible), Plan (renew) and Bookings (see and cancel open bookings, history). Products, Share & QR and the Customers list are closed with a "renew your plan — all data is safe" message. Joining reward offers needs a live plan; an earlier joined offer still pays if qualified.

## 6. Database Tables (minimum)

users, retailers, customers, retailer_customers (favourites/source), products, product_swaps (swap history), bookings, wallets (+ wallet_ledger), wallet_redemptions, retailer_reward_offers (+ payouts), orders, shipments, reviews, shop_events, leads, plans, platform_settings, subscriptions, retailer_offers, subscription_payments, subscription_audit_log, notifications, admin_users.

Use UUID primary keys, created_at/updated_at on all tables, soft deletes where needed, proper indexes (GiST on location, composite on retailer_id+status, etc.), and Alembic migrations.

## 7. API Structure (FastAPI)

All endpoints are served under the `/api/v1` prefix.

```
app/
  api/        auth, retailers, products, bookings, wallet, orders, reviews,
              discovery, analytics, leads, subscriptions, admin
  models/     SQLAlchemy models
  schemas/    Pydantic schemas
  services/   booking_service, wallet_service, subscription_service,
              visibility_service, product_swap_service, courier_service, lead_scoring
  workers/    Celery tasks (booking_expiry, reminders, subscription_lifecycle)
  ml/         training, scoring
  core/       config, security, dependencies (require_plan, get_current_user, etc.)
```

- Implement a reusable dependency `require_plan(feature)` that checks subscription status and plan features, and `check_product_limit` / `check_weekly_lock` guards.
- Role-based access control (customer / retailer / admin).
- All business rules (booking points, wallet ledger, plan limits, visibility) must live in the service layer, with unit tests.

## 8. Non-functional Requirements

- Mobile-first, fast on low-end Android phones and 3G/4G; image compression and lazy loading; offline-friendly caching of browsed pages (PWA).
- UI language: **English by default** (owner decision 2026-10-18). The user can switch to Hindi (hi), Gujarati (gu), Marathi (mr), Telugu (te), Bengali/Bangla (bn), Kannada (kn) or Odia (or); the choice is remembered on the device and saved in the profile. Every language must have every UI string (enforced at build time); more languages (e.g. Tamil) can be added the same way.
- **UI conventions (owner decision 2026-10-18), apply to every current and future screen/dashboard:** headings, navigation links and tabs are shown in CAPITALS. This is one universal setting (`--heading-case` in `frontend/app/globals.css`); new screens must use h1–h4, the shared header/RetailerNav/AdminNav/`.tabs`, or the `ui-heading` class instead of styling headings themselves. Theme: navy blue + white with green accents.
- Security: OTP rate limiting, input validation, signed media URLs, no secrets in code, audit logs for money-related state changes.
- Money in paise (integers), all timestamps in UTC, display in IST.
- Dockerized setup (docker-compose: api, postgres+postgis, redis, celery worker/beat), env-based config, OpenAPI docs.

## 9. Build Order

1. Project scaffold, DB models and migrations (with PostGIS), auth (OTP+JWT)
2. Retailer profile, products with plan limits and weekly slot-swap lock
3. Customer signup via retailer link/QR + favourites
4. Discovery with PostGIS and plan-based visibility
5. Subscription system + admin controls (trial, pricing, offers, grace) + lifecycle jobs
6. Wallets (THE-MANAGER code redemption, points ledger) + booking with points + purchase + retailer reward offers — built as 6a (wallets + code redemption), 6b (bookings), 6c (reward offers)
7. Expired-retailer limited access behaviour
8. Ratings, analytics events and dashboard
9. Courier integration (abstract service + one provider)
10. Lead scoring (rule-based first, then ML)
11. PWA polish, i18n, push notifications

## 10. Instructions to the AI Assistant

Start with step 1 and 2. First show me the complete database schema (SQL/SQLAlchemy models) and the project folder structure for review, then proceed step by step. Ask me before making any assumption that changes a business rule above.

## 11. Testing Requirements (mandatory)

Write automated tests (pytest) for all business rules in the service layer. Do not mark a step complete until these pass. Test boundaries exactly, and use a controllable clock (freezegun or an injectable `now()`) instead of real time.

**Wallet and booking with points**
- Product without a discount, or with discount > price, is rejected
- Reservation rejected when wallet balance < discount (one paisa short → rejected; exactly equal → allowed)
- Purchase with balance < discount → full price, zero points deducted; balance ≥ discount → exactly the discount deducted
- Reservation deducts exactly the discount; points are never returned (no cancel refund)
- PURCHASED booking: no second deduction; points credited to the retailer's wallet exactly once
- FORFEITED booking: points go to nobody, record stays visible
- Reservation forfeited at exactly 24h 00m, not at 23h 59m; forfeit job runs once only (idempotent); stock is released
- Retailer cancellation returns the points to the customer exactly once; reservation without stock is rejected
- Wallet balance always equals the sum of its ledger entries and never goes negative; ledger is immutable
- Code redemption: same `request_id` reused on retry, a code is credited at most once, 404/409 credit nothing
- Reward offer: only opted-in retailers with ≥ threshold points in the period qualify; non-qualifiers keep their balance; payout = % of balance; their wallets reset to 0 via ledger
- Reward offer: exact threshold qualifies, one point less does not; points before the start / after the end don't count; payout recorded once per retailer; deduction = balance at the end (later points kept); overlapping offers rejected; no joining after the end or without a live plan

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
- EXPIRED retailer is absent from public discovery, but IS shown (limited view) to a customer with an open booking with them
- Expired retailer can complete existing bookings but cannot add products or take new bookings
- Limited view only for a customer with an open booking, and gone once it closes; expired retailer's customer list / QR / product changes are refused, bookings list and cancel work
- Ranking is by distance ring (radius / 6), then rating; plan priority only as tie-break
- Radius boundary is exact (just inside shown, just outside hidden); without GPS the fallback uses profile pincode/city and rating order

**Product search**
- PREMIUM product found from another city and beyond the radius; PRO product only in the same city and within radius; BASIC product never in product search
- Expired retailer's products absent; hidden/deleted products absent; downgrade limit respected
- Spelling-tolerant match works; ranking is text match, then distance ring, then rating, then plan

**Security and data**
- A customer cannot read another customer's bookings or wallet; a retailer cannot access another retailer's data
- Feature gating (`require_plan`) returns 403 for features outside the plan
- No secrets in the repo; `.env.example` is provided

**UI / PWA (screenshots)**
- Take screenshots at mobile width (about 360px) for: retailer page, product list, booking flow, wallet screen, discovery list. Check layout, Hindi text rendering, and that PWA install works. Screenshots do NOT replace the backend tests above.

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
- Write unit tests for all money, wallet, booking, subscription, visibility and plan-limit logic (see Section 11). Run them before every commit.
- Never commit `.env` or any secret. Only `.env.example` goes in the repo.
- After each step, add a 5-line summary to `CHANGELOG.md`.
- If you must make an assumption about a business rule, ask me first.
- Keep this file and `CLAUDE.md` in the repo root. `CLAUDE.md` only needs one line: "Read SPEC.md first, and follow Section 13."
