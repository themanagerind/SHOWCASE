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
