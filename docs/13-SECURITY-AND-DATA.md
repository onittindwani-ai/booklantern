# Security and data

The full list of what was tested and what was not is in `../SECURITY.md`. In short:

- **Never moves money.** No bank credentials, no payment initiation. The bank side is a CSV file.
- **Draft mode is the default.** Nothing is posted or sent. Live mode is a setting a person changes outside the app. The app cannot switch it on.
- **Read only against accounting by default** (`ACCOUNTING_WRITE=false`).
- **Who decides what (this is exactly what the code enforces).**
  - A drafted reminder is written by the system and sent only after a person approves it. The same goes for every item on the Approvals page: the person who asked cannot decide it.
  - A bill that has, or ever had, a blocking finding (a changed bank account, a duplicate or a number changed by a character on the same amount, a total that does not add up, a vendor that is not on the list asking for a bank account, a sender that is not on the allow list, text that gives orders, and so on) needs two different people. A bill remembers that it ever had one (`had_block`): editing the check away, for example typing the account on file into the bill, closes the finding but not the rule. The person who changed any field of that bill cannot close a blocking finding on it, and the person who changed the bill or closed one of its findings cannot approve it. Both are refused with a plain message.
  - The owner is the one exception, and only on their own work: the owner may close a finding on a bill they edited, and may approve a bill they edited or closed a finding on, with a written reason. What the code enforces about the reason is its shape, not its truth: at least 12 characters, at least 2 words, at least 5 different letters or digits, so one character or `aaaa` is refused and a person still has to say something. Each such step is marked `self_review` in the audit log. The approval also carries a fingerprint of the bill as the page loaded it (`etag`), and a bill that changed since, or whose vendor record changed, is not approved until the page is reloaded.
  - A closed blocking finding opens again when the same check fires after another edit of the bill, because a reason given for the bill as it was is not a reason for the bill as it is now. Who closed it earlier stays in the audit log.
  - A bill with no blocking finding can be edited and approved by one person. Nothing forces a second pair of eyes there, so keep an approver who is not the owner and read the bills the system flagged only with a warning.
  - Posting needs live mode, the write switch and an approved bill together, and the draft the accounting system returns is checked: if its total is not the approved total, the bill goes back to review and is not recorded as posted.
- **Untrusted text.** Text inside a bill, an email or a bank line is treated as data. It is wrapped before any model prompt and cannot trigger an action.
- **Audit log.** Every change is chained to the one before. Press Check the chain on the Audit page.
- **Web.** The browser never holds a vendor key. The web app forwards to the API and adds a required header to every change, so a form on another website cannot make the browser change data. The API asks for the same header (`x-booklantern: 1`) on every change whose session comes from the cookie, so the API port is not open to that either.
- **Uploads and mail.** Only PDF, PNG and JPEG, with a size limit counted as the bytes arrive. The same file twice is one document. One damaged or hostile attachment never loses the other bills in a mailbox poll, and a mail is marked read only after its bills are saved.
- **Mail connections** check the server's certificate, and plain text is refused for any host but this computer.
- **Demo shortcuts** (the public demo password, the example logins, the demo buttons, the sample date, sample data) exist only with `DEMO_MODE=true` and no `OWNER_PASSWORD_HASH`.
- **The in app switches.** Pause all and force draft, set in the app, hold for posting, sending and payment links even when the environment says live.
- **Where data lives.** Bills, bank lines and customer names are in your database and the uploads folder. If you turn on the live reader, bill contents go to the model vendor.

- **Sign in limits.** Each address gets a few tries at an account, and a wider number of tries in total. There is deliberately no limit on an account across all addresses, because that would let a stranger who knows the owner's email keep the owner out. The price is that guesses spread over very many addresses are not slowed down by account, so the owner password must be long and random (`tools/hash_password.py` makes the hash).

## What you must do

Keep `.env` out of Git. Use a second approver. Back up the database and the uploads. Rotate a key if you ever pasted it somewhere. Keep the server updated.
