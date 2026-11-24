# Run it on your own computer

`01-QUICK-DEMO.md` is the fast version. This is the full one, including real settings and Postgres.

## Install

1. Python 3.12 or newer (or uv, which fetches it), Node 22 or newer, pnpm (`corepack enable` or `npm i -g pnpm`). `make install` picks uv or python3.12 for you.
2. `python3.12 -m venv .venv`, or with uv (no Python 3.12 needed first): `uv venv --python 3.12 .venv`
3. `.venv/bin/pip install -e packages/core-py -e "apps/api[dev]"`, or with uv: `uv pip install --python .venv/bin/python -e packages/core-py -e "apps/api[dev]"` (add `-e "apps/api[postgres]"` if you use Postgres).
4. `pnpm install` then `pnpm build`.

## Settings

`cp .env.example .env`, then follow `04-ENVIRONMENT-VARIABLES.md`. Run `make check-env` (it needs only Python) and then `python tools/doctor.py`. The first reads your file, the second tests the services. Neither prints a value.

## Database

- **SQLite** (default): tables are created on start. In demo mode the made up company is loaded when the database is empty.
- **Postgres**: set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname`, then `cd apps/api && ../../.venv/bin/alembic upgrade head`. Do this on every update.

## Two programs, then the web app

Run each in its own terminal, from the project folder.

1. **API:** `.venv/bin/python -m uvicorn booklantern.api.app:app_from_env --factory --port 8000 --proxy-headers`
2. **Worker** (reads the mailbox, runs the reminder and forecast jobs): `.venv/bin/python -m booklantern.worker`
3. **Web:** `pnpm --filter web start` after `pnpm build`, or `pnpm dev` while you change code.

Open http://localhost:3000.

## Tests

- Python: `.venv/bin/python -m pytest`. The last full run is in `data/counts.json`: <!--n:tests.passed-->219<!--/n--> passed, <!--n:tests.skipped-->1<!--/n--> skipped (it needs a Postgres, set `TEST_POSTGRES_URL`), coverage <!--n:tests.coverage_percent-->92.9<!--/n--> percent of the `booklantern` package.
- Seed check: `.venv/bin/python tools/score_seed.py` prints one line per planted problem.
- Extraction eval: `.venv/bin/python tools/eval_extraction.py` (see `EXTRACTION-EVAL.md`).
- Browser tests: `pnpm e2e` (needs Google Chrome; it starts its own API and web server and a throwaway database). It tests the last build, so run `pnpm build` first. <!--n:e2e.tests-->41<!--/n--> tests.

## Stop everything

Press Ctrl+C in each terminal. Data stays in the database.
