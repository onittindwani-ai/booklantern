"""Sign in, demo shortcuts, the refusal to start on unsafe settings, and a restart that never erases real data."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from booklantern import clock, demo
from booklantern.api import routes_auth
from booklantern.api.app import create_app
from booklantern.config import Settings
from booklantern.context import Ctx
from booklantern.models import Customer, State, Vendor
from sendora_core.auth import hash_password
from sendora_core.db import Base, make_engine, make_session_factory
from sendora_core.settings import ConfigError

from .conftest import make_ctx

REAL_SECRET = "test-only-Rt7Kq2Vw9Xm4Zc8Lb3Nf6Hy1Js5Dp0Ga2Ue7Tq4Wi9"
PASSWORD = "a-long-test-password-1"


def sub(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    return folder


def real_ctx(tmp_path, **kw) -> Ctx:
    base = dict(demo_mode=False, session_secret=REAL_SECRET, owner_password_hash=hash_password(PASSWORD))
    base.update(kw)
    return make_ctx(tmp_path, **base)


def real_client(tmp_path, **kw) -> TestClient:
    ctx = real_ctx(tmp_path, **kw)
    return TestClient(create_app(ctx.settings, ctx), base_url="http://api.test")


def test_login_key_ignores_spaces_and_capitals(tmp_path):
    c = real_client(tmp_path)
    variants = ["owner@example.test", " owner@example.test", "owner@example.test ", "OWNER@example.test", "\towner@example.test", "owner@example.test\n"]
    codes = [c.post("/api/auth/login", json={"email": v, "password": "wrong-password"}).status_code for v in variants]
    assert codes[:5] == [401] * 5 and codes[5] == 429  # the sixth try is refused whatever padding it uses


def test_login_accepts_a_padded_email_with_the_right_password(tmp_path):
    r = real_client(tmp_path).post("/api/auth/login", json={"email": "  Owner@Example.test ", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"] == "owner@example.test"


def test_login_refuses_oversize_fields(tmp_path):
    c = real_client(tmp_path)
    assert c.post("/api/auth/login", json={"email": "a" * 300 + "@x.test", "password": "x"}).status_code == 422
    assert c.post("/api/auth/login", json={"email": "owner@example.test", "password": "x" * 2000}).status_code == 422


def test_each_address_has_its_own_wider_limit(tmp_path):
    c = real_client(tmp_path, login_burst=2)
    codes = [c.post("/api/auth/login", json={"email": f"user{i}@x.test", "password": "x"}).status_code for i in range(40)]
    assert codes[0] == 401 and 429 in codes[30:]  # a new email every time never gets a fresh set of tries


def test_guesses_spread_over_many_addresses_still_run_out(tmp_path):
    ctx = real_ctx(tmp_path, login_burst=2)
    app = create_app(ctx.settings, ctx)
    codes = []
    for i in range(30):
        c = TestClient(app, base_url="http://api.test", client=(f"203.0.113.{i + 1}", 50000 + i))
        codes.append(c.post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong-password"}).status_code)
    assert codes[0] == 401 and 429 in codes[20:]
    other = TestClient(app, base_url="http://api.test", client=("198.51.100.5", 40000))
    assert other.post("/api/auth/login", json={"email": "someone.else@example.test", "password": "x"}).status_code == 401


def test_unknown_accounts_cost_the_same_work_as_wrong_passwords(tmp_path, monkeypatch):
    calls = []
    real = routes_auth.verify_password_or_dummy
    monkeypatch.setattr(routes_auth, "verify_password_or_dummy", lambda pw, h: (calls.append(h), real(pw, h))[1])
    assert real_client(tmp_path).post("/api/auth/login", json={"email": "nobody@x.test", "password": "x"}).status_code == 401
    assert calls == [None]  # a hash check against a throw away hash was still done


def test_a_real_owner_password_switches_every_demo_shortcut_off_even_in_demo_mode(tmp_path):
    ctx = real_ctx(tmp_path, demo_mode=True)
    assert ctx.settings.demo_shortcuts is False
    c = TestClient(create_app(ctx.settings, ctx), base_url="http://api.test")
    for email in ("approver@example.test", "viewer@example.test", "owner@example.test"):
        assert c.post("/api/auth/login", json={"email": email, "password": "demo-password-1"}).status_code == 401
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).json()["token"]
    assert c.post("/api/demo/reset").status_code == 404 and c.post("/api/demo/tick").status_code == 404
    assert c.post("/api/demo/advance", json={"hours": 1}).status_code == 404 and c.post("/api/demo/stress-bank", json={"n": 1}).status_code == 404
    assert c.get("/api/auth/me").json()["demo_mode"] is False  # the demo strip shows only while its routes exist
    assert any("owner password" in p for p in ctx.settings.problems())


def test_the_demo_reset_refuses_when_called_directly_with_an_owner_password(tmp_path):
    ctx = real_ctx(tmp_path, demo_mode=True)
    with ctx.factory() as s:
        s.add(Customer(key="C1", name="Real Customer", email="a@b.test"))
        s.commit()
    with ctx.factory() as s, pytest.raises(PermissionError):
        demo.reset(s, ctx)
    with ctx.factory() as s:
        assert s.scalars(select(Customer)).first() is not None  # nothing was erased


def test_demo_with_no_owner_password_keeps_working(tmp_path):
    ctx = make_ctx(tmp_path)
    c = TestClient(create_app(ctx.settings, ctx), base_url="http://api.test")
    r = c.post("/api/auth/login", json={"email": "approver@example.test", "password": "demo-password-1"})
    assert r.status_code == 200 and r.json()["role"] == "approver"


def test_the_demo_clock_is_used_only_while_demo_shortcuts_are_on(tmp_path):
    demo_ctx, real = make_ctx(sub(tmp_path, "d")), real_ctx(sub(tmp_path, "r"))
    with demo_ctx.factory() as s:
        assert demo_ctx.now(s) == clock.DEMO_START
    with real.factory() as s:
        s.add(State(key="clock_offset_hours", value="500"))
        s.commit()
        assert abs((real.now(s) - clock.datetime.now(clock.UTC)).total_seconds()) < 5  # real time, whatever an old offset says


def test_the_app_refuses_an_example_secret_outside_demo_mode(tmp_path):
    with pytest.raises(ConfigError):
        real_client(tmp_path, session_secret="change-me-to-a-long-random-string")


def test_a_demo_on_a_server_database_is_refused_before_anything_is_touched(tmp_path):
    s = Settings(_env_file=None, demo_mode=True, database_url="postgresql+psycopg://u:p@127.0.0.1:1/none", session_secret=REAL_SECRET)
    with pytest.raises(ConfigError):
        create_app(s)  # no connection is attempted: the check runs first, so nothing can be erased or seeded


def test_a_restart_never_seeds_over_real_data(tmp_path):
    ctx = make_ctx(tmp_path)  # demo mode on, no owner password: the case where the old code reset the whole database
    with ctx.factory() as s:
        s.add(Customer(key="C1", name="Entered By Hand", email="a@b.test"))
        s.commit()
    create_app(ctx.settings, ctx)  # a restart
    with ctx.factory() as s:
        assert s.scalars(select(Customer).where(Customer.name == "Entered By Hand")).first() is not None
        assert s.scalars(select(Vendor)).first() is None  # and the fictional seed was not loaded on top


def test_a_restart_with_an_owner_password_never_seeds(tmp_path):
    ctx = real_ctx(tmp_path, demo_mode=True)
    create_app(ctx.settings, ctx)
    with ctx.factory() as s:
        assert s.scalars(select(Vendor)).first() is None


def test_an_empty_demo_database_is_seeded_once(tmp_path):
    ctx = make_ctx(tmp_path)
    create_app(ctx.settings, ctx)
    with ctx.factory() as s:
        n = len(list(s.scalars(select(Vendor))))
    assert n == 8
    create_app(ctx.settings, ctx)
    with ctx.factory() as s:
        assert len(list(s.scalars(select(Vendor)))) == 8


def test_live_mode_refuses_the_placeholder_identity(tmp_path):
    with pytest.raises(ConfigError) as e:
        real_client(tmp_path, mode="live", email_adapter="smtp", smtp_host="mail.example.test")
    assert "COMPANY_NAME" in str(e.value) and "COMPANY_ADDRESS" in str(e.value) and "EMAIL_FROM" in str(e.value)
    ok = dict(mode="live", company_name="Rivera Works", company_address="12 Main Street, Springfield, IL 62701, USA", email_from="accounts@riveraworks.test", email_adapter="smtp")
    real_client(tmp_path, **ok)  # starts


def test_placeholders_are_listed_in_problems_in_draft_mode_and_not_in_demo(tmp_path):
    draft = real_ctx(tmp_path, email_adapter="smtp").settings
    assert any("COMPANY_NAME" in p for p in draft.problems()) and any("COMPANY_ADDRESS" in p for p in draft.problems())
    assert not any("COMPANY_" in p for p in make_ctx(sub(tmp_path, "x")).settings.problems())


def test_a_bad_reply_to_or_time_zone_is_a_problem(tmp_path):
    s = real_ctx(tmp_path, reply_to="not an address", default_timezone="Mars/Olympus").settings
    problems = " ".join(s.problems())
    assert "REPLY_TO" in problems and "DEFAULT_TIMEZONE" in problems


def test_an_empty_line_in_the_env_file_means_not_set(tmp_path):
    f = tmp_path / "e.env"
    f.write_text("LLM_CALL_BUDGET=\nLLM_BUDGET_USD=\nQBO_MINOR_VERSION=\nCOMPANY_ADDRESS=\n")
    s = Settings(_env_file=str(f))
    assert s.llm_call_budget is None and s.qbo_minor_version == "75" and s.company_address == ""


def test_a_settings_page_in_demo_reports_demo_only_while_shortcuts_exist(tmp_path):
    ctx = real_ctx(tmp_path, demo_mode=True)
    c = TestClient(create_app(ctx.settings, ctx), base_url="http://api.test")
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).json()["token"]
    assert c.get("/api/settings").json()["demo_mode"] is False
