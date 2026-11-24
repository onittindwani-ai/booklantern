# Stripe

Checked 2026-11-23.

- VERIFIED: creating a payment link is `POST /v1/payment_links` (https://docs.stripe.com/api/payment-link/create).
- VERIFIED: keys are made on the API keys page of the Dashboard, sandbox keys start `sk_test_` or `rk_test_`, restricted keys are recommended, and a live key you created yourself cannot be shown again (https://docs.stripe.com/keys).
- UNVERIFIED: the exact restricted permission needed to create payment links, and how a link maps to an invoice number (we put the invoice number in the link's metadata).
- Built: an idempotency key per invoice so a retry cannot make two links. Draft mode saves a placeholder and calls nothing. We never capture a payment and never receive a webhook.
- UNVERIFIED: the price_data and product_data field names we send for the link line item were not on the page read.
