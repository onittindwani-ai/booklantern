# Mail (IMAP and SMTP)

Checked 2026-11-23.

- VERIFIED: a Google app password needs 2-Step Verification, is created at myaccount.google.com/apppasswords, and may be unavailable for work or school accounts, security key only accounts or Advanced Protection (https://support.google.com/accounts/answer/185833).
- UNVERIFIED: the Gmail host names and ports, and whether Google keeps app passwords available.
- Built and tested against a mock server we wrote: read unseen messages, keep only PDF, PNG and JPEG attachments, mark messages seen, send a reminder over SMTP.
