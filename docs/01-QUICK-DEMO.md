# Five minute demo

No accounts and no keys. Everything runs on made up data for a fictional company, Birchfield Supply Co.

## With Docker

`docker compose up` starts the API, the worker, a database and the web app, then open http://localhost:3000. The compose file was written but **not run** here because no Docker daemon was available (UNVERIFIED). If it fails, use the steps below.

## Without Docker

1. Python 3.12 and Node 22 or newer, plus pnpm.
2. `python3.12 -m venv .venv` then `.venv/bin/pip install -c constraints.txt -e packages/core-py -e "apps/api[dev]"`.
3. `pnpm install` then `pnpm build`.
4. In one terminal: `DEMO_MODE=true MODE=live INSECURE_COOKIES=1 .venv/bin/python -m uvicorn booklantern.api.app:app_from_env --factory --port 8000`
5. In another: `API_BASE_URL=http://127.0.0.1:8000 INSECURE_COOKIES=1 pnpm --filter web start`
6. Open http://localhost:3000 and sign in as `owner@example.test` with the demo password shown on the sign in page.

The first start fills the database with the made up company by itself.

## The tour

1. **Cash cockpit.** Drag "Customers pay later by" and watch the chart redraw. A dashed line shows the plan without your changes.
2. **Invoice review.** Open the bill from Eastgate Cleaning. The page is on the left. Click a field and its box lights up. The total does not add up, so Approve needs a written reason.
3. **Bills and payables.** Press Upload a bill and choose any PDF from `data/documents`.
4. **Aging.** Click a coloured piece of a bar to see the invoices behind it.
5. **Collections.** Press +1 day at the top, then Run now, and watch reminders appear as drafts on the Drafts tab. Dispute an invoice and see its ladder stop.
6. **Reconciliation.** Select a bank line. Drag it onto an invoice, or press the Link button.
7. **Reports.** Download the month end PDF.

The demo clock is fixed at 2026-12-01 so numbers never change from run to run. To start over, open the search with Cmd+K (Ctrl+K on Windows), type "reset" and choose "Reset the demo data".
