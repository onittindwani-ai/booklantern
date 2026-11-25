# Operating and backups

## Daily

- Open Invoice review. Approve, fix or reject the bills waiting.
- Open Approvals and decide drafted reminders or other risky actions. The person who asked cannot approve it.
- Open Exceptions and clear the list.

## Weekly

- Import the new bank statement CSV on Reconciliation, check the Needs attention list.
- Look at Collections: which invoices are waiting, which are stopped and why.
- Audit log: press Check the chain. If it says broken, something changed history. Stop and look.

## Month end

Reports, then Download the PDF. Read it before you share it. It is a working pack, not accounting or tax advice.

## Stopping fast

Press **Pause all**. It blocks every outgoing action at once. To stop even if the web app is down set `KILL_SWITCH=true` and restart the API and worker.

## Backups

- **SQLite:** `sqlite3 booklantern.sqlite3 ".backup backup.sqlite3"` while it runs, or stop the app and copy the file.
- **Postgres, Docker:** `deploy/hetzner/backup.sh` does it for you. It can run from cron, writes the dump to a partial file and keeps it only when it is not empty, also saves the uploads as a tar file, keeps the newest 14 of each, and with `BACKUP_COPY_TO=user@host:/path/` copies them to another machine. A copy on the same disk is not a backup.
- **Postgres, your own server:** `pg_dump --format=custom "postgresql://USER:PASSWORD@HOST:5432/booklantern" > booklantern.dump` (the plain `postgresql://` form of `DATABASE_URL`, without `+psycopg`).
- **Uploaded bills** live in `UPLOAD_DIR`. In Docker that is the `uploads` volume, which `backup.sh` saves. Otherwise back that folder up as well.

## Restore (test this once)

1. Make an empty database. 2. Postgres: `pg_restore --clean --if-exists -d "postgresql://USER:PASSWORD@HOST:5432/booklantern" booklantern.dump`. In Docker: `docker compose exec -T db pg_restore --clean --if-exists -U booklantern -d booklantern < booklantern-DATE.dump`. SQLite: put the file back. Restore into a spare database first and look at it; a restore that was never tried is a hope, not a backup. 3. Start the API, open the Audit log and press Check the chain.

## Logs

The API and worker log to the console (`docker compose logs -f api worker`). Logs can hold vendor and customer names. Check them before you share them.
