# Updating

1. Back up the database and the uploads folder (`11`).
2. Read `CHANGELOG.md`.
3. `git pull`.
4. Reinstall: `make install`, or `.venv/bin/pip install -c constraints.txt -e packages/core-py -e "apps/api[dev]"` (with a uv environment: `uv pip install --python .venv/bin/python -c constraints.txt -e packages/core-py -e "apps/api[dev]"`) then `pnpm install && pnpm build`.
5. Migrate (Postgres): `cd apps/api && ../../.venv/bin/alembic upgrade head`. `alembic` reads `DATABASE_URL` from the environment or from `.env` (or the file named by `ENV_FILE`) and stops when it finds none. SQLite creates missing tables on start and adds the few columns that were added after release 1.0.0 (`booklantern.dbupgrade`), but it does not change anything else in old tables, so across any other schema change use Postgres. There is no export button: keep the old `.sqlite3` file as your backup (`11`).
6. Restart the API, worker and web app.
7. Run `python tools/doctor.py` and open the Audit log.

The shared code in `packages/` (the base) is versioned separately. Do not edit it in a client install. `.env.example` lists every setting (a test fails when a setting is missing from it or from `04`); run `make check-env` to compare it with your `.env` after an update.

## Pinned packages

`constraints.txt` pins every third party Python package to the version the tests ran against, so an install today gives the same set as the one that was tested (`make install`, the Docker image and CI all use it). After a deliberate upgrade of a package, install the new version, run the tests, then rewrite the file with `tools/make_constraints.py` from the hub repository (`sendora-ai-systems`).

## Changes in 1.0.1 that can stop an old install from starting or change what you see

- Postgres: run `alembic upgrade head` (migration `0004` adds `ll_bill.had_block` and fills it from the findings already on file). SQLite adds the column by itself at start.
- `MODE=live` with the bills mailbox and the sender mailbox on one account now needs `REPLY_TO` set to a different mailbox that a person reads. The app refuses to start otherwise (or stays in draft), because a customer's "stop" reply would land among the bills.
- A server that runs the offline demo (`DEMO_MODE=true`, no `OWNER_PASSWORD_HASH`) together with a real accounting, payments, mail or inbox adapter, or with any write setting on, is refused at start. Set `OWNER_PASSWORD_HASH` and `DEMO_MODE=false`, or set `ALLOW_DEMO_SERVER=true` on a throw away machine. The API Docker image now sets `DEMO_MODE=false` itself.
- Bank import: when there is more than one bank account the file import needs `account_id` (the web page asks). A statement line whose amount cannot be read (a minus sign, `DR` or `CR`, brackets) now refuses the whole file and lists every bad line, instead of guessing.
- The invoice import accepts an optional `paid_on` column. Without it a paid invoice no longer gets its issue date as the payment date.
- `INTAKE_ALLOWED_SENDERS` (new, optional): a list of addresses allowed to send bills to the intake mailbox. A bill from anyone else is held with a blocking finding.
