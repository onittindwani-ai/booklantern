# QuickBooks Online

Checked 2026-11-23.

- VERIFIED: the OAuth 2.0 sign in, token and revoke endpoints and the accounting scope, from Intuit's discovery document and the Intuit SDK readme.
- UNVERIFIED: the bill and invoice resource paths, the field names we send and read, the current minor version (we default to 75) and the sandbox base address. The developer pages are rendered by script and the fetch tool saw no content.
- Behaviour we built and tested against our own stand in only: refresh the access token when it expires, keep the new refresh token Intuit returns, retry once after a 401, create a draft bill only when live mode, the write switch and an approval are all on.

Next step for a person: open the API reference in a browser, check the paths and fields in `apps/api/src/booklantern/adapters/quickbooks.py` and fix any difference, then run against a sandbox company.

## Contract test (2026-11-23)

Intuit publishes no machine readable spec we could fetch, and the API reference pages are script rendered (the fetch saw only the title). So `mock/contracts/quickbooks/` holds the token request (endpoint verified, form per RFC 6749) and two files of what the adapter sends and reads for a bill and an invoice query, marked UNVERIFIED. `mock/tests/test_contracts.py` checks the adapter keeps to them. That proves consistency, not that QuickBooks agrees.
