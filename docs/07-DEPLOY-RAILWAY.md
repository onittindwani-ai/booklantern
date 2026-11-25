# Deploy on Railway

**Not tested: no Railway account was used.** Every step is UNVERIFIED and comes from our general knowledge of Railway. Check each against https://docs.railway.com before you rely on it. A starting `railway.json` is in `deploy/railway/` in case your account accepts it.

You make four things in one Railway project: a Postgres database, the API, the worker and, if you do not use Vercel, the web app.

1. New project, then add Postgres.
2. Add a service from your Git repository named `api`. Dockerfile path `apps/api/Dockerfile`, repository root as the build context. Health check path `/health`.
3. Variables for `api`: `DATABASE_URL` (use the Postgres reference and make it start with `postgresql+psycopg://`), `SESSION_SECRET`, `MODE=draft`, `DEMO_MODE=false`, `OWNER_EMAIL`, `OWNER_PASSWORD_HASH` and your adapter choices (see `04`).
4. The Dockerfile start command runs `alembic upgrade head` on boot for Postgres.
5. Add a service `worker` with the same Dockerfile and variables and start command `python -m booklantern.worker`. No public address.
6. Uploaded bills are saved to `UPLOAD_DIR`. Attach a volume to `api` and `worker` and point `UPLOAD_DIR` at it, or uploads vanish on redeploy.
6a. Set `FORWARDED_ALLOW_IPS` on `api` to the address your requests arrive from (Railway's private network range; the API image defaults it to `127.0.0.1`). Without it the API sees every visitor as one address: all visitors then share one sign in limit and one rate limit, so a few wrong passwords can block everybody. Run uvicorn with `--proxy-headers` (the image does).
7. Add a service `web` (Dockerfile path `apps/web/Dockerfile`) with `API_BASE_URL` set to the API's private address, or use Vercel.
8. Give `web` a public domain. Keep `api` private if you can.
9. Open the `api` shell and run `python tools/doctor.py`.

Keep `MODE=draft` until `09-GO-LIVE-CHECKLIST.md` is finished.
