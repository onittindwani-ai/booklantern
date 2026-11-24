# Booklantern specification

Booklantern is a finance back office for a small business, set up and run by an implementer for one client per copy. It reads vendor bills, checks them with code, chases late customers, matches the bank statement and shows a 13 week cash forecast. It never moves money. It does not give tax or accounting advice.

All people, companies, bank lines and numbers in the seed data are fictional and labelled as such.

## 1. Hard rules

1. Money is integer minor units plus a currency code, everywhere (database, API, code). No floats touch money. One module, `money.py`, owns rounding (half up, documented) and splitting (largest remainder).
2. Every total, tax figure, aging bucket, match score and forecast number comes from code. A model (or the offline stand in) only writes explanation text, and only from numbers passed to it.
3. Never moves money. No payment initiation, no bank credentials. The bank side is CSV import only.
4. Read only against the accounting system by default (`ACCOUNTING_WRITE=false`). Draft mode (the default) posts and sends nothing: it saves what it would have done.
5. Text in documents, emails and bank descriptions is untrusted data. It is wrapped before any model prompt and can never trigger an action.
6. Reminders obey stop rules before anything else (see section 5).

## 2. Entities (tables use the prefix `ll_`)

Vendor, Customer, Document, Bill (+ BillLine), Invoice (+ InvoiceLine), Payment (+ PaymentAllocation), Reminder, PromiseToPay, Account, BankAccount, BankTransaction, Match, RecurringItem, Forecast, Scenario, Exception, State.

## 3. Pipelines

1. Intake: upload, or IMAP mailbox (attachments that are PDFs or images). Each file is hashed; the same file twice is one Document.
2. Extraction: the extractor turns a Document into fields with a confidence per field and the page position (box) of each value. Demo mode uses an offline stand in that reads the text layer of the PDFs the seed generator makes. It is NOT a language model. Scanned pages (images in a PDF) have no text layer: the stand in says so and the bill goes to manual entry. The live path through the base model wrapper is written and UNVERIFIED (never run).
3. Validation by code: line sums, subtotal plus tax equals total, tax rate sanity, duplicates (exact and near), amount against the vendor's history, changed bank details, missing purchase order, date in the future, currency mismatch, bill addressed to another company. Each finding is an Exception with a severity.
4. Review queue: a person edits fields, sees the boxes on the page, approves. Approval makes a draft posting for the accounting adapter.
5. Receivables: aging by code, reminder ladder with tones and stop rules, promises to pay, payment link (Stripe adapter, draft mode makes a placeholder, never moves money).
6. Reconciliation: bank CSV import (dedupe by hash), scored matching, split detection, exceptions.
7. Forecast: 13 weeks, deterministic, from open invoices (collection probability by aging bucket and per customer pay habit), open bills, recurring items and the bank balance. Scenarios change inputs (collect later, delay a payment, add a hire). The slider in the Cash cockpit asks the API, which runs the same function.
8. Month end pack: a PDF built by code (reportlab) with the totals, aging, unmatched items, exceptions and forecast.

## 4. Adapters

| Category | Adapter | Tier | Notes |
| --- | --- | --- | --- |
| accounting | seed (offline), csv, quickbooks (QBO), xero, akaunting | A (seed, csv, quickbooks against a mock), B (xero, akaunting) | read first; create draft bill only when `ACCOUNTING_WRITE=true`, mode live and approved |
| payments | seed, stripe (payment links) | B | creates a payment link; never captures or moves money |
| inbox | seed, imap (Gmail app password or any IMAP host) | A against a fake IMAP server | only reads unseen messages |

## 5. Reminder stop rules (tested as properties)

Never send a reminder when: the invoice is paid or voided; the customer opted out; the customer has a bankruptcy flag; the invoice is in dispute; an unbroken promise to pay has a date still in the future; the maximum count is reached; it is outside the send window (weekdays, 09:00 to 17:00 in the customer's time zone) in which case it waits; less than the minimum gap since the last one; kill switch on; mode is draft (a draft is saved instead). A payment, a dispute or a promise recorded after a reminder was drafted cancels that draft before it is sent.

## 6. Evals

- Extraction accuracy per field on the dev set, and on a held out set of 24 documents written first, in different layouts and wording, scored once untouched.
- Duplicate detection precision and recall against the answer key.
- Reconciliation accuracy against the answer key.
- Property tests: sums equal parts, allocations never exceed amounts, forecasts are deterministic, reminder stop rules hold on random worlds.

## 7. API (all under /api, session required except login)

auth (login, logout, me), overview, documents (list, upload, detail, page image, extract), bills (list, detail, patch fields, approve, reject, post draft), vendors, customers, invoices (list, detail), aging (summary and drill down), collections (reminders list, approve, send, promises, dispute, opt out), payments link, bank (transactions list, CSV import, matches suggest, link, unlink), exceptions (list, resolve), forecast (get, scenario run), reports (month end pack PDF), integrations (list, test), approvals, audit, settings, events stream, demo (reset, tick, advance).

## 8. Pages

Cash cockpit (forecast chart and scenario slider), Invoice review (page left, fields right, linked highlights), Bills and payables, Aging, Collections, Reconciliation, Exceptions, Reports, Integrations, Approvals, Audit log.

## 9. Jobs

intake poll, extract, validate, reminders tick, reconcile suggest, forecast refresh, month end report.

## 10. Environment variables

See `docs/04-ENVIRONMENT-VARIABLES.md`: core settings from the base, `ACCOUNTING_ADAPTER`, `PAYMENTS_ADAPTER`, `INBOX_ADAPTER`, `ACCOUNTING_WRITE`, QuickBooks, Xero, Akaunting, Stripe and IMAP settings, and the founder rules (collection probabilities, ladder, send window), each a decided default that the implementer can change.
