# Using it for a client

One copy of Booklantern serves one client. Do not mix two clients in one database.

## What you are selling

Set up, a trial period in draft mode, and a monthly review of the exceptions and the forecast. You are not selling tax or accounting advice, and you are not selling a promise that the reader is right. Say that plainly.

## What to charge for

This guide gives no price figures. It gives the shape of the offer, so you can price it yourself after looking at your market and your costs.

- **Setup, once.** Business basics check (`02`), a fresh copy for the client, mailbox and accounting connections, importing three months of the bank statement, loading real vendors and customers, agreeing the reminder ladder and the exchange rates in writing, and a trial period in draft mode. Charge for the hours and the care, not for the software, which is free.
- **Running it, monthly.** A short review of the exceptions, the aging, the forecast and the exchange rates (a person types them; check they are current), and answering when the reader gets a bill wrong. State plainly how many hours a month that includes.
- **Costs that pass through, at cost.** Hosting, the mailbox for bills, the accounting tool's own fees, the payment link fees and any model usage. Show these as the client's own accounts, not as your markup.
- **Never charge for** a promised amount of money collected or saved, and never present anything here as tax, accounting or legal advice. The reader suggests, a person confirms, the forecast is a guess, and the demo numbers are fictional.

## Onboarding checklist

1. Run `02-BUSINESS-BASICS-CHECK.md` with the client.
2. Make a fresh copy, `DEMO_MODE=false`, the client's company name, address, reply address, currency and time zone (`04`).
3. Connect the mailbox for bills and the accounting system in its sandbox (`03`, `04`).
4. Import three months of the bank statement as CSV.
5. Load real vendors (with the bank account on file), customers, open invoices, the bank account and the chart of accounts with `tools/load_data.py` or the owner only API routes (`05`, "A real install"). The CSV accounting adapter does not load these.
6. Agree the reminder ladder, the collection chances and the payment terms with the client in writing. The defaults are net 30, reminders at 1, 7, 14 and 30 days (friendly, firm, firmer, final) and 95, 90, 75, 50 and 20 percent chances by aging group.
7. If any bill or invoice is in another currency, type the exchange rate with its date on the Reports page. Without a rate that item is left out and flagged, never guessed. Agree who updates the rates and how often.
8. Trial in draft mode, then follow `09-GO-LIVE-CHECKLIST.md`.

## Handover

- Give the client their own owner and approver sign ins, and a read only sign in (`VIEWER_EMAIL`) for their accountant. Remove yours.
- Hand over the backup steps in `11` and the contact for the person who updates it.
- Hand over the secrets inside the client's own hosting account, never by chat or email.
- Hand over the list of exchange rates with their dates and where each one was looked up.
- Agree who answers when the reader gets a bill wrong. It will.

## What to put in the client contract

Plain wording, checked by your own lawyer: what is included in setup and in the monthly work; that costs of third party accounts are the client's; that the client owns the data and the accounts; that the client's accountant owns the books and this tool gives no tax or accounting advice; that exchange rates are typed by a person and are the client's responsibility to keep current; that the client confirms they may contact each customer who gets a reminder; that no results are promised; who answers if a reminder or a bill goes wrong, and how fast; how either side ends the work and what happens to the data afterwards. This is not legal advice.

## Keep it honest

The reader is a suggestion a person confirms. Every forecast is a guess from the data it has. The month end pack is a working document for the accountant.
