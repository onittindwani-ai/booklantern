# Run it on your own computer

`01-QUICK-DEMO.md` is the fast version. This is the full one, including real settings and Postgres.

Windows: use WSL 2 with Ubuntu and work inside it. PowerShell and cmd are not supported. On Ubuntu or Debian (and WSL) install the venv package first, or `python3 -m venv` fails with "ensurepip is not available": `sudo apt install python3-venv python3-pip` (for a specific version, `python3.12-venv`). `corepack enable` may need `sudo` with a system Node.

## Install

1. Python 3.12 or newer (or uv, which fetches it), Node 22 or newer, pnpm (`corepack enable` or `npm i -g pnpm`). `make install` picks uv or python3.12 for you.
2. `python3.12 -m venv .venv`, or with uv (no Python 3.12 needed first): `uv venv --python 3.12 .venv`
3. `.venv/bin/pip install -c constraints.txt -e packages/core-py -e "apps/api[dev]"`, or with uv: `uv pip install --python .venv/bin/python -c constraints.txt -e packages/core-py -e "apps/api[dev]"` (add `-e "apps/api[postgres]"` if you use Postgres).
4. `pnpm install` then `pnpm build`.

## Settings

`cp .env.example .env`, then follow `04-ENVIRONMENT-VARIABLES.md`. The example has `DEMO_MODE=false`, so the API will not start until you set a real `SESSION_SECRET` (and, for a real install, `OWNER_PASSWORD_HASH`); for the offline demo set `DEMO_MODE=true` instead and leave `OWNER_PASSWORD_HASH` empty. Run `make check-env` (it needs only Python) and then `python tools/doctor.py`. The first reads your file, the second tests the services. Neither prints a value.

## Database

- **SQLite** (default): tables are created on start. In demo mode (and only with no `OWNER_PASSWORD_HASH`) the made up company is loaded when the database is empty. A database that already holds data is never reloaded or erased on start.
- **Postgres**: set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname`, then `cd apps/api && ../../.venv/bin/alembic upgrade head`. Alembic reads `DATABASE_URL` from the environment or from `.env` (or the file named by `ENV_FILE`, relative to the folder you run it in: `ENV_FILE=../../.env`) and stops with a message when it finds none. Do this on every update.

## Two programs, then the web app

Run each in its own terminal, from the project folder.

1. **API:** `.venv/bin/python -m uvicorn booklantern.api.app:app_from_env --factory --port 8000 --proxy-headers` (it refuses to start on unsafe settings and says which)
2. **Worker** (reads the mailbox, runs the reminder and forecast jobs): `.venv/bin/python -m booklantern.worker`
3. **Web:** `pnpm --filter web start` after `pnpm build`, or `pnpm dev` while you change code.

Open http://localhost:3000.

## A real install

With `DEMO_MODE=false` the app starts empty: no sample company, no sample vendors. Set `COMPANY_NAME`, `COMPANY_ADDRESS`, `EMAIL_FROM`, `REPLY_TO`, `BASE_CURRENCY` and `DEFAULT_TIMEZONE` (`04`), then add what the app needs, either through the API (owner login, see `/docs` on the API) or with the command line loader, which reads the same settings file:

```
python tools/load_data.py bank-account "Main account" --currency USD --opening 1250000 --opening-date 2026-01-01
python tools/load_data.py vendors vendors.csv      # name, currency, tax_rate, requires_po, bank_account, terms_days, address
python tools/load_data.py customers customers.csv  # name, email, timezone, terms_days
python tools/load_data.py invoices invoices.csv    # number, customer, issue_date, due_date, total, currency, paid, paid_on (optional)
python tools/load_data.py account 6200 "Software" expense
python tools/load_data.py recurring "Rent" out 450000 monthly --day 1 --match LANDLORD
```

A file is all or nothing: one bad line, named by its number, stops the whole file. A vendor's `bank_account` is what every payment detail on a bill is compared with, so enter it from a source you trust, not from a bill. The web app has no page for typing vendors or customers yet; use the API or this loader. There is no file upload for them in the browser.

## Tests

- Python: `.venv/bin/python -m pytest`. The last full run is in `data/counts.json`: <!--n:tests.passed-->425<!--/n--> passed, <!--n:tests.skipped-->1<!--/n--> skipped (it needs a Postgres, set `TEST_POSTGRES_URL`), coverage <!--n:tests.coverage_percent-->92.3<!--/n--> percent of the `booklantern` package.
- Seed check: `.venv/bin/python tools/score_seed.py` prints one line per planted problem.
- Extraction eval: `.venv/bin/python tools/eval_extraction.py` (see `EXTRACTION-EVAL.md`).
- Browser tests: `pnpm e2e` (needs Google Chrome; it starts its own API and web server and a throwaway database). It tests the last build, so run `pnpm build` first. <!--n:e2e.tests-->41<!--/n--> tests.

## Stop everything

Press Ctrl+C in each terminal. Data stays in the database.
