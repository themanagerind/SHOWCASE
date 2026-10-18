# Security

## Audit 2026-10-18

The whole app was reviewed in four areas: login/sessions, money and points, data exposure, and
frontend/config/dependencies. Every finding below was reproduced first and then fixed with a regression test.
The race-condition tests use real threads against real Postgres/Redis and fail on the old code.

### Fixed

| Severity | Finding | Fix |
|---|---|---|
| High | OTP codes written to the log in every environment (anyone with log access could log in as anyone) | Console SMS only in dev/test; production refuses to start without a real SMS provider |
| High | Postgres and Redis published on all interfaces, Redis without a password (Redis holds OTPs and rate limits) | Bound to 127.0.0.1, Redis password required |
| High | Any retailer could turn a phone number into the person's full name and spam requests | Short name only ("Priya S."), one waiting request per customer, 30 per shop per hour |
| Medium | Parallel wrong OTP guesses got past the 5-attempt limit; one OTP could log in twice; a 500 afterwards | Check-and-count is one Redis transaction; per-IP verify limit |
| Medium | `.env.example` JWT placeholder was accepted; production accepted dev settings | Placeholder refused; `ENV=prod` refuses weak secret, default DB password, console SMS, localhost CORS, dev mock key |
| Medium | Open redirect after login (`/login?next=/\evil.com`) | Destination parsed and limited to the same site |
| Medium | THE-MANAGER code could be used up with no points (lost response, then 503) | Stays PENDING and is retried with the same `request_id` |
| Medium | Two payments settling together got the same period | Subscription row locked first |
| Medium | Retailer bookings list showed full customer numbers without consent | Masked without consent, like the customer list (SPEC §4.2) |
| Medium | Photo URLs unvalidated (huge strings, `javascript:`/`data:`), unlimited timings, no body-size limit | https only ≤ 500 chars, ≤ 4 ranges/day, 1 MB request limit |
| Medium | `/events` could be flooded with a new `anon_id` per request; clicks not de-duplicated | Per-IP cap; every event type counted once per 30 min per visitor |
| Medium | No frontend security headers (clickjacking, no CSP) | CSP, `frame-ancestors 'none'`, nosniff, Referrer-Policy, Permissions-Policy, HSTS; API sends its own |
| Low | Reward offer could be cancelled after a payout was recorded (race) | Offer row locked in `record_payout` |
| Low | Manual "Mark paid" retry gave two periods; SUPPORT could set any amount | Reference unique per manual payment; a different amount is SUPER_ADMIN only |
| Low | `null` in PATCH bodies gave 500; huge `offset` gave 500 | 422 for required fields; offsets capped |
| Low | Expired retailer could still edit products | Needs a live plan (SPEC §5) |
| Low | Service worker cached `/welcome?prefill=<token>`; logout kept caches | URLs with a query are never cached; logout clears caches and session storage |
| Low | `/docs` public; dev mock key and tests in the image | Docs off in production; mock and tests excluded from the image |

Checked and fine: JWT algorithm/expiry/type checks, immediate session revocation, refresh rotation with reuse
detection, admin 12-hour limit, role checks re-read from the database, constant-time OTP and Razorpay
signature checks, Razorpay amounts from the server quote, append-only ledgers, booking/discount state machines
and lock order, ownership checks on every client-supplied id, LIKE escaping in product search, no
`dangerouslySetInnerHTML`/`eval`, no secrets in git history, `npm audit --omit=dev` and `pip-audit` clean.

### Open (accepted for now, revisit before launch)

- **SMS provider**: needed before production (MSG91 or similar). Until then `ENV=prod` will not start, by design.
- **Tokens in localStorage**: the CSP reduces the risk; moving the refresh token to an HttpOnly cookie is planned.
- **OTP send cap per phone** (10/day) can be used by someone else to block a number for the rest of the UTC day.
  Mitigated by per-IP limits; a CAPTCHA after a few sends would close it.
- **One secret for JWT, OTP and wallet-code HMACs**: separate keys would limit damage if one leaks.
- **Backend dependency lock file**: `pyproject.toml` uses ranges; add a hashed lock before the first deployment.
- **Retailer photos** are any https link (visitors' IPs reach that host); own upload storage later.
- Dev-only lint packages (`eslint-config-next`) have advisories in their glob dependencies; they are not shipped.

## Production checklist

1. `.env`: `ENV=prod`, `JWT_SECRET=$(openssl rand -hex 32)`, strong `POSTGRES_PASSWORD` and `REDIS_PASSWORD`
   (also inside `DATABASE_URL` / `REDIS_URL`), real `CORS_ORIGINS`, `PUBLIC_BASE_URL`, a real `SMS_PROVIDER`.
2. Put a TLS reverse proxy in front and set `FORWARDED_ALLOW_IPS` to its address only (never `*`).
3. Do not publish Postgres/Redis ports beyond 127.0.0.1.
4. `THE_MANAGER_API_KEY` = THE-MANAGER's `ECOM_STORE_API_KEY` (never the dev mock key); Razorpay live keys and
   webhook secret only in `.env`.
