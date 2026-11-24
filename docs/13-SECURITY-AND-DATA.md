# Security and data

The full list of what was tested and what was not is in `../SECURITY.md`. In short:

- **Never moves money.** No bank credentials, no payment initiation. The bank side is a CSV file.
- **Draft mode is the default.** Nothing is posted or sent. Live mode is a setting a person changes outside the app. The app cannot switch it on.
- **Read only against accounting by default** (`ACCOUNTING_WRITE=false`).
- **Approvals.** The person who asks cannot approve their own risky action. Posting needs live mode, the write switch and an approved bill together.
- **Untrusted text.** Text inside a bill, an email or a bank line is treated as data. It is wrapped before any model prompt and cannot trigger an action.
- **Audit log.** Every change is chained to the one before. Press Check the chain on the Audit page.
- **Web.** The browser never holds a vendor key. The web app forwards to the API and adds a required header to every change, so a form on another website cannot make the browser change data.
- **Uploads.** Only PDF, PNG and JPEG, with a size limit. The same file twice is one document.
- **Where data lives.** Bills, bank lines and customer names are in your database and the uploads folder. If you turn on the live reader, bill contents go to the model vendor.

## What you must do

Keep `.env` out of Git. Use a second approver. Back up the database and the uploads. Rotate a key if you ever pasted it somewhere. Keep the server updated.
