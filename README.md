# SHOWCASE

Online storefront PWA for offline retailers in India. **Read [SPEC.md](SPEC.md) first** — it is the single source of truth.

## Run with Docker

```bash
cp .env.example .env          # fill in real values (openssl rand -hex 32 for JWT_SECRET)
docker compose up --build     # App: http://localhost:3000  API docs: http://localhost:8001/docs
```

## Backend development

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8001
```

## Tests

Tests need PostgreSQL with PostGIS and run against the real Alembic migration (database `showcase_test`, override with `TEST_DATABASE_URL`).

```bash
cd backend && .venv/bin/pytest
```

## Frontend development

```bash
cd frontend && npm install
npm run dev                   # http://localhost:3000 (expects the API on :8001)
npm run typecheck && npm run build
```

Demo data for local testing: `cd backend && .venv/bin/python -m scripts.seed_demo`, then open http://localhost:3000/sharma-electronics?src=qr (dev OTPs are printed in the API log).

## Admin access

```bash
cd backend && .venv/bin/python -m scripts.create_admin --phone 98XXXXXXXX            # SUPER_ADMIN
cd backend && .venv/bin/python -m scripts.create_admin --phone 98XXXXXXXX --role SUPPORT
```

The admin logs in with OTP like everyone else and gets an **Admin** link (`/admin`).

## Online payments (Razorpay)

Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` in `.env`, and in the Razorpay
dashboard add a webhook to `https://<api-host>/api/v1/webhooks/razorpay` for `payment.captured`.
Until the keys are set, retailers see "pay the Showcase team by UPI" and admins record payments manually.

## THE-MANAGER wallet codes (local testing)

```bash
cd backend && MOCK_TM_KEY=dev-shared-key .venv/bin/uvicorn scripts.mock_the_manager:app --port 8000
# Showcase .env: THE_MANAGER_BASE_URL=http://localhost:8000  THE_MANAGER_API_KEY=dev-shared-key
```
Demo codes: `DEMO1500` (₹1,500), `DEMO0500`, `SHOP2500`, `TINY0100`. For production set the real THE-MANAGER URL and the
shared key (same value as THE-MANAGER's `ECOM_STORE_API_KEY`).
