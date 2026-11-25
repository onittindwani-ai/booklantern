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
