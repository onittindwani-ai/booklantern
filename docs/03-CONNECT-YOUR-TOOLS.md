# Connect your tools

Each job has an offline adapter called `seed` that is the default. You switch one job at a time by changing one variable. Every real connection is written from vendor documentation and **was never run against the real service** (UNVERIFIED), except where a section says otherwise. Test each one in a sandbox first. `tools/doctor.py --live` tests a connection without sending anything.

Variable names and the numbered steps to get each value are in `04-ENVIRONMENT-VARIABLES.md`.

## Accounting (ACCOUNTING_ADAPTER)

- **quickbooks** (QuickBooks Online). Tested against a stand in server. The sign in endpoints and scope were checked against Intuit's own pages on 2026-11-23. The bill and invoice paths, field names and the current minor version are UNVERIFIED because those pages could not be read.
- **xero**. Written from documentation, mock tested only, tier B.
- **akaunting**. Written from documentation, mock tested only, tier B.
- **csv**. Reads open invoices from `invoices.csv` (columns Number, Customer, Total, Balance, Due) in the folder `CSV_FOLDER` and writes approved bills to `draft-bills.csv` there, for a person to import by hand. It reads no vendors. Tested offline.

Read only by default. Posting a draft bill needs three things together: `MODE=live`, `ACCOUNTING_WRITE=true` and a person approving that bill.

## Payment links (PAYMENTS_ADAPTER)

- **stripe**. Creates a payment link for an invoice and nothing else. It never captures a payment. The create endpoint was checked against Stripe's API reference on 2026-11-23. Tested against a stand in server. In draft mode it saves a placeholder and contacts nobody.

## Where bills arrive (INBOX_ADAPTER)

- **imap**. Reads unread messages from one mailbox, keeps only PDF, PNG and JPEG attachments and marks the message seen. Works with Gmail (app password) and any host that speaks IMAP. Tested against a fake IMAP server.

## Reminder email (EMAIL_ADAPTER)

- **smtp**. Sends an approved reminder. In draft mode it saves the reminder instead.

## The reader (EXTRACTOR and LLM_BACKEND)

- **offline** (default). Rules that read the text layer of a PDF. It cannot read scans.
- **live**. A language model reads the text layer through the base wrapper, and code checks every value it returns and redoes the sums (`model_tasks.py`). Run only against a local fake server, never with a real key (UNVERIFIED), and it cannot yet send page images (see `14-LIMITS-AND-HONEST-NOTES.md`).

## How to add another tool

Ask Claude Code to write an adapter. Use `prompts/connect-tools.md`. Adapters live in `apps/api/src/booklantern/adapters/` and register in `registry.py`. A new adapter needs a seed style test against a stand in server before it counts as tested.
