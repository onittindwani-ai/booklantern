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
| Hetzner | Everything, in `.env` at the repository root next to `docker-compose.yml` (see `08-DEPLOY-HETZNER.md`). Never commit it. |

**How each step was checked.** Steps marked VERIFIED were read from the vendor's page on the date shown. Steps marked UNVERIFIED come from our general knowledge of the vendor's screens and must be checked against the page when you do them. Costs are described in plain terms only, because prices change. Read the vendor's price page on the day you decide.

## 1. Core

| Name | Required | What it does |
| --- | --- | --- |
| `APP_NAME` | no | A short name (default `booklantern`). It is also the key the live model's spend limit is counted under. |
| `DATABASE_URL` | yes | Where data lives. SQLite for the demo, Postgres for real use (`postgresql+psycopg://user:pass@host:5432/name`). |
| `SESSION_SECRET` | yes | Signs the sign in cookie. At least 32 random characters, and the app will not start with the example value when `DEMO_MODE` is `false`. Make one: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Change it and everyone is signed out. |
| `MODE` | yes | `draft` (default) saves what it would do. `live` lets approved actions leave the app. Only a person changes it, the app never can. |
| `DEMO_MODE` | yes | `true` fills the fictional company and shows the demo bar. Set `false` for a real client (the example file already says `false`). Demo shortcuts (the public demo password, the example approver and viewer logins, the demo buttons, the made up demo date, loading the sample data) work only while `DEMO_MODE=true` and `OWNER_PASSWORD_HASH` is empty. |
| `ALLOW_DEMO_SERVER` | no | The app refuses `DEMO_MODE=true` on a Postgres database unless this is `true`. Leave it `false`. |
| `MAX_BODY_BYTES` | no | The largest request the API accepts (default 25 MB, 26214400). Uploads are counted as they arrive, so a file with no declared size is cut off too. |
| `LOG_LEVEL` | no | `DEBUG`, `INFO` (default), `WARNING` or `ERROR`. Bill text and bank lines are never written to the log at any level. |
| `KILL_SWITCH` | no | `true` blocks every outgoing action. There is also a Pause all button. |
| `OWNER_EMAIL`, `OWNER_PASSWORD_HASH` | outside demo | Make the hash with `python tools/hash_password.py` and keep the single quotes around it. |
| `APPROVER_EMAIL`, `APPROVER_PASSWORD_HASH` | recommended | A second person, who must have a different address from the owner and the viewer (the app will not start otherwise). What a second person is needed for is listed in `13-SECURITY-AND-DATA.md`, in the bullet Who decides what. |
| `VIEWER_EMAIL`, `VIEWER_PASSWORD_HASH` | optional | A read only login (an accountant, a client who only watches). It can see every page and change nothing. |
| `LOGIN_BURST` | no | Sign in tries in a row before a short wait (default 5), counted for each account on each network address and, at six times the number (at least 30), for each network address alone. There is deliberately no limit on an account across all addresses, so a stranger can never keep the owner out. Leave it. Only the browser tests raise it. |
| `HANDOFF_DIR`, `UPLOAD_DIR` | no | Folders for saved drafts and uploaded bills (defaults `./handoff` and `./uploads`). |
| `SEED_DIR` | demo only | The folder that holds the demo data (`seed.json`). It is looked up here first, so an installed copy that has no repository next to it works. Not needed outside demo mode. |
| `API_BASE_URL` | web only | The address of the API, no trailing slash. |
| `POSTGRES_PASSWORD` | compose only | Password for the database container. Letters and digits only (or percent-encoded), because it is placed inside the database address: make one with `openssl rand -hex 24`. |

Cost: none. Validation: `make check-env`. If wrong you see for example `PROBLEM SESSION_SECRET is missing` or, outside demo mode, `OWNER_PASSWORD_HASH is empty`.

### Which adapter each job uses

Every one of these defaults to the offline choice, so nothing reaches an outside service until you change it.

| Name | Values | What it chooses |
| --- | --- | --- |
| `ACCOUNTING_ADAPTER` | `seed` (default), `quickbooks`, `xero`, `akaunting`, `csv` | Where approved bills are posted as drafts and open invoices are read from. |
| `PAYMENTS_ADAPTER` | `seed` (default), `stripe` | Who creates the payment link for an invoice. |
| `INBOX_ADAPTER` | `seed` (default), `imap` | Where bills arrive. |
| `EMAIL_ADAPTER` | `seed` (default), `smtp` | How approved reminders are sent. |
| `EXTRACTOR` | `offline` (default), `live` | Who reads a bill: the built in reader, or a language model whose answers code checks. |
| `REMINDER_WRITER` | `template` (default), `model` | The wording of a reminder: the default text, or a model's wording that code checks and a person approves. |

## 2. Company and rules

The reminder, collection and net 30 values are decided defaults (set by the product owner, 2026-11-23). You can change each one for a client. The company name, address and reply address are about your business, so set them before anything leaves the app.

| Name | Default | Meaning |
| --- | --- | --- |
| `COMPANY_NAME` | Birchfield Supply Co | Your company name. A bill addressed to any other name is flagged, and every reminder is signed with it. Leaving the placeholder keeps a real install out of live mode (the app lists it as a problem and refuses to start with `MODE=live`). |
| `COMPANY_ADDRESS` | empty | Your postal address on one line. It is printed in the footer of every reminder. Needed (at least 10 characters) before reminders go out for real. |
| `REPLY_TO` | empty | Where customers answer a reminder, and the address in the unsubscribe header. Empty means `EMAIL_FROM`. When the bills mailbox is also the sender mailbox (`INBOX_ADAPTER=imap` and `EMAIL_ADAPTER=smtp`) it must be set to a mailbox a person reads, and not to the bills mailbox itself: the app refuses to start in live mode otherwise, because a customer's "stop" would sit among the bills. |
| `INTAKE_ALLOWED_SENDERS` | empty | Comma separated addresses or `@domain` entries whose email may bring bills, for example `billing@vendor.example,@supplier.example`. Empty means anyone who knows the intake address. A bill from any other sender is kept, but it carries a blocking finding until a person approves it with a written reason. A From line can be forged, so this narrows the door, it does not lock it. |
| `DEFAULT_TIMEZONE` | America/New_York | The time zone given to a customer imported or typed in without one, for example `Europe/London`. Reminders are sent inside the window in each customer's own time zone. |
| `BASE_CURRENCY` | USD | The company currency: totals, aging and the forecast are shown in it. Amounts in another currency are converted at a rate you type in the app, by date (Reports page). With no rate the item is left out and flagged, never guessed. |
| `REMINDER_WINDOW_START`, `REMINDER_WINDOW_END` | 9 and 17 | Reminders go out on weekdays inside this window in the customer's time zone. |
| `REMINDER_MIN_GAP_DAYS`, `REMINDER_MAX_COUNT` | 5 and 4 | At least 5 days apart and at most 4 per invoice. |
| `COLLECTION_PROB_BP` | current=9500,1-30=9000,31-60=7500,61-90=5000,90+=2000 | The chance, in basis points, that an invoice in each aging group is paid. Used by the forecast. |

## 3. Accounting: QuickBooks Online

Set `ACCOUNTING_ADAPTER=quickbooks`. Variables: `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, `QBO_REFRESH_TOKEN`, `QBO_REALM_ID`, `QBO_ENVIRONMENT` (`sandbox` or `production`), `QBO_MINOR_VERSION`. Keep `ACCOUNTING_WRITE=false` until you have tested (`ACCOUNTING_WRITE` is the switch that lets approved bills be posted as drafts; it also needs `MODE=live`). `QBO_API_BASE` and `QBO_TOKEN_URL` are advanced overrides, empty or the usual address by default. All four of `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, `QBO_REFRESH_TOKEN` and `QBO_REALM_ID` are needed together, or none. Each post carries a request id, so a repeat never makes a second bill.

Steps (UNVERIFIED, Intuit's developer pages are script rendered and could not be read on 2026-11-23, check each against https://developer.intuit.com):

1. Sign in at https://developer.intuit.com and create an app with the accounting scope.
2. Open the app's keys and credentials page. Copy the client ID and client secret for the **sandbox** (development) keys first.
3. Create a sandbox company from the developer dashboard. Its company ID is the `QBO_REALM_ID`.
4. Run Intuit's authorisation flow once to get a refresh token. The authorisation, token endpoints and the accounting scope were VERIFIED against Intuit's discovery document and SDK readme on 2026-11-23. Booklantern keeps the new refresh token each time Intuit returns one.
5. Set `QBO_MINOR_VERSION` to the value on Intuit's current minor version page. Our default of 75 is UNVERIFIED.

Cost: a sandbox is free to create. A real company needs a QuickBooks subscription. Validation: `python tools/doctor.py --live` prints `OK   accounting/quickbooks` or `FAIL accounting/quickbooks: <what Intuit said>`. With a variable missing it prints `FAIL accounting/quickbooks: set QBO_CLIENT_ID, ...`.

## 4. Accounting: Xero and Akaunting (tier B, UNVERIFIED)

- Xero: `XERO_ACCESS_TOKEN`, `XERO_TENANT_ID` (both or none), and `XERO_BASE_URL` (default `https://api.xero.com`). Create an app in the Xero developer portal (https://developer.xero.com), authorise it against a demo company, copy the access token and the tenant ID. Access tokens expire quickly, so this adapter needs a refresh step added before real use. Not verified, the pages could not be read.
- Akaunting: `AKAUNTING_BASE_URL`, `AKAUNTING_USER`, `AKAUNTING_PASSWORD` (all or none; the adapter sends no repeat key, so post a bill once). You run Akaunting yourself, create a user for the API and use its address. Not verified.

Cost: Xero is a subscription. Akaunting is free to run yourself, and you pay for the server.

## 5. Accounting: CSV

`ACCOUNTING_ADAPTER=csv` and `CSV_FOLDER` (default `./csv-in`). No account. The folder holds `invoices.csv` and receives `draft-bills.csv`; cells that start like a formula are written as plain text. Cost: none.

## 6. Payment links: Stripe

Set `PAYMENTS_ADAPTER=stripe` and `STRIPE_SECRET_KEY` (`STRIPE_BASE_URL` is the advanced override, default `https://api.stripe.com`). VERIFIED against https://docs.stripe.com/keys on 2026-11-23:

1. Sign in to the Stripe Dashboard and open the API keys page (https://dashboard.stripe.com/apikeys).
2. Work in a **sandbox** first. Sandbox keys start with `sk_test_` (secret) or `rk_test_` (restricted).
3. Stripe recommends a restricted key over a secret key. Follow https://docs.stripe.com/keys/restricted-api-keys to give it only what it needs. Which permission covers creating payment links was not checked, UNVERIFIED.
4. Copy the key when it is shown. In live mode a key you create yourself cannot be shown again, so store it at once in your secrets store.
5. Put it in `STRIPE_SECRET_KEY`. Never in a commit, a screenshot or a chat.

Cost: creating links costs nothing by itself. Stripe charges a fee when a customer pays (read their current price page). Validation: `python tools/doctor.py --live`. A wrong key shows `FAIL payments/stripe: <Stripe's message>`.

## 7. Where bills arrive and reminder email

`INBOX_ADAPTER=imap` and `EMAIL_ADAPTER=smtp`. Variables: `IMAP_HOST`, `IMAP_PORT`, `IMAP_USE_SSL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `EMAIL_FROM`. The same user and password serve both. Both connections check the server's certificate. `IMAP_USE_SSL=false` and `SMTP_USE_TLS=false` (plain text) are refused for every host except `127.0.0.1`, so they work only for a test against a local fake server. A bill is marked read only after it has been saved, so a failure never loses a mail. A message with no bill in it (a customer's answer, a mail over the size limit) is left unread in the mailbox and, when it comes from a customer or asks to stop, is shown on the Exceptions page. Every reminder carries your name and address and an unsubscribe header pointing at `REPLY_TO` (or `EMAIL_FROM`).

For a Gmail mailbox, VERIFIED against https://support.google.com/accounts/answer/185833 on 2026-11-23:

1. Turn on 2-Step Verification for the Google account. App passwords only work with it on.
2. Open https://myaccount.google.com/apppasswords, sign in and create an app password. Use it as `SMTP_PASSWORD`.
3. Google says you may not be able to create one on a work or school account, with security keys only or with Advanced Protection. Then use another mailbox host.

Host names for Gmail (imap.gmail.com and smtp.gmail.com) come from our general knowledge and are UNVERIFIED. Use a mailbox just for bills. Cost: a free Gmail account works for a test. Validation: `python tools/doctor.py --live`.

## 8. The live reader (optional)

`EXTRACTOR=live` (default `offline`), `LLM_BACKEND=anthropic` and `ANTHROPIC_API_KEY`. The other switches, all optional: `LLM_MODE` (the older switch), `LLM_MODEL` (one model id for both kinds), `LLM_HARD_MODEL` and `LLM_BULK_MODEL`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_VERSION`, `LLM_TIMEOUT`, `LLM_MAX_TOKENS`, `LLM_MAX_RETRIES`, `LLM_BUDGET_USD` (most tracked dollars), `LLM_THINKING` (`default` or `off`), `LLM_FIXTURES_DIR`, `LLM_RECORD`, `LLM_REDACT` and `LLM_LOG_PROMPTS` (leave it `false`: it would write bill text into the log). Pages a visitor with a read only login opens never call the paid model. `LLM_BACKEND` is `offline` (default, built in stand in, no account), `fixture` (recorded answers from `LLM_FIXTURES_DIR`) or `anthropic`; it wins over the older `LLM_MODE`. Steps: create an account at https://console.anthropic.com, create a key, set it. This path was **never run against the real service** (only a local fake server and recorded answers made from it) and cannot send page images yet (`14-LIMITS-AND-HONEST-NOTES.md`). `EXTRACTOR=live` has a model read each bill and code check it; `REMINDER_WRITER=model` has the model word reminders (default `template`); a failed or refused model call, the kill switch and the call budget (`LLM_CALL_BUDGET`) all fall back to the offline reader or the default wording. The same switch also words the forecast explanation and the month summary. Cost: pay per use, see Anthropic's price page. Leave `LLM_BACKEND=offline` to stay offline.

## 9. The Docker path, step by step

Docker compose reads `deploy/hetzner/.env` or the `.env` next to `docker-compose.yml`. Before the first start, set these, in this order, because the stack refuses to start without them:

1. `DEMO_MODE=false`.
2. `SESSION_SECRET`: 32 or more random characters (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`).
3. `OWNER_PASSWORD_HASH`: from `python tools/hash_password.py`, inside single quotes.
4. `POSTGRES_PASSWORD`: letters and digits only, or percent-encoded (`openssl rand -hex 24`).
5. `COMPANY_NAME`, `COMPANY_ADDRESS`, `EMAIL_FROM`, `REPLY_TO` and `DEFAULT_TIMEZONE`.

A real install starts empty. Add its data from the app's setup pages or with `python tools/load_data.py` (`05-RUN-LOCALLY.md`, "A real install").

## 10. Hosting

- Vercel, VERIFIED against https://vercel.com/docs/monorepos on 2026-11-23: choose Create New, then Project, import the repository, press Edit next to Root Directory and pick `apps/web`. Set `API_BASE_URL`. See `06-DEPLOY-VERCEL.md`.
- Railway and Hetzner steps are in `07` and `08` and are UNVERIFIED.

## Advanced overrides

These have sensible defaults and you rarely change them: `QBO_API_BASE`, `QBO_TOKEN_URL`, `XERO_BASE_URL`, `STRIPE_BASE_URL`, `SMTP_USE_TLS`, `IMAP_USE_SSL`, `LLM_HARD_MODEL`, `LLM_BULK_MODEL`, `ANTHROPIC_BASE_URL`. The vendor base addresses are checked so they cannot point at a private network address.

`python -m pytest apps/api/tests/test_hardening_ops.py` fails when a setting exists in the code but is missing from this page or from `.env.example`.
