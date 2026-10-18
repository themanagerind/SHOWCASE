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

## Languages — English default + 7 Indian languages
- UI is English by default (owner decision; SPEC §8). Users can switch to Hindi, Bangla, Telugu, Marathi, Gujarati, Kannada or Odia from a dropdown in the header (each shown in its own script); the choice is remembered on the device and saved in the profile.
- Strings moved to `frontend/lib/locales/<code>.ts`; every locale is typed against English, so a missing translation fails the build (verified).
- Dates use the matching Indian locale (e.g. `gu-IN`); backend accepts `en|hi|gu|mr|te|bn|kn|or` as `preferred_language`; WhatsApp share text now English.
- Checked in Chromium at 360px for all 8 languages, logged out and as a retailer (longest header): no overflow, nav links on one line; screenshots in `docs/screenshots/languages/`.
- Translations were written by the AI assistant — a native-speaker review is recommended before launch.

## Step 5 — Subscriptions, payments and admin controls
- Plans monthly or yearly (retailer's choice; yearly "4 months free": ₹1,599 / ₹3,199 / ₹7,999), GST-inclusive with GST shown; price order override → offer → base; free trial (default 30 days PRO) auto-starts with the shop, once per retailer.
- Subscription status is derived from paid periods: TRIAL/ACTIVE → GRACE (default 7 days, per-retailer extension) → EXPIRED; paying early queues the next period (no days lost), so retailer plan changes apply from the next renewal; admins can change a plan immediately. Hourly Celery job + de-duplicated 3-day reminders.
- Razorpay Orders + Checkout with payment-signature and webhook verification (idempotent, amount-checked) — switches on when keys are set; admins can record UPI/cash payments meanwhile.
- Admin (SUPPORT / SUPER_ADMIN): retailer list/search, record payment, extend grace, price override, offers, immediate plan change, plan prices (new-only grandfathering or all), plan features, trial/grace/GST settings; every change in the append-only audit log. Admin screens at `/admin` (English), retailer "Plan" screen in all 8 languages.
- Migration `0004`; `scripts/create_admin.py`; 42 new tests (171 total); browser e2e: trial → admin offer + payment → retailer sees offer price and queued yearly period; screenshots in `docs/screenshots/step-5/`.

## UI convention — capital headings everywhere
- One universal setting (`--heading-case` in `frontend/app/globals.css`) puts every heading (h1–h4), header link, dashboard tab (`.rnav`) and toggle tab (`.tabs`) in CAPITALS; new screens get it automatically, custom headings use `ui-heading`. Recorded in SPEC §8 as a rule for all future screens. Indic scripts are unaffected (no capitals).

## Sessions & logout
- Logout now ends the session on the server too, effective immediately: access tokens carry a session id (`sid`) that is checked on every request.
- Profile → "Logged-in devices" (browser + phone type, last active, "this device"), log out any one device or all other devices (lost phone).
- Customers/retailers: logged out after 30 days without use (sliding); admins: logged out 12 h after login even if active (`ADMIN_SESSION_HOURS`). A device whose session ended is sent to login with "You were logged out" (all 8 languages).
- Migration `0005`; 10 new tests (181 total); two-device browser e2e; screenshots in `docs/screenshots/sessions/`.

## Step 6a — Wallets and THE-MANAGER code redemption
- Customer and retailer wallets (1 point = 1 paisa) with an append-only `wallet_ledger` (DB trigger) and a cached balance that can never go negative (service check + DB constraint); balance always equals the ledger sum.
- Code redemption per the agreed contract: the attempt is saved before calling THE-MANAGER; lost responses are retried with the same `request_id` (3 immediate tries + a 5-minute Celery job); 404/409 rejected, 401/503 reported as integration errors; a code can be credited at most once in Showcase; the raw code is not kept; 10 attempts/hour per customer.
- `scripts/mock_the_manager.py` (dev stand-in with demo codes) and the real HTTP client tested against it, incl. replay and float rejection.
- Screens: customer Wallet (balance, add code, history) in all 8 languages; wallet points tile on the retailer dashboard. Migration `0006`; 17 new tests (198 total).

## Step 6b — Bookings with points + shop discount on unlisted items
- Customer reserves a product with wallet points (the product's wallet discount is held, 1 unit of stock is held); multiple bookings allowed, including the same product.
- Only the customer can complete a booking by tapping "I bought it" — the retailer cannot; points then go to the retailer's wallet once (double tap is harmless), even if the shop's plan has expired since.
- 24 hours (exact boundary) without "I bought it" → FORFEITED: points are gone, stock is released, record kept; Celery job every 5 minutes (idempotent).
- Retailer can cancel an open booking with a reason (e.g. out of stock): points return to the customer once and stock is released.
- SPEC §4.4a: retailer can send a wallet discount for an item that is not listed online (customer's phone + amount + item); points move only after the customer confirms in the app within 30 minutes; decline/expiry moves nothing; the retailer never sees the customer's balance.
- Migration `0007` (bookings, shop_discount_requests, two new ledger types); new pages `/bookings` (booking number, countdown, "I bought it", discount requests) and retailer `Bookings` tab; text in all 8 languages.
- 22 new backend tests (220 total); 360px browser run of the full flow with screenshots in `docs/screenshots/step6b/`.

## Step 6c — Retailer reward offers
- SPEC §4.5 owner decisions recorded: one offer at a time (DB exclusion constraint blocks overlapping periods), points received in the whole period count (booking purchases + discounts on unlisted items), joining needs a live plan, payout = floor(balance at the end × percent), only those end-balance points are removed (later points stay).
- Admin `Rewards` page: create (SUPER_ADMIN), cancel before any payout, participants with collected points / qualifies / payout, record the cash payout with date and reference (SUPER_ADMIN or SUPPORT); payout records are append-only; payouts per retailer must go in offer order (no double cash on the same points).
- Retailer dashboard card: offer terms, join/leave, progress bar, "target reached", payout history; texts in all 8 languages.
- Wallet ledger entries now carry the app clock time, so periods are judged consistently (and testable).
- Migration `0008`; 13 new backend tests (233 total); 360px browser run (admin → retailer → customer purchase → payout) with screenshots in `docs/screenshots/step6c/`.

## Step 7 — Expired-retailer limited access
- SPEC §5 owner decisions recorded: what the limited view shows and for how long, greyed favourites, which retailer screens stay open.
- Customer with an open booking at an expired shop gets a limited view (`/bookings/shop/{slug}`): address, WhatsApp, call, map link, timings and their open bookings — no products; it closes as soon as the booking is bought / forfeited / cancelled. Everyone else still gets "shop not available".
- Favourites keep expired shops, greyed as "Currently unavailable" with no details, or "You have an open booking here" linking to the limited view; renewal brings them back to normal.
- Expired retailer: dashboard says "plan ended — renew, nothing is lost", shows Renew + Bookings, wallet and reward payouts; Products / Share & QR / Customers show a "renew to open this" screen and their APIs return `subscription_required`; bookings list and cancel keep working.
- 3 new + 1 updated backend tests (236 total); 360px browser run with screenshots in `docs/screenshots/step7/`.

## THE-MANAGER resident signup prefill (Showcase side)
- SPEC §4.12 build decisions recorded; the integration doc now says the Showcase side is built.
- `/welcome?prefill=<token>`: the token is removed from the address bar at once and never sent twice; the page has `Referrer-Policy: no-referrer`. The backend redeems it once with THE-MANAGER (same `request_id` on retry), keeps the data 15 minutes in Redis and gives the browser only the mobile number.
- Login opens with that number filled in (editable); after OTP the profile form is filled — only for the same verified number, read once, only empty fields, consent unticked; nothing is stored until Save; email is never stored. Then the resident lands on nearby shops.
- Any problem (unknown / expired / used token, wrong key, THE-MANAGER down, rate limit 20/hour/IP) falls back to the normal signup with a friendly message. A resident can always sign up directly; the account is the mobile number.
- Customers get optional society / address / flat / floor / state and `signup_source` (DIRECT | THE_MANAGER) — migration `0009`.
- Mock THE-MANAGER gained `/dev/shop-now` and the redeem API; 8 new backend tests (244 total); 360px browser run with screenshots in `docs/screenshots/prefill/`.

## Step 8a — Ratings and reviews
- SPEC §4.7 owner decisions recorded (and §4.9 analytics decisions for step 8b).
- Customer rates a purchase — a booking marked "I bought it" or a confirmed discount on an unlisted item — with 1–5 stars and an optional comment, once per purchase, within 30 days, and can change it within those 30 days ("Rate your purchases" on My bookings). Not on your own shop.
- Shop page shows the average, count and latest reviews; names appear as "Ravi V.", never the phone number. `rating_avg` / `rating_count` (used by discovery ranking) count only visible reviews.
- Retailer `Reviews` tab: all reviews, "Report abusive review" with a reason. Admin `Reviews` page: flagged queue, Hide (out of the page and the average) or Keep; any admin role may moderate.
- Migration `0010`; 4 new backend tests (248 total); 360px browser run with screenshots in `docs/screenshots/step8a/`.

## Step 8b — Shop analytics (Insights)
- Shop page sends shop_view (once per browser per 30 min), product_view (when half a product card is on screen), WhatsApp and call clicks; favourite_add, booking_start and booking_confirmed are recorded by the backend itself. Visitor = logged-in customer or a random per-browser id; the retailer's own visits are ignored; no location is stored; per-visitor rate limit; only live shops are tracked.
- Retailer `Insights` tab (PRO / PREMIUM): 7 / 30 / 90 days — visitors, shop views, WhatsApp and call clicks, favourites, booking conversion, a visitors-per-day bar chart with hover/tap details and a table view, new vs returning visitors, bookings, most seen products. BASIC sees "X people viewed your shop in the last 7 days" with an upgrade note; an expired plan shows the renew screen.
- Raw events older than 13 months are deleted by a daily job.
- 4 new backend tests (252 total); 360px browser run (real visitor events + 30 days of sample data in the dev database only) with screenshots in `docs/screenshots/step8b/`.

## Security audit (2026-10-18)
- Full review in four areas (login/sessions, money/points, data exposure, frontend/config/dependencies); 18 findings fixed with regression tests (race tests use real threads and fail on the old code). Details, open items and the production checklist: `docs/SECURITY.md`.
- Highlights: OTPs no longer logged outside dev and production refuses unsafe settings; Postgres/Redis local-only with a Redis password; atomic OTP verification; no name-fishing via shop discount requests; payment/payout race fixes; open redirect closed; CSP and security headers; input limits.
- Frontend now has ESLint (`npm run lint`, 0 errors). Backend: 273 tests passing.

## Step 9 on hold
- Owner decision: courier integration (online orders and delivery) stays pending; SPEC §9 build order marked accordingly.
