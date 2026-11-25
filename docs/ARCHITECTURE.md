# Architecture

## Pieces

- **API** (`apps/api`, FastAPI, SQLAlchemy 2, Alembic). Everything that matters happens here. <!--n:api_paths-->61<!--/n--> paths, <!--n:tables-->20<!--/n--> tables with the prefix `ll_`. The OpenAPI file is `docs/openapi.json`.
- **Worker** (`python -m booklantern.worker`). Runs four jobs on a timer: read the mailbox, send or draft reminders, suggest bank matches, refresh the forecast.
- **Web** (`apps/web`, Next.js 16, React 19, TanStack Query, the shared plain CSS kit). It never talks to vendors. It forwards to the API and adds a required header to every change.
- **Base** (`packages/core-py`, `packages/ui-kit`). Shared with the other systems and never edited here: write guard, approvals, audit chain, job runner, text model wrapper, adapter registry.
- **Adapters** (`apps/api/src/booklantern/adapters`). Accounting (seed, csv, quickbooks, xero, akaunting), payments (seed, stripe), inbox (seed, imap), email (seed, smtp).

## One rule that shapes everything

**Code does the maths and the checks. A model only words things.** Totals, tax, aging, match scores and the forecast come from code with integers. The offline stand in or a model may write a short explanation, and only from numbers handed to it.

## Money

Amounts are whole numbers in the smallest unit (cents) plus a currency code. No decimals touch money. Rounding is half away from zero and lives in one module, `money.py`. Rates are whole numbers in basis points (1 bp is 0.01 percent). Splitting a total uses the largest remainder method so the parts always add up exactly. The one place a decimal is made is a number sent to a vendor's JSON body.

## Bill intake

1. A file arrives by upload or the mailbox. It is hashed, so the same file twice is one document.
2. The reader turns it into fields. Each field has a confidence and a box on the page (fractions of the page, so the screen can draw it at any size).
3. Code validates: line sums, subtotal plus tax equals total, tax rate against the vendor's on file, duplicates (the same vendor, bill number and amount on any date, with punctuation and zero padding in the number ignored, is blocking; near: same amount, similar number, within 3 days), amount above 4 times the vendor's usual (needs at least 3 past bills), changed bank details, missing purchase order, date in the future, currency mismatch, wrong company. Each finding has a severity. A blocking one needs a written reason to approve.
4. A person reviews and approves. Approval makes a draft for the accounting adapter.

### How the offline reader scores confidence

The reader reads text rectangles from the PDF and groups them into rows. A value starts from a found label at 60, adds 15 if it parses, 5 if it sits to the right of its label, then 15 if a cross check agrees (for example the lines add up) or minus 25 if one disagrees. A value with no label is a guess at 45, plus 10 if it parses. The review screen prints these reasons next to each field.

## Collections

Aging buckets: not due, 1 to 30, 31 to 60, 61 to 90, over 90. The ladder decides, for each open invoice, one of send, wait or stop, and says why. Stop rules come first: paid, customer opted out, bankruptcy flag, dispute, promise pending, maximum count reached, kill switch. Waiting reasons: outside the send window, less than the minimum gap. In draft mode a draft is saved. The rule set is checked again at the moment of sending, so a payment recorded after a draft was made cancels it.

## Reconciliation

CSV only. Score a bank line against an open item: amount 50, name similarity up to 30, number found in the text 25, date within a window 10. At 85 or more the match is confirmed automatically. From 60 it is only suggested. Splits (one deposit paying 2 to 4 invoices) are found by subset sums. Identical lines inside one file are kept and flagged, and the same file twice adds nothing. A bank line in the company currency is compared with a bill or invoice in another currency after converting at the manual rate of that day; with no rate there is no amount comparison and the pair is never matched on the raw numbers. The match reason says which rate was used.

## Forecast (13 weeks)

A pure function. Inputs: opening cash, open invoices, open bills, recurring items, customer habits, probability by aging bucket, a new sales assumption. For each invoice the expected receipt is `mul_bp(outstanding, probability)` rounded once, placed in the week the customer usually pays (their past delay, plus a catch up for late ones). A promise to pay moves it to the promised date at a higher chance. Bills are paid on their due date. Recurring items are expanded by date. New sales: the average invoiced per week over the last 13 weeks, collected 6 weeks later. Scenarios change inputs only: collect later, pay later, add a hire. The slider on the Cash cockpit calls the API with the scenario and the chart redraws from the answer.

## Other currencies (manual rates)

The company currency (`BASE_CURRENCY`) is the one every total, the aging and the forecast are shown in. A bill or invoice in another currency is converted by `fx.py` and `money.convert`: the rate is a `Decimal` typed by a person with a date (table `ll_fx_rate`, rate stored as text so no float ever touches it), the latest rate dated on or before the day looked at is used, the scale between the two currencies' minor units is applied (a yen has none, a dollar has two) and the result is rounded once, half away from zero. Amounts themselves stay integers in minor units.

Nothing converts silently. Each conversion returns the original amount, its currency, the rate and the rate date, and every endpoint that builds a total returns an `fx` block listing what was converted and what was left out. An item with no rate is left out of the totals, the aging and the forecast, is listed with the reason `no_rate`, and raises a `missing_fx_rate` exception until a rate is entered. A rate older than 45 days is marked old. The screens show a note under the title and the original amount beside the converted one; the month end PDF ends with the rates used and each converted item. Rates are never fetched from a market feed.

## Safety layers

Draft mode, the kill switch, the accounting write switch, approvals and the write guard are all checked by the base before anything leaves the app. The in app switches can only make things safer. SSRF protection checks every vendor address.

## Demo clock

The demo runs on a fixed clock (2026-12-01 plus an offset) so numbers, tests and screenshots do not change.
