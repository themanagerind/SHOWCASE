# THE-MANAGER → Showcase: Resident Signup Prefill — proposed contract

Status: **DESIGN, not built.** Showcase-side proposal for review by the owner and the THE-MANAGER team.
Agreed principles (from THE-MANAGER): no SSO, OTP on Showcase is mandatory, prefill is only to save typing,
token verified server-to-server with the shared secret, short-lived, single-use, editable before saving.

## 1. Two security gaps in the current design, and the fix

**Gap 1: personal data in the URL.** If the token itself carries name/mobile/address (a signed token such as
a JWT), anyone who sees the URL can read it: signing prevents changes, it does not hide the data. URLs end
up in browser history, server and CDN logs, analytics, and the `Referer` header sent to other sites.

**Gap 2: whoever opens the link first sees the resident's data.** A link forwarded on WhatsApp, or opened on
a shared phone, would show the resident's name, address and flat to someone else.

**Fix (recommended):**
1. The token is an **opaque random value** (≥128 bits, base64url), with no data inside. The data stays in
   THE-MANAGER and is fetched by the Showcase backend with the shared key, the same pattern as wallet redemption.
2. Showcase **reveals the data in steps**. Before OTP, the browser gets only the mobile number (to fill the
   login box). Name, email, address and flat are returned only **after OTP is verified for that same
   mobile**. If the person verifies a different number, the prefill is thrown away.
3. Showcase removes the token from the address bar right away (`history.replaceState`) and the landing page
   sends `Referrer-Policy: no-referrer`.

## 2. THE-MANAGER side (to build)

**"Shop Now" link:** `https://<showcase-host>/welcome?prefill=<token>`

**Token rules:** random opaque value, valid for **5 minutes** (a few seconds is too short on slow 3G phones and
during app switching), single use, bound to one resident.

**Consent (DPDP Act 2023):** before redirecting, THE-MANAGER shows the resident one line, e.g.
"Your name, mobile, flat and society address will be shared with Showcase to fill your signup form." Sharing
personal data with another company needs this notice/consent on THE-MANAGER's side.

**Redeem API** (called only by the Showcase backend):

```
POST {THE_MANAGER_BASE_URL}/api/v1/showcase-prefill/redeem
X-Store-Api-Key: <same shared secret as wallet redemption>
Content-Type: application/json

{ "token": "<token from the URL>", "request_id": "showcase-prefill-<uuid>" }
```

`request_id` gives the same safe-retry behaviour as wallet verify: a retry with the same `request_id`
returns the same 200 again, and any other caller gets 410.

**200**
```json
{
  "name": "Ravi Verma",
  "mobile": "+919876543210",
  "email": null,
  "address": { "society_name": "Green Park Residency", "line": "AB Road", "city": "Indore", "state": "Madhya Pradesh", "pincode": "452010" },
  "flat": { "number": "B-402", "floor": "4" }
}
```

| Status | Meaning | Showcase does |
|---|---|---|
| 401 | key missing/wrong | log for admin; normal signup |
| 404 | unknown token | normal signup |
| 410 | expired or already used | normal signup, message "link expired, please continue" |
| 503 | integration not live | normal signup |

The prefill never blocks signup. Any error simply falls back to the normal form.

## 3. Showcase side (to build after confirmation)

1. `/welcome?prefill=<token>`: the page strips the token from the URL and calls `POST /api/v1/prefill/start {token}`.
2. The Showcase backend redeems the token once with THE-MANAGER and keeps the data **in Redis for 15 minutes only**,
   under a random `prefill_id`. It returns `{prefill_id, mobile}`, and nothing else is sent to the browser.
3. The login screen opens with the mobile filled in. The resident can edit it, then verifies by OTP.
4. After login, `GET /api/v1/prefill/{prefill_id}` (authenticated) returns name/email/address/flat **only if**
   the verified phone equals the prefill mobile. The Redis entry is then deleted.
5. The profile form opens filled in. **Existing values are not overwritten**; only empty fields are filled.
   The contact-consent box stays unticked. The resident saves.
6. The customer is tagged `signup_source = THE_MANAGER` (useful later for wallet redemption and reporting).

Showcase needs new optional profile fields: `email`, `society_name`, `address_line`, `flat_number`, `floor`, `state`.

## 4. Open questions for the owner

1. Approve the **opaque token + server-side fetch** design (instead of putting data in a signed token)?
2. Approve **revealing name/address only after OTP for the same mobile**?
3. Token validity: **5 minutes** OK?
4. Should Showcase **store the address/flat/email** in the customer profile (useful for courier delivery in
   step 9), or use them only to fill the form once? DPDP says to keep minimal data.
5. Landing URL `/welcome?prefill=` OK? (`/signup` is fine too.)
