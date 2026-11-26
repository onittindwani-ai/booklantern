"""The Booklantern API. Every route under /api needs a signed in session, except sign in."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from booklantern.api import routes_admin, routes_auth, routes_demo, routes_read, routes_setup, routes_write
from booklantern.config import Settings
from booklantern.context import Ctx
from booklantern.dbupgrade import add_missing_columns
from sendora_core.app import SESSION_COOKIE, create_base_app
from sendora_core.auth import read_session_token
from sendora_core.db import Base, make_engine, make_session_factory
from sendora_core.ratelimit import TokenBucket

PUBLIC = {"/api/auth/login", "/api/auth/logout"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _holds_data(ctx: Ctx) -> bool:
    """True when the database already holds anything a person or a mailbox put there. A demo seed never goes on top of that."""
    from sqlalchemy import select

    from booklantern.models import BankTransaction, Bill, Customer, Document, Invoice, Vendor

    with ctx.factory() as s:
        return any(s.scalars(select(m.id).limit(1)).first() is not None for m in (Vendor, Customer, Invoice, Bill, Document, BankTransaction))


def _seed_if_empty(ctx: Ctx) -> None:
    """A fresh demo database starts with the sample seed world, so the first page is never empty.

    Only for a demo with no owner password, on a local SQLite file, and only when the database holds nothing at all: a restart can never
    erase or reseed data that someone entered.
    """
    from booklantern import demo

    if not (ctx.settings.demo_shortcuts and ctx.settings.database_url.startswith("sqlite")) or _holds_data(ctx):
        return
    try:
        with ctx.factory() as s:
            demo.reset(s, ctx)
    except FileNotFoundError as exc:
        logging.getLogger("booklantern").warning("The demo data was not loaded: %s", exc)


def create_app(settings: Settings | None = None, ctx: Ctx | None = None) -> FastAPI:
    settings = settings or (ctx.settings if ctx is not None else Settings())
    settings.check_runtime()  # before anything touches the database: an unsafe configuration must not erase, seed or create anything
    if ctx is None:
        engine = make_engine(settings.database_url)
        from sendora_core import models as _c  # noqa: F401
        import booklantern.models  # noqa: F401

        if settings.database_url.startswith("sqlite"):
            Base.metadata.create_all(engine)  # SQLite zero setup path. Postgres uses `alembic upgrade head`.
            add_missing_columns(engine)  # a database file made by an older version gets the columns added since
        ctx = Ctx(settings, make_session_factory(engine))
    _seed_if_empty(ctx)
    app = create_base_app(ctx.settings, ctx.factory)
    app.title, app.version = "Booklantern API", "1.0.2"
    app.state.ctx = ctx
    # A page makes several calls at once. This bucket is per client address (set uvicorn --proxy-headers so that is the real visitor, not the web server).
    app.state.limiter = TokenBucket(capacity=600, refill_per_sec=20.0)
    # Sign in attempts per address and email: a burst of LOGIN_BURST (default 5), then one more every 12 seconds.
    app.state.login_bucket = TokenBucket(capacity=settings.login_burst, refill_per_sec=1 / 12)
    # And a wider limit per address alone, so changing the email in every try does not give a fresh set of tries.
    app.state.login_ip_bucket = TokenBucket(capacity=max(30, settings.login_burst * 6), refill_per_sec=1 / 3)
    # There is deliberately NO bucket per account alone: it would let anyone who knows the owner's email keep the owner out of their own system from any address.
    # Every limit above names the address of the person trying, so the owner, on their own address, is never held up by what a stranger does.

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        p = request.url.path
        if p.startswith("/api/") and p not in PUBLIC:
            header_token = request.headers.get("x-session")
            token = request.cookies.get(SESSION_COOKIE) or header_token
            data = read_session_token(ctx.settings.session_secret, token) if token else None
            if data is None:
                return JSONResponse({"error": {"code": "http_401", "message": "Sign in to continue."}}, 401)
            # A change made with the browser's cookie alone is what a page on another site can cause. The web app adds this header (a page on another site cannot), and a
            # caller that sends the session in the x-session header (the web app's own server, tools) is not using the cookie at all.
            if request.method not in SAFE_METHODS and not header_token and request.headers.get("x-booklantern") != "1":
                return JSONResponse({"error": {"code": "http_403", "message": "Missing request header (x-booklantern: 1). A change needs it when the session comes from the cookie."}}, 403)
            request.state.user = data
        return await call_next(request)

    for r in (routes_auth, routes_read, routes_write, routes_setup, routes_admin, routes_demo):
        app.include_router(r.router)
    return app


def app_from_env() -> FastAPI:  # uvicorn booklantern.api.app:app_from_env --factory
    settings = Settings(_env_file=os.environ.get("ENV_FILE", ".env"))
    logging.getLogger("booklantern").setLevel(getattr(logging, settings.log_level))
    return create_app(settings)
