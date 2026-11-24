# Environment variables

Names only. No real value ever goes in a document, a commit or a screenshot. Copy `.env.example` to `.env`, fill it in, then run:

- `make check-env` reads your file and lists missing or half filled groups. It prints names, never values.
- `python tools/doctor.py` tests the services that work offline, and `python tools/doctor.py --live` also tests the real ones you switched on. It sends nothing.

**Where each value goes.**

| Place | Which variables |
| --- | --- |
| Local | Everything, in `.env` in the project folder. |
| Vercel | Only `API_BASE_URL` for the web app (project settings, Environment Variables). |
| Railway | Everything else, on the `api` service and the `worker` service. Use variable references so both read the same value. |
| Hetzner | Everything, in `deploy/hetzner/.env` next to the compose file. Never commit it. |

**How each step was checked.** Steps marked VERIFIED were read from the vendor's page on the date shown. Steps marked UNVERIFIED come from our general knowledge of the vendor's screens and must be checked against the page when you do them. Costs are described in plain terms only, because prices change. Read the vendor's price page on the day you decide.

## 1. Core

| Name | Required | What it does |
| --- | --- | --- |
| `DATABASE_URL` | yes | Where data lives. SQLite for the demo, Postgres for real use (`postgresql+psycopg://user:pass@host:5432/name`). |
| `SESSION_SECRET` | yes | Signs the sign in cookie. Make one: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Change it and everyone is signed out. |
| `MODE` | yes | `draft` (default) saves what it would do. `live` lets approved actions leave the app. Only a person changes it, the app never can. |
| `DEMO_MODE` | yes | `true` fills the fictional company and shows the demo bar. Set `false` for a real client. |
| `KILL_SWITCH` | no | `true` blocks every outgoing action. There is also a Pause all button. |
| `OWNER_EMAIL`, `OWNER_PASSWORD_HASH` | outside demo | Make the hash with `python tools/hash_password.py` and keep the single quotes around it. |
| `APPROVER_EMAIL`, `APPROVER_PASSWORD_HASH` | recommended | A second person. Risky actions need someone other than the requester. |
| `VIEWER_EMAIL`, `VIEWER_PASSWORD_HASH` | optional | A read only login (an accountant, a client who only watches). It can see every page and change nothing. |
| `LOGIN_BURST` | no | Sign in tries in a row before a short wait (default 5). Leave it. Only the browser tests raise it. |
| `HANDOFF_DIR`, `UPLOAD_DIR`, `SEED_DIR` | no | Folders for saved drafts, uploaded bills and the demo data. |
| `API_BASE_URL` | web only | The address of the API, no trailing slash. |
| `POSTGRES_PASSWORD` | compose only | Password for the database container. |

Cost: none. Validation: `make check-env`. If wrong you see for example `PROBLEM SESSION_SECRET is missing` or, outside demo mode, `OWNER_PASSWORD_HASH is empty`.

## 2. Company and rules

The reminder, collection and net 30 values are decided defaults (set by the product owner, 2026-11-23). You can change each one for a client. The company name is a placeholder: set the client's real name.

| Name | Default | Meaning |
| --- | --- | --- |
| `COMPANY_NAME` | Birchfield Supply Co | A bill addressed to any other name is flagged. |
| `BASE_CURRENCY` | USD | The company currency: totals, aging and the forecast are shown in it. Amounts in another currency are converted at a rate you type in the app, by date (Reports page). With no rate the item is left out and flagged, never guessed. |
| `REMINDER_WINDOW_START`, `REMINDER_WINDOW_END` | 9 and 17 | Reminders go out on weekdays inside this window in the customer's time zone. |
| `REMINDER_MIN_GAP_DAYS`, `REMINDER_MAX_COUNT` | 5 and 4 | At least 5 days apart and at most 4 per invoice. |
| `COLLECTION_PROB_BP` | current=9500,1-30=9000,31-60=7500,61-90=5000,90+=2000 | The chance, in basis points, that an invoice in each aging group is paid. Used by the forecast. |

## 3. Accounting: QuickBooks Online

Set `ACCOUNTING_ADAPTER=quickbooks`. Variables: `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, `QBO_REFRESH_TOKEN`, `QBO_REALM_ID`, `QBO_ENVIRONMENT` (`sandbox` or `production`), `QBO_MINOR_VERSION`. Keep `ACCOUNTING_WRITE=false` until you have tested.

Steps (UNVERIFIED, Intuit's developer pages are script rendered and could not be read on 2026-11-23, check each against https://developer.intuit.com):

1. Sign in at https://developer.intuit.com and create an app with the accounting scope.
2. Open the app's keys and credentials page. Copy the client ID and client secret for the **sandbox** (development) keys first.
3. Create a sandbox company from the developer dashboard. Its company ID is the `QBO_REALM_ID`.
4. Run Intuit's authorisation flow once to get a refresh token. The authorisation, token endpoints and the accounting scope were VERIFIED against Intuit's discovery document and SDK readme on 2026-11-23. Booklantern keeps the new refresh token each time Intuit returns one.
5. Set `QBO_MINOR_VERSION` to the value on Intuit's current minor version page. Our default of 75 is UNVERIFIED.

Cost: a sandbox is free to create. A real company needs a QuickBooks subscription. Validation: `python tools/doctor.py --live` prints `OK   accounting/quickbooks` or `FAIL accounting/quickbooks: <what Intuit said>`. With a variable missing it prints `FAIL accounting/quickbooks: set QBO_CLIENT_ID, ...`.

## 4. Accounting: Xero and Akaunting (tier B, UNVERIFIED)

- Xero: `XERO_ACCESS_TOKEN`, `XERO_TENANT_ID`. Create an app in the Xero developer portal (https://developer.xero.com), authorise it against a demo company, copy the access token and the tenant ID. Access tokens expire quickly, so this adapter needs a refresh step added before real use. Not verified, the pages could not be read.
- Akaunting: `AKAUNTING_BASE_URL`, `AKAUNTING_USER`, `AKAUNTING_PASSWORD`. You run Akaunting yourself, create a user for the API and use its address. Not verified.

Cost: Xero is a subscription. Akaunting is free to run yourself, and you pay for the server.

## 5. Accounting: CSV

`ACCOUNTING_ADAPTER=csv` and `CSV_FOLDER`. No account. Put files in the folder. Cost: none.

## 6. Payment links: Stripe

Set `PAYMENTS_ADAPTER=stripe` and `STRIPE_SECRET_KEY`. VERIFIED against https://docs.stripe.com/keys on 2026-11-23:

1. Sign in to the Stripe Dashboard and open the API keys page (https://dashboard.stripe.com/apikeys).
2. Work in a **sandbox** first. Sandbox keys start with `sk_test_` (secret) or `rk_test_` (restricted).
3. Stripe recommends a restricted key over a secret key. Follow https://docs.stripe.com/keys/restricted-api-keys to give it only what it needs. Which permission covers creating payment links was not checked, UNVERIFIED.
4. Copy the key when it is shown. In live mode a key you create yourself cannot be shown again, so store it at once in your secrets store.
5. Put it in `STRIPE_SECRET_KEY`. Never in a commit, a screenshot or a chat.

Cost: creating links costs nothing by itself. Stripe charges a fee when a customer pays (read their current price page). Validation: `python tools/doctor.py --live`. A wrong key shows `FAIL payments/stripe: <Stripe's message>`.

## 7. Where bills arrive and reminder email

`INBOX_ADAPTER=imap` and `EMAIL_ADAPTER=smtp`. Variables: `IMAP_HOST`, `IMAP_PORT`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`. The same user and password serve both.

For a Gmail mailbox, VERIFIED against https://support.google.com/accounts/answer/185833 on 2026-11-23:

1. Turn on 2-Step Verification for the Google account. App passwords only work with it on.
2. Open https://myaccount.google.com/apppasswords, sign in and create an app password. Use it as `SMTP_PASSWORD`.
3. Google says you may not be able to create one on a work or school account, with security keys only or with Advanced Protection. Then use another mailbox host.

Host names for Gmail (imap.gmail.com and smtp.gmail.com) come from our general knowledge and are UNVERIFIED. Use a mailbox just for bills. Cost: a free Gmail account works for a test. Validation: `python tools/doctor.py --live`.

## 8. The live reader (optional)

`EXTRACTOR=live`, `LLM_BACKEND=anthropic` and `ANTHROPIC_API_KEY`. `LLM_BACKEND` is `offline` (default, built in stand in, no account), `fixture` (recorded answers from `LLM_FIXTURES_DIR`) or `anthropic`; it wins over the older `LLM_MODE`. Steps: create an account at https://console.anthropic.com, create a key, set it. This path was **never run against the real service** (only a local fake server and recorded answers made from it) and cannot send page images yet (`14-LIMITS-AND-HONEST-NOTES.md`). `EXTRACTOR=live` has a model read each bill and code check it; `REMINDER_WRITER=model` has the model word reminders (default `template`); a failed or refused model call, the kill switch and the call budget (`LLM_CALL_BUDGET`) all fall back to the offline reader or the default wording. The same switch also words the forecast explanation and the month summary. Cost: pay per use, see Anthropic's price page. Leave `LLM_BACKEND=offline` to stay offline.

## 9. Hosting

- Vercel, VERIFIED against https://vercel.com/docs/monorepos on 2026-11-23: choose Create New, then Project, import the repository, press Edit next to Root Directory and pick `apps/web`. Set `API_BASE_URL`. See `06-DEPLOY-VERCEL.md`.
- Railway and Hetzner steps are in `07` and `08` and are UNVERIFIED.

## Advanced overrides

These have sensible defaults and you rarely change them: `QBO_API_BASE`, `QBO_TOKEN_URL`, `XERO_BASE_URL`, `STRIPE_BASE_URL`, `SMTP_USE_TLS`, `IMAP_USE_SSL`, `LLM_HARD_MODEL`, `LLM_BULK_MODEL`. The vendor base addresses are checked so they cannot point at a private network address.
