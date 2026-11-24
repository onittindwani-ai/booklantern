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
- **Postgres:** `pg_dump --format=custom "$DATABASE_URL_PLAIN" > booklantern.dump` using the plain `postgresql://` form of the address. `deploy/hetzner/backup.sh` does it for you.
- **Uploaded bills** live in `UPLOAD_DIR`. Back that folder up as well.

## Restore (test this once)

1. Make an empty database. 2. Postgres: `pg_restore --clean --if-exists -d "$DATABASE_URL_PLAIN" booklantern.dump`. SQLite: put the file back. 3. Start the API, open the Audit log and press Check the chain.

## Logs

The API and worker log to the console (`docker compose logs -f api worker`). Logs can hold vendor and customer names. Check them before you share them.
