# Security

Booklantern handles bills, bank lines and customer names. It never moves money and has no bank login. This page says what was checked, what was found and fixed, and what was not done. Nothing here is a guarantee. It was checked by the person who built it, not by an independent tester.

## Two risks to know before you deploy

- **Demo mode.** `DEMO_MODE=true` switches on a public demo password, example approver and viewer accounts, the demo buttons (one of them erases the database), a sample demo date and the loading of sample data. They all turn off the moment `OWNER_PASSWORD_HASH` is set, and the app refuses demo mode on Postgres, but a real install should always run with `DEMO_MODE=false`.
- **Secrets.** `SESSION_SECRET` signs every login. With `DEMO_MODE=false` the app refuses to start on a short or example value. Anyone who learns it can sign in as the owner, so keep `.env` out of git and change it if it may have leaked. The vendor's bank account on file is the number every payment detail is compared with, so only the owner can change it.

## Design rules

- Draft mode is the default. Nothing is posted or sent until a person sets live mode. For accounting, three things must all be on: live mode, `ACCOUNTING_WRITE=true` and an approved bill. The app can switch things off (Pause all) but can never switch live mode on.
- Every connection to a mail server checks its certificate, and plain text is refused for any host but this computer.
- Text from bills, emails and bank lines is data. It is wrapped before any model prompt and cannot trigger an action.
- The person who asked for a risky action cannot decide it.
- Every change goes into an audit log chained to the one before.
- The web app keeps the session in an httpOnly cookie, sets SameSite to Lax, and sends a required header on every change.
- Vendor base addresses are checked so they cannot point at a private network address (SSRF guard).

## What was checked (2026-11-23, and again for 1.0.1 on 2026-11-25)

- Secret scan of tracked files (`python tools/scan_secrets.py`): nothing found.
- Dependency audit of Python (`pip-audit` against the OSV service) and Node (`pnpm audit`): no known vulnerabilities at the time.
- Tests, in `apps/api/tests/test_security.py`, `test_api.py` and `test_adapters.py`: every route needs a session, the login is rate limited, an owner only kill switch, the SSRF guard, an instruction hidden in a bill cannot approve or post it, an oversized upload is refused, a damaged PDF does not crash the server, a file name with a path cannot escape the upload folder, a formula in a bank line stays plain text, the asker cannot approve their own request, an approver cannot turn the kill switch off.
- Browser tests: a change without the required header is refused, and accounting write stays off.

## Found and fixed during the build

1. A damaged PDF made the upload fail with a server error. It now becomes a bill with a note to key the fields by hand.
2. The shared base does not stop a person deciding their own approval request. Booklantern now refuses it in its own route.

Version 1.0.1 fixed what a stricter second self review found:

3. A restart of a demo with a real owner password could erase or reload the database, and the demo clock replaced the real one. Seeding, the demo routes and the demo clock now exist only when demo shortcuts are on (demo mode and no owner password), and a database that holds data is never reloaded.
4. One damaged or hostile attachment lost every bill fetched from the mailbox in the same poll. Each document is now checked and saved on its own, a mail is marked read only after its bills are saved, and a failure is logged without the bill's text.
5. The duplicate bill and changed bank account checks did nothing on an install with no vendor list, and bank details printed as a routing and account pair were never read. They now work from the bill itself, and a vendor with an account on file whose bill shows none is held back.
6. Text on a bill that looked like markup could break the month end PDF. It is now escaped.
7. Amounts of 20 digits, overlong text, a negative total and an unknown currency code could break a save. They are now limited, and a bill with an implausible or negative amount cannot be approved.
8. Mail connections did not check the server certificate on every path. They now use the standard verifying context.
9. Uploads and mail messages are read with a size limit as they arrive, and the page picture of a huge page is drawn small.
10. Two clicks at the same moment could approve, reject or post one bill twice, or link one bank line twice. Each move is now a single conditional change, and the rows are locked while the sums are checked.
11. The sign in route used the unpadded email for the account and the padded one for the limit, and did not limit by network address. Both now use one cleaned address and a second bucket by address.

A further independent audit of the hardened code found these, fixed in the same release:

12. A person could clear the finding their own edit had raised, then approve alone, and a closed finding never opened again. Whoever changed a bill or closed a finding on it can no longer approve it, an approver cannot close a blocking finding on their own edit, and a blocking finding opens again when the check fires after another edit. The owner may do both on their own work with a written reason, logged as `self_review`.
13. A 1.4 KB PDF could use gigabytes of memory in the live reader's text layout, and a file that killed the reader was tried again every cycle. The layout is bounded, and a document whose reading was started three times and never finished goes to a person.
14. The drafts sent to QuickBooks, Xero and Akaunting lacked the tax or the lines, and the total they returned was never compared. It is now, and a draft with another total sends the bill back to review.
15. A change made with the cookie alone, with no body, did not need the custom header at the API. It does now. The sign in limit on an account across all addresses let a stranger keep the owner out, so it was removed (each address keeps its own limit).

A third independent audit found these, fixed in the same release:

16. An approver could edit a blocking finding away (a wrong company name, a bank account typed in, a number changed by one character), because the finding was deleted and the bill then looked clean, and approve alone. A bill now remembers that it ever carried a blocking finding. A reason for an override must be a real sentence (12 characters, 2 words, 5 different letters or digits).
17. A vendor name that only looked like a real vendor's skipped both the duplicate check and the bank account check. A bill with a number is now compared with every other bill when either vendor is not on the list, and an unknown vendor that asks to be paid into an account blocks. `INTAKE_ALLOWED_SENDERS` can limit who may email bills in.
18. A bank line written with the real minus sign or an en dash was read as money in, and `DR` as positive. One strict reader now keeps the sign, and anything it does not understand stops the import.
19. A customer's "stop" reply was marked read by the mail poller within minutes. Mail with no bill in it now stays unread, and one from a customer or asking to stop is shown to a person.
20. A start with no `DEMO_MODE` line passed the start check with real connections and live writes while the public demo password was active. It is now refused unless `ALLOW_DEMO_SERVER=true`.
21. A later deposit of the same amount from the same customer could pay an invoice that was already paid, while the invoice still open kept getting reminders. An open invoice or bill now always wins, and a part paid invoice offers only what is still owed.
22. A mail connection that failed after the message was handed over put the reminder back to be sent again, so a customer could get it twice. It now stays "sending" for a person to check. Posting to an accounting system that cannot recognise a repeated request stays "unknown" until a person looks.

## Not done, and known limits

- No independent penetration test. No test against real vendor accounts. No deploy to a real host: the CI workflow builds the Docker images and starts the stack, nothing more.
- PDFs are opened by a native library (pdfium) in the same process as the API, with no separate process or memory limit. A bug in it could be dangerous with a hostile file. Run the API in a container as a plain user, keep dependencies updated, and only accept bills from mailboxes you control.
- The SSRF guard checks the address when the adapter is built. A host that changes its address afterwards (DNS rebinding) is not covered.
- Rate limits are kept in memory in one process. Two API copies do not share them.
- The web app sends a Content-Security-Policy with `script-src 'self' 'unsafe-inline'`: the pages Next.js builds carry small inline scripts, and a nonce would make every page render on each request. Everything else is limited to this site, and framing and plug ins are refused.
- `INTAKE_ALLOWED_SENDERS` checks the From line of an email, which a sender can forge. Use it to narrow the door, and keep the intake address private.
- `/ready` (open, like `/health`) answers a database failure with the class name of the error. It holds no data, but a fixed message would be better. That is in the shared base and is fixed there, not in this repository.
- Sign in is one password per person. There is no second factor. Because no limit is kept on an account across all addresses (it would let a stranger lock the owner out), guesses spread over very many addresses are slowed only per address: use a long random owner password.
- The API container trusts `X-Forwarded-For` only from the addresses in `FORWARDED_ALLOW_IPS` (default `127.0.0.1`; the compose file widens it to the private network that holds the web container). Keep the API behind your proxy, as the compose file does by binding to 127.0.0.1.
- The hosting guides and every real vendor connection were never run (`docs/14-LIMITS-AND-HONEST-NOTES.md`). The Docker images are built and the stack is started by the CI workflow on GitHub, not on a real host.
- Bills, bank lines and the audit log are kept until you delete them. There is no automatic retention job.
- No screen reader test. Axe reports no serious or critical problems.

## If you find a problem

Do not post it in a public issue. Open the repository's **Security** tab and choose **Report a vulnerability**: that report is private. We aim to acknowledge it within 5 working days. Include steps to reproduce. Never include real keys, passwords or customer data. Rotate any key you think was exposed.
