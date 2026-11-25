# Go live checklist

Do these in order, one client at a time. Stay in draft mode until every box is ticked. The word "draft" means Booklantern saves what it would do and does nothing outside the app.

## Before you start

- [ ] The business basics check is done (`02`).
- [ ] The client has a person who will open the review screen every working day.
- [ ] The client's accountant knows what this tool does and does not do.

## Settings

- [ ] `DEMO_MODE=false`, a real `SESSION_SECRET`, an owner password hash, and a second approver.
- [ ] `COMPANY_NAME`, `COMPANY_ADDRESS`, `EMAIL_FROM`, `REPLY_TO`, `BASE_CURRENCY`, `DEFAULT_TIMEZONE`, payment terms, reminder window and ladder are the client's real answers, not the defaults. The app refuses `MODE=live` while the company name is the placeholder.
- [ ] The vendors (with their bank accounts on file), customers, open invoices, bank account and chart of accounts are loaded (`05`, "A real install"), and a person checked a few bank accounts against the vendor's own paperwork.
- [ ] `REPLY_TO` is a mailbox a person reads, and it is not the mailbox bills arrive in (the app refuses `MODE=live` otherwise). Someone reads it every working day and records an opt out on the customer when one asks to stop. A message with no bill in it that reaches the bills mailbox stays unread there and, from a customer or asking to stop, is shown on the Exceptions page.
- [ ] `INTAKE_ALLOWED_SENDERS` lists the addresses or domains your vendors send bills from, if you can (empty means anyone who knows the address). The bills mailbox is used for bills only.
- [ ] `python tools/doctor.py --live` shows no FAIL.
- [ ] `make check-env` shows no problem.

## Trial in draft mode (at least two weeks)

- [ ] Real bills arrive in the review queue. A person reads each page next to the fields.
- [ ] You compared the reader's fields with the page for at least 30 real bills and wrote down the mistakes. The offline reader will be wrong often on real layouts (`EXTRACTION-EVAL.md`).
- [ ] Reminders are saved as drafts. The client reads them and agrees the tone and the wording.
- [ ] The forecast was compared with what really happened for a few weeks.
- [ ] You tried **Pause all** and saw it stop everything.

## Turning on a real connection

- [ ] Test the accounting connection in the vendor's sandbox first.
- [ ] Only then set `MODE=live`. Leave `ACCOUNTING_WRITE=false` for another week. Turn it on last.
- [ ] Check the first posted draft bill inside the accounting system by hand.
- [ ] Reminders: send the first ones to yourself or to a friendly customer first.

## Never

- Never give Booklantern a bank login. It does not need one and does not have one.
- Never turn on live mode on a Friday afternoon.
