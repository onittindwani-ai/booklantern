# Changelog

## 1.0.1 (2026-11-25)

A hardening release: the fixes of a second, stricter self review, in plain words.

- Demo and real installs: the public demo password, the example approver and viewer logins, the demo buttons, the made up demo date and the loading of sample data now work only when `DEMO_MODE=true` and no `OWNER_PASSWORD_HASH` is set. A restart can no longer erase or reload a database that holds data. The example `.env` now says `DEMO_MODE=false`.
- A real install is usable from nothing: vendors (with the bank account on file), customers, open invoices, bank accounts, the chart of accounts and repeating items can be added through new owner only API routes, CSV imports and `tools/load_data.py`. Business name, address, reply address, currency and time zone are settings (`COMPANY_NAME`, `COMPANY_ADDRESS`, `REPLY_TO`, `BASE_CURRENCY`, `DEFAULT_TIMEZONE`); the placeholder company name keeps a live install from starting.
- Reminders carry your name, your postal address, a plain way to stop them and an unsubscribe header. A placeholder payment link is never stored or sent.
- Bill intake: one damaged or hostile attachment no longer loses the other bills in the same mailbox poll (each document is saved on its own, a mail is marked read only after saving, failures are logged without bill text). Mail is read without marking it read, and size and message count limits apply.
- Bill checks: the duplicate and changed bank account checks work with no vendor list, bank details printed as a routing and account pair are read, and a vendor with an account on file whose bill shows none is held back. Amounts of 20 digits, very long text, negative totals and unknown currency codes are limited and flagged instead of breaking a save. Text that looks like markup no longer breaks the month end PDF.
- Safety: mail connections check the server certificate and refuse plain text except to this computer; uploads are read with a size limit as they arrive; the page picture of a huge page is drawn small; the kill switch and force draft set in the app hold for posting, sending and payment links; approve, reject, post and bank links cannot be done twice by two clicks; repeated accounting posts carry a request or idempotency key; spreadsheet cells that start like a formula are written as plain text; a viewer's page never makes a paid model call.
- Sign in: one cleaned email is used for the limit and the lookup, field lengths are limited, and there is a second limit by network address. The web app passes on only the last address of `X-Forwarded-For`.
- Operations: alembic and the worker read the same settings file as the API (`ENV_FILE`), with no silent SQLite fallback; the backup script works from cron, keeps no empty dump and saves the uploads; the data folder is found through `SEED_DIR` first.
- Docs and tooling: `.env.example` and `docs/04-ENVIRONMENT-VARIABLES.md` list every setting, and a test fails when one is missing; the docs no longer say the Docker images were never built (CI builds them and starts the stack, no real host was used); Windows and `python3-venv` notes; `SECURITY.md` points to the private Security tab; the web app has an error page and a not found page.
- Versions: the API, the root package and the web package are all 1.0.1.

Second independent audit (same release):

- A person can no longer clear the finding their own edit raised. Approving a bill that has, or ever had, a blocking finding is refused for whoever changed the bill or closed one of its findings, and an approver cannot close a blocking finding on a bill they edited. The owner may do both on their own work with a written reason, logged as `self_review`. A closed blocking finding opens again when the same check fires after another edit. The docs now say exactly this (`02`, `04`, `11`, `13`, `14`).
- A bill paid by a matched bank line is marked paid (a part payment lowers what is owed, taking the match away makes it payable again), so payables and the forecast no longer count it twice.
- The same vendor, bill number and amount is a blocking duplicate on any date or with no date; punctuation, case and zero padding in the number are ignored.
- A 1.4 KB PDF can no longer exhaust memory when the live reader lays out its text, and a document whose reading was started three times and never finished goes to a person instead of blocking intake (new column `read_attempts`, migration 0003).
- QuickBooks, Xero and Akaunting drafts carry the tax and the lines of the approved bill; the total the accounting system reports is compared with the approved total and a draft with another total sends the bill back to review instead of counting as posted. These adapters are still tested only against stand ins.
- An edit cannot change a bill that was approved a moment earlier; a network error while posting gives a safe message and an audit row instead of a crash; a reminder is marked as being sent before the mail leaves, so a stop in between never sends it twice; the CSV adapter names a missing column or a bad amount; the backup script fails loudly when the uploads cannot be archived.
- Every change made with the browser cookie alone needs the `x-booklantern: 1` header at the API as well; there is no limit on an account across all addresses (a stranger could keep the owner out); an approver or viewer email equal to the owner's stops the app from starting.
- The review page tells the person when they changed the bill or closed a finding on it (the owner is asked for a written reason, anyone else is told someone else has to approve), a taken back payment never moves a bill into a state nobody approved, and SQLite files made by an earlier version get the new `read_attempts` column added at start.
- Docs: Hetzner env file location, `FORWARDED_ALLOW_IPS` on Railway, how to pin the Docker base images by digest, the header of `constraints.txt`.

### Also in this release (earlier work that was not yet released)

- Round 5 walk through every screen as a first time owner: a bill with no vendor, date or total cannot be approved; a vendor typed on the review page is saved and matched to the vendor list; amounts and dates are checked in the page before saving; a scanned bill shows its picture; closing a blocking finding needs a written reason; a promise to pay needs a real date that is not in the past and a newer promise replaces the old one; a bank file must have Date, Description and Amount, one currency, no zero lines, and the balance counts only lines in the account currency; money that came in links only to an invoice and money that went out only to a bill; a row that is gone answers 404; reset no longer drops the tables; viewers see write controls disabled; Pause all and Sign out stay on a phone; sign in returns to the page asked for; the audit log reads in plain words and opens a detail sheet; text copied from another product removed from the CSV picker.
- Renamed from Ledgerlight to Booklantern after a public name check.
- Bill reader version 2 (every page, nine languages, number and date styles, credit notes), tested on two independent sets of bills.
- Model path behind the base wrapper (bill reading, forecast and month wording, reminder wording) with checks by code, a hostile text guard and recorded fixtures; live use unverified.
- Contract tests for the QuickBooks, CSV and mail adapters; more currencies; printed tax rate compared with the vendor's usual rates.

## 1.0.0

First release. Bill intake with an offline reader, checks by code, review screen, collections ladder with stop rules, CSV bank reconciliation, 13 week cash forecast, month end PDF, eleven pages, adapters for QuickBooks (tested against a stand in), Xero and Akaunting (written from documentation), CSV, Stripe payment links and IMAP. See `docs/14-LIMITS-AND-HONEST-NOTES.md` for what was and was not run.
