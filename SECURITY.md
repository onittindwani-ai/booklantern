# Security

Booklantern handles bills, bank lines and customer names. It never moves money and has no bank login. This page says what was checked, what was found and fixed, and what was not done. Nothing here is a guarantee. It was checked by the person who built it, not by an independent tester.

## Design rules

- Draft mode is the default. Nothing is posted or sent until a person sets live mode. For accounting, three things must all be on: live mode, `ACCOUNTING_WRITE=true` and an approved bill. The app can switch things off (Pause all) but can never switch live mode on.
- Text from bills, emails and bank lines is data. It is wrapped before any model prompt and cannot trigger an action.
- The person who asked for a risky action cannot decide it.
- Every change goes into an audit log chained to the one before.
- The web app keeps the session in an httpOnly cookie, sets SameSite to Lax, and sends a required header on every change.
- Vendor base addresses are checked so they cannot point at a private network address (SSRF guard).

## What was checked (2026-11-23)

- Secret scan of tracked files (`python tools/scan_secrets.py`): nothing found.
- Dependency audit of Python (`pip-audit` against the OSV service) and Node (`pnpm audit`): no known vulnerabilities at the time.
- Tests, in `apps/api/tests/test_security.py`, `test_api.py` and `test_adapters.py`: every route needs a session, the login is rate limited, an owner only kill switch, the SSRF guard, an instruction hidden in a bill cannot approve or post it, an oversized upload is refused, a damaged PDF does not crash the server, a file name with a path cannot escape the upload folder, a formula in a bank line stays plain text, the asker cannot approve their own request, an approver cannot turn the kill switch off.
- Browser tests: a change without the required header is refused, and accounting write stays off.

## Found and fixed during the build

1. A damaged PDF made the upload fail with a server error. It now becomes a bill with a note to key the fields by hand.
2. The shared base does not stop a person deciding their own approval request. Booklantern now refuses it in its own route.

## Not done, and known limits

- No independent penetration test.
- PDFs are opened by a native library (pdfium) in the same process as the API. A bug in it could be dangerous with a hostile file. Run the API in a container as a plain user, keep dependencies updated, and only accept bills from mailboxes you control.
- The SSRF guard checks the address when the adapter is built. A host that changes its address afterwards (DNS rebinding) is not covered.
- Rate limits are kept in memory in one process. Two API copies do not share them.
- Sign in is one password per person. There is no second factor.
- The API container trusts `X-Forwarded-For` from any address (`--forwarded-allow-ips '*'`). Keep it behind your proxy, as the compose file does by binding to 127.0.0.1.
- The Docker images, hosting guides and every real vendor connection were never run (`docs/14-LIMITS-AND-HONEST-NOTES.md`).
- No screen reader test. Axe reports no serious or critical problems.

## If you find a problem

Do not post it in public. Use the private security reporting of the host where you got this code, or contact the maintainer directly. Rotate any key you think was exposed.
