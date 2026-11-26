# Start here

Booklantern is a finance back office for one small business, set up and run by an implementer. It reads the bills vendors send, checks them with code, chases customers who pay late, matches the bank statement and shows the next 13 weeks of cash. A person approves everything that matters.

All people, companies, bank lines and numbers in the demo are sample data and labelled as sample data.

## Who it is for

- A small business owner who is tired of typing bills in by hand and wants to see cash coming.
- An implementer who sets this up for a client. One copy of Booklantern serves one client. See `10-USING-IT-FOR-A-CLIENT.md`.

## What it does

1. **Reads bills.** A bill arrives by email or upload. The reader pulls out the vendor, number, dates, amounts and lines. Every field shows how sure the reader is and where on the page it came from.
2. **Checks them with code.** Totals, tax, line sums, duplicates, a bill far above the vendor's usual, changed bank details, a missing purchase order, a date in the future, the wrong currency, a bill addressed to another company. A bill with a serious finding cannot be approved without a written reason.
3. **Waits for a person.** The review screen shows the page on the left and the fields on the right. Approving a bill makes a draft entry for your accounting system. In draft mode nothing is posted anywhere.
4. **Chases late invoices.** A reminder ladder (friendly, firm, firmer, final) with stop rules. A payment, a dispute, a promise to pay, an opt out or a bankruptcy flag stops it. Reminders are saved as drafts until you turn live mode on.
5. **Matches the bank.** You import a CSV statement. Lines are matched to invoices and bills, split payments are found, and odd lines go to a list for a person.
6. **Forecasts cash.** 13 weeks, worked out by code. A slider shows what happens if customers pay later, you pay vendors later or you hire someone.
7. **Month end pack.** A PDF built by code.

## What it will not do

- It never moves money. It has no bank login and cannot start a payment.
- It does not give tax or accounting advice. It reads the rate printed on a bill and compares it with what is on file, nothing more.
- It posts nothing to your books unless live mode is on, the accounting write switch is on and a person approved the bill.

## Read this before you promise anything

The built in reader is an offline stand in. It is **not a language model**. On two independent sets of bills written by separate AI test authors it got about 3 fields in 4 right and about 1 document in 10 with nothing wrong (see `EXTRACTION-EVAL.md`). The model reader (a language model reads, code checks) is real code tested against a local mock server only, never with a real key. Treat every extraction as a suggestion a person confirms.

## Next steps

1. Try it in five minutes: `01-QUICK-DEMO.md`.
2. Check the business basics before you take a client: `02-BUSINESS-BASICS-CHECK.md`.
3. Connect real tools: `03-CONNECT-YOUR-TOOLS.md` and `04-ENVIRONMENT-VARIABLES.md`.

The numbers in these docs come from `data/counts.json`: <!--n:pages-->11<!--/n--> pages, <!--n:api_paths-->62<!--/n--> API paths, <!--n:tables-->20<!--/n--> database tables.
