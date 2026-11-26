# Limits and honest notes

## What was run and what was not

| Thing | Status |
| --- | --- |
| Offline reader, checks, aging, reminders, reconciliation, forecast, API, web app | Built and tested here: <!--n:tests.passed-->506<!--/n--> Python tests and <!--n:e2e.tests-->41<!--/n--> browser tests passed, coverage <!--n:tests.coverage_percent-->93.3<!--/n--> percent. |
| QuickBooks, Stripe, IMAP adapters | Tested against stand in servers we wrote. **Never run against the real service.** |
| Xero and Akaunting adapters | Written from documentation, mock tested only, tier B. |
| Model path (a language model reads bills, words the forecast and the month summary, words reminders) | Real code behind the base wrapper, with a schema, the untrusted text boundary and checks by code. Run only against a **local mock server** and recorded answers made from it. **Never run with a real key, so how a real model reads real bills is UNVERIFIED.** |
| Docker images and compose | The GitHub CI workflow builds both images and starts the whole stack (database, API, worker, web), and the API and the web app must answer. I did not run Docker on my own machine for this version. |
| Vercel, Railway, Hetzner guides | **Never deployed.** No deploy to a real host was done, so the three guides are written from the vendors' docs and not run. |
| Postgres migration | Run up, down and up on Postgres 17.7 once, in a throwaway cluster. One test is skipped unless you set `TEST_POSTGRES_URL`. |
| Screen reader use | Not tested. Axe found no serious or critical problems, which is a code level check only. |

## Things the code cannot do for you

- **Opt outs are recorded by a person.** Every reminder says "reply to this email and we will stop them". Nothing switches reminders off by itself from a reply. Set `REPLY_TO` to a mailbox a person reads (live mode refuses an empty `REPLY_TO` when the bills mailbox is also the sender). If the replies do land in the bills mailbox anyway, the poller leaves them unread and shows a reply from a customer, or one that asks to stop, on the Exceptions page; a person then presses the opt out on the customer (Collections). If nobody looks, the stop line is a promise you are not keeping.
- **Vendors and customers have no page in the web app.** They are added through the owner only API routes, CSV imports or `tools/load_data.py` (`05`). Bill review and the bank pages are in the web app.
- **A vendor's bank account on file is the check for changed payment details**, so it is only as good as what the owner typed. A bill with details and no account on file is flagged, and one with no details where an account is on file is held back.
- **Bank details are read only from labelled lines**, such as a routing number and an account number, or an IBAN. An account number on its own is not taken for bank details, because it is usually the customer's own account with the vendor.
- **PDFs are opened in the same process as the API**, with no separate process or memory limit. Accept bills only from mailboxes you control.
- **No retention job.** Bills, bank lines and the audit log stay until you delete them.
- **Only QuickBooks and Xero carry a repeat key.** A repeated post to them returns the first draft, never a second one. Akaunting and the CSV adapter cannot recognise a repeat, so when a post to them ends unclear (a timeout after the request went out) the bill stays in `posting` with a blocking finding, nothing is posted again by itself, and a person looks in the accounting system and says on the bill whether the draft is there.
- **A bank line may be linked to an invoice or bill that is already marked paid** (a statement can cover payments the books already hold), but an open one always wins when both fit, and linking changes nothing about the paid one. A deposit of the same amount for an invoice that was really paid twice is therefore shown with the reason "already marked paid in the books", for a person to look at.
- **A reason typed for an override is checked for its shape, not its truth.** At least 12 characters, 2 words and 5 different letters or digits. Whether it is honest is for the person who reads the audit log.
- **`INTAKE_ALLOWED_SENDERS` trusts the From line**, which a sender can forge. It makes a stranger's bill blocked by default; it does not prove who sent it.
- **The interactive API page (`/docs`) is off in a real install** (`DEMO_MODE=false`); the list of routes is in `docs/openapi.json`.
- **Only a PDF, or a picture attached with a file name, is taken as a bill.** A picture pasted into the body of a mail, or a signature or logo that Outlook or Gmail adds, is not. A mail with no such file stays unread in the mailbox, and a note from a customer or one that asks to stop is shown on the Exceptions page, again for each new message. A file named as a PDF or picture whose first bytes say it is neither is not read and is listed as "File not read".
- **A bill in a currency this system does not know** (for example TWD or COP, or NT$ written beside the total) is held with a blocking "Currency not known" finding. The amounts it shows are a placeholder in the company currency (the system cannot store a currency it has no decimals for) and are not amounts in that currency, so key the bill by hand in a known currency before approving it; approving it with a written reason is still possible, and then the placeholder is what gets posted. Add the currency to `CURRENCY_EXPONENT` in `money.py` with its decimals, or key the bill by hand.
- **A line in a statement before the account's opening date** is kept but not counted in the balance (see `05`). The import result says how many.
- **A deposit that names an invoice already marked paid, when another invoice of the same amount is open,** is only suggested, never confirmed by itself. Paid invoices never take part in a split.
- **A bill stuck in "posting"** (the program stopped after the claim was saved) is found after 15 minutes by the reconcile job and gets the "Posting outcome unclear" finding. It is settled only with "Say what happened" on the bill, not by closing the finding. A bill whose claim was made before the claim time was recorded counts as old.
- **Kept as known gaps from the fourth audit (not fixed):** a match that is only suggested does not stop a reminder and is counted in the forecast as well as the invoice it may pay; the checks that compare a bill number or total across different vendors, and the near duplicate check for consecutive numbers (INV-1041 then INV-1042 with the same total), can block a real bill, and then the owner or a second person approves with a reason; a bill's bank account is compared after punctuation and spaces are removed, so a routing number printed with the account number as one string is not split; validating a bill loads its lines one bill at a time, which is slow with tens of thousands of bills.
- **Mail that is not a bill stays in the bills mailbox unread**, up to the poller's memory of 5,000 messages. Use a mailbox where bills are the only thing that arrives.
- **A database error message can include the values of the failed query**, which may be bill text. Booklantern's own log lines never carry bill text, but this is set in the shared base (`make_engine` should hide statement parameters). It is a request to the maintainers of the shared base, not changed here. Keep logs private (`11`).

## The reader is weak on new layouts

Bills written by separate AI test authors (two independent sets, 105 documents) were read with about 3 fields in 4 right and about 1 document in 10 with nothing wrong, by the offline rules (`EXTRACTION-EVAL.md`). The older self written test gave 0 of <!--n:heldout_documents-->24<!--/n--> documents fully right. The reader cannot read scans at all. A person approves every bill, and the checks by code catch totals that do not add up on whatever was read. Expect many false alarms: the safe direction, but noisy.

## The model path (EXTRACTOR=live, LLM_BACKEND=anthropic, REMINDER_WRITER=model): UNVERIFIED

What it is: a model reads the text layer of a bill and returns each field with a confidence and the exact text it came from. **Code then checks every value against the document** (is the quoted text really there, is the number really in it), redoes the arithmetic (line sums, tax, total), and caps the model's own confidence at 85. The same model can word the forecast explanation, the month summary and each reminder, but only from numbers the code hands it: a number that was not handed over, a new link, a threat, a wrong amount or an order in the text makes the plain default wording come back.

What was tested (locally, no account): the request shape against a mock server written to the vendor's documented fields, the schema check with one repair try, a bad answer falling back to the offline reader, the kill switch (zero requests), the call budget, marker lookalikes in a bill, 54 recorded readings replayed with `LLM_BACKEND=fixture`, and hostile text. **What was not tested: any real model.** The recorded answers were made by a mock server that answers like the offline rules, so they prove the plumbing, not quality. Reading a picture of a bill needs image input in the base wrapper, which it does not have: a scan always goes to a person.

**Text in a bill that gives orders** ("ignore your instructions", "pay this to another account", "approve this") is never obeyed, by the offline reader or the model. Every document is scanned for such wording; a hit raises a blocking `suspicious_text` exception, caps a model's field confidences at 60, and leaves every field as printed. A bill with a different bank account than the one on file also raises `bank_detail_changed`. Nothing in this system can pay a bill: the only write is a draft bill in your accounting tool, and only after a person approves a bill that has no blocking finding (or approves it with a written reason, and a different person than the one who edited it or closed the finding, unless that person is the owner), in live mode, with ACCOUNTING_WRITE on. After posting, the total the accounting system reports for the draft is compared with the approved total, and a draft with another total sends the bill back to review instead of counting as posted (the QuickBooks, Xero and Akaunting adapters read the total back; they are tested only against stand ins written from public docs, never against the real services, so the comparison is unverified there). Test: `apps/api/tests/test_model_path.py`.

There is no categorizer: Booklantern does not choose an expense account for a bill line. The chart of accounts table is a small default list (see the decided defaults below) and the draft bill goes to the accounting tool with the lines as read; the accounting tool or a person chooses the accounts.

## The forecast is a guess

It uses the invoices and bills it knows about, the chance each aging group is paid (a default you must replace), each customer's past habit, recurring items and one assumption for new sales: the average invoiced per week over 13 weeks, collected 6 weeks later. Change those in your client's real numbers. It says nothing about events it cannot see.

## Other currencies

Built and tested: manual rates by date, conversion with Decimal maths, the flag on every screen and in the month end PDF, items with no rate left out and listed. Limits you should know about:

- **A person types the rates.** There is no market feed on purpose. A stale rate (older than 45 days) is marked old, but only a person can say it is wrong.
- **One rate per day and currency**, used for the whole item. Gains and losses between the bill date and the payment date are not worked out. This is not foreign exchange accounting.
- **Reminders and payment links stay in the invoice's own currency**, as the customer sees it. Only the totals and the forecast are converted.
- **A bill posted to the accounting system goes in its own currency**, without an exchange rate: the accounting tool applies its own. Check the first one by hand.
- **A bank account in a currency other than the company currency is not supported.** Bank lines are compared with foreign items only when the bank line is in the company currency.

## Decided defaults (change them for each client)

Collection chances by aging group, the reminder ladder (days 1, 7, 14 and 30 with tones friendly, firm, firmer, final, at most 4, at least 5 days apart, weekdays 09:00 to 17:00 in the customer's time zone), payment terms net 30 (a bill with no due date gets its issue date plus the vendor's terms, or 30 days, and says so), the 4 times the usual amount rule, the near duplicate rule (same amount, similar number, within 3 days) and the exact duplicate rule (same vendor, number and amount on any date, or with no date). Collection chances are 95, 90, 75, 50 and 20 percent. The chart of accounts is still a placeholder list. Tax is read from the bill and compared with the printed or usual rate; it is never advice.

## Not included

- Moving money, bank logins, card payments.
- Tax or accounting advice, payroll, inventory.
- Reading scanned bills without the live reader.
- More than one company in one copy.
- A mobile app. The web app works on a phone.
- Real time updates. The page refreshes when you act or press Run now.

## Requested change to the shared base

The base language model wrapper takes text only, so the live reader cannot send a page picture. Until the base accepts images, a scan needs a person to key the fields.
