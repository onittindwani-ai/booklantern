# Changelog

## Unreleased

- Round 5 walk through every screen as a first time owner: a bill with no vendor, date or total cannot be approved; a vendor typed on the review page is saved and matched to the vendor list; amounts and dates are checked in the page before saving; a scanned bill shows its picture; closing a blocking finding needs a written reason; a promise to pay needs a real date that is not in the past and a newer promise replaces the old one; a bank file must have Date, Description and Amount, one currency, no zero lines, and the balance counts only lines in the account currency; money that came in links only to an invoice and money that went out only to a bill; a row that is gone answers 404; reset no longer drops the tables; viewers see write controls disabled; Pause all and Sign out stay on a phone; sign in returns to the page asked for; the audit log reads in plain words and opens a detail sheet; text copied from another product removed from the CSV picker.
- Renamed from Ledgerlight to Booklantern after a public name check.
- Bill reader version 2 (every page, nine languages, number and date styles, credit notes), tested on two independent sets of bills.
- Model path behind the base wrapper (bill reading, forecast and month wording, reminder wording) with checks by code, a hostile text guard and recorded fixtures; live use unverified.
- Contract tests for the QuickBooks, CSV and mail adapters; more currencies; printed tax rate compared with the vendor's usual rates.

## 1.0.0

First release. Bill intake with an offline reader, checks by code, review screen, collections ladder with stop rules, CSV bank reconciliation, 13 week cash forecast, month end PDF, eleven pages, adapters for QuickBooks (tested against a stand in), Xero and Akaunting (written from documentation), CSV, Stripe payment links and IMAP. See `docs/14-LIMITS-AND-HONEST-NOTES.md` for what was and was not run.
