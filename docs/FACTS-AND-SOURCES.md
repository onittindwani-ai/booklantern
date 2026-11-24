# Facts and sources

Every outside fact this project relies on. VERIFIED means the page was read on the date shown and says what we wrote. UNVERIFIED means we did not read it, could not read it, or it is our own general knowledge. Dates are the day the page was checked. Details per vendor are in `facts/`.

| Fact | Source | Checked | Status |
| --- | --- | --- | --- |
| QuickBooks sign in and token endpoints, and the accounting scope | Intuit developer discovery document and SDK readme, see `facts/quickbooks.md` | 2026-11-23 | VERIFIED |
| QuickBooks bill and invoice paths, field names, current minor version | https://developer.intuit.com (pages are script rendered, could not be read) | 2026-11-23 | UNVERIFIED |
| Stripe payment link create endpoint and fields | https://docs.stripe.com/api/payment-link/create | 2026-11-23 | VERIFIED |
| Stripe API key page, restricted keys, sandbox key prefixes, a live key cannot be shown again | https://docs.stripe.com/keys | 2026-11-23 | VERIFIED |
| Which Stripe restricted permission lets a key create payment links | https://docs.stripe.com/keys/restricted-api-keys | not read | UNVERIFIED |
| Google app passwords need 2-Step Verification, and may be unavailable on work or school accounts | https://support.google.com/accounts/answer/185833 | 2026-11-23 | VERIFIED |
| Gmail IMAP and SMTP host names | general knowledge | not read | UNVERIFIED |
| Vercel Root Directory for a monorepo | https://vercel.com/docs/monorepos | 2026-11-23 | VERIFIED |
| Vercel setting to include files outside the Root Directory | https://vercel.com/docs | not found on the page read | UNVERIFIED |
| Xero API endpoints and OAuth | https://developer.xero.com/documentation/ (script rendered) | 2026-11-23 | UNVERIFIED |
| Akaunting API | https://akaunting.com/ | not read | UNVERIFIED |
| Railway service, variable and volume steps | https://docs.railway.com | not read | UNVERIFIED |
| Hetzner server, firewall and cloud config steps | https://docs.hetzner.com | not read | UNVERIFIED |
| Anthropic model and key steps | https://docs.anthropic.com | not read | UNVERIFIED |
| Model path request and response shape (Messages endpoint, structured output) | read for the shared base on 2026-11-23, see the hub's FACTS-AND-SOURCES. Run only against a local fake server, never with a real key | 2026-11-23 | UNVERIFIED live |
| Prices of every paid tool | each vendor's price page | not read | UNVERIFIED, no price is quoted |

## Libraries used

Installed 2026-11-23: reportlab 5.1.0 (builds the month end PDF and the sample bills), pypdfium2 5.15.2 (reads text rectangles and draws page pictures), Pillow 13.0.0 (builds the sample scans). We checked how each works by running it here. We did **not** read their documentation through a documentation tool, so any API detail we rely on is whatever the tests prove. An earlier version also installed pypdf 7.1.1 and then dropped it because pdfium covers the same job.

## Not a fact from outside

All people, companies, bank lines, amounts and the exchange rate in the demo are invented by us.
