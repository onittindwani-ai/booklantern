"""A real install (DEMO_MODE off, no seed) can do the core job from nothing: add the vendors, customers, bank account and chart of accounts, read a bill, approve it, import a bank file, match, and chase an invoice."""

import io
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy import select

from booklantern import setup_data
from booklantern.api.app import create_app
from booklantern.config import Settings
from booklantern.models import Account, BankAccount, Bill, Customer, Invoice, RecurringItem, Vendor

from .test_hardening_auth import PASSWORD, real_ctx

ROOT = Path(__file__).resolve().parents[3]
IDENTITY = dict(company_name="Rivera Works", company_address="10 Elm St, Austin TX 78701", email_from="accounts@riveraworks.test", reply_to="ar@riveraworks.test", default_timezone="America/Chicago")


def bill_pdf(vendor="Orchard Parts Ltd", number="OP-7", total="1,250.00", extra=()):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 780
    for ln in [vendor, "INVOICE", f"Invoice No: {number}", "Invoice Date: 2026-03-02", "Due Date: 2026-04-01", "Bill To: Rivera Works", *extra, f"Subtotal USD {total}", "Tax USD 0.00", f"Total Due USD {total}"]:
        c.drawString(72, y, ln)
        y -= 18
    c.save()
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path):
    ctx = real_ctx(tmp_path, **IDENTITY)
    c = TestClient(create_app(ctx.settings, ctx), base_url="http://api.test")
    r = c.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD})
    assert r.status_code == 200
    c.headers["x-session"] = r.json()["token"]
    c.ctx = ctx
    return c


def test_a_fresh_install_starts_empty_and_says_so(client):
    assert client.get("/api/bills").json() == [] and client.get("/api/vendors").json() == [] and client.get("/api/bank/accounts").json() == []
    with client.ctx.factory() as s:
        assert s.scalars(select(Vendor)).first() is None and s.scalars(select(Bill)).first() is None


def test_the_demo_routes_do_not_exist_on_a_real_install(client):
    assert client.post("/api/demo/reset").status_code in (403, 404)
    assert client.post("/api/demo/tick").status_code in (403, 404)


def test_the_whole_setup_through_the_api_and_the_first_bill_end_to_end(client):
    assert client.post("/api/bank/accounts", json={"name": "Main", "currency": "USD", "opening_minor": 500_000, "opening_date": "2026-01-01"}).status_code == 200
    assert client.post("/api/accounts", json={"code": "6200", "name": "Software", "kind": "expense"}).status_code == 200
    assert client.post("/api/recurring", json={"name": "Rent", "direction": "out", "amount_minor": 450_000, "cadence": "monthly", "day": 1, "match_text": "LANDLORD"}).status_code == 200
    r = client.post("/api/vendors", json={"name": "Orchard Parts Ltd", "currency": "USD", "bank_account": "021000021 123456789"})
    assert r.status_code == 200
    csv_vendors = "name,currency,tax_rate,requires_po,bank_account,terms_days,address\nHarbor Freight Co,USD,8.25,yes,,45,1 Pier Rd\n"
    assert client.post("/api/vendors/import", json={"text": csv_vendors}).json() == {"added": 1, "skipped": []}
    assert client.post("/api/customers/import", json={"text": "name,email,timezone,terms_days\nNorthwind LLC,ap@northwind.test,America/Chicago,30\n"}).json()["added"] == 1
    inv = "number,customer,issue_date,due_date,total,currency,paid\nINV-100,Northwind LLC,2025-10-01,2025-11-01,\"2,400.00\",USD,0\n"
    assert client.post("/api/invoices/import", json={"text": inv}).json()["added"] == 1

    up = client.post("/api/documents/upload", content=bill_pdf(extra=["Routing number: 021000021", "Account number: 123456789"]), headers={"x-filename": "op7.pdf"})
    assert up.status_code == 200, up.text
    bills = client.get("/api/bills").json()
    assert len(bills) == 1 and bills[0]["number"] == "OP-7" and bills[0]["total_minor"] == 125_000
    bill = client.get(f"/api/bills/{bills[0]['id']}").json()
    assert bill["vendor_id"] is not None  # matched to the vendor the owner typed in, not to a seeded list
    assert not [e for e in bill.get("exceptions", []) if e["severity"] == "block"]
    assert client.post(f"/api/bills/{bills[0]['id']}/approve", json={}).status_code == 200
    posted = client.post(f"/api/bills/{bills[0]['id']}/post").json()
    assert posted["posted"] is False and "MODE is draft" in posted["reason"]  # a real install posts nothing until the owner goes live

    bank = client.post("/api/bank/import", json={"text": "Date,Description,Amount,Reference\n2026-03-05,ORCHARD PARTS OP-7,-1250.00,R1\n2026-03-06,NORTHWIND INV-100,2400.00,R2\n", "name": "march.csv"})
    assert bank.status_code == 200 and bank.json()["added"] == 2


def test_a_wrong_account_on_a_bill_is_caught_on_a_fresh_install(client):
    client.post("/api/vendors", json={"name": "Orchard Parts Ltd", "currency": "USD", "bank_account": "021000021 123456789"})
    client.post("/api/documents/upload", content=bill_pdf(number="OP-8", extra=["Routing number: 021000021", "Account number: 555555555"]), headers={"x-filename": "op8.pdf"})
    b = client.get("/api/bills").json()[0]
    kinds = {e["kind"]: e["severity"] for e in client.get(f"/api/bills/{b['id']}").json()["exceptions"]}
    assert kinds.get("bank_detail_changed") == "block"


def test_the_same_bill_sent_twice_is_a_duplicate_on_a_fresh_install(client):
    client.post("/api/documents/upload", content=bill_pdf(number="DUP-1"), headers={"x-filename": "a.pdf"})
    client.post("/api/documents/upload", content=bill_pdf(number="DUP-1", extra=["Page 1 of 1"]), headers={"x-filename": "b.pdf"})
    second = max(client.get("/api/bills").json(), key=lambda b: b["id"])
    assert "duplicate_exact" in {e["kind"] for e in client.get(f"/api/bills/{second['id']}").json()["exceptions"]}


def test_setup_data_is_owner_only(client, tmp_path):
    with client.ctx.factory():
        pass
    c2 = TestClient(create_app(client.ctx.settings, client.ctx), base_url="http://api.test")
    assert c2.post("/api/vendors", json={"name": "X"}).status_code in (401, 403)


# ---- imports ----

def test_a_bad_line_stops_the_whole_import_and_is_named(tmp_path):
    ctx = real_ctx(tmp_path, **IDENTITY)
    with ctx.factory() as s:
        with pytest.raises(setup_data.SetupError, match="Line 3"):
            setup_data.import_vendors(s, ctx.settings, "t", "name,currency\nGood Co,USD\nBad Co,XXX\n")
        assert s.scalars(select(Vendor)).first() is None  # nothing from the file was kept


def test_importing_the_same_vendors_twice_adds_nothing_the_second_time(tmp_path):
    ctx = real_ctx(tmp_path, **IDENTITY)
    text = "name,currency\nAcme Co,USD\nBeta Co,EUR\n"
    with ctx.factory() as s:
        assert setup_data.import_vendors(s, ctx.settings, "t", text).added == 2
        again = setup_data.import_vendors(s, ctx.settings, "t", text)
        assert again.added == 0 and len(again.skipped) == 2


def test_invoices_need_their_customer_and_a_sensible_total(tmp_path):
    ctx = real_ctx(tmp_path, **IDENTITY)
    head = "number,customer,issue_date,due_date,total\n"
    with ctx.factory() as s:
        with pytest.raises(setup_data.SetupError, match="no customer"):
            setup_data.import_invoices(s, ctx.settings, "t", head + "I-1,Nobody,2026-01-01,2026-02-01,10.00\n")
        setup_data.create_customer(s, ctx.settings, "t", name="Northwind", email="a@northwind.test")
        with pytest.raises(setup_data.SetupError, match="due date is before"):
            setup_data.import_invoices(s, ctx.settings, "t", head + "I-1,Northwind,2026-02-01,2026-01-01,10.00\n")
        with pytest.raises(setup_data.SetupError, match="above zero"):
            setup_data.import_invoices(s, ctx.settings, "t", head + "I-1,Northwind,2026-01-01,2026-02-01,0.00\n")
        assert setup_data.import_invoices(s, ctx.settings, "t", head + "I-1,Northwind,2026-01-01,2026-02-01,\"1,000.00\"\n").added == 1


def test_a_customer_with_a_bad_address_or_timezone_is_refused(tmp_path):
    ctx = real_ctx(tmp_path, **IDENTITY)
    with ctx.factory() as s:
        with pytest.raises(setup_data.SetupError):
            setup_data.create_customer(s, ctx.settings, "t", name="A", email="nope")
        with pytest.raises(setup_data.SetupError):
            setup_data.create_customer(s, ctx.settings, "t", name="B", email="b@x.test", timezone="Mars/Base")
        c = setup_data.create_customer(s, ctx.settings, "t", name="C", email="c@x.test")
        assert c.timezone == "America/Chicago"  # the company's DEFAULT_TIMEZONE, not a hard coded city


def test_the_chart_of_accounts_and_repeating_items_check_their_input(tmp_path):
    ctx = real_ctx(tmp_path, **IDENTITY)
    with ctx.factory() as s:
        setup_data.create_account(s, "t", code="6200", name="Software", kind="expense")
        with pytest.raises(setup_data.SetupError, match="already"):
            setup_data.create_account(s, "t", code="6200", name="Again", kind="expense")
        with pytest.raises(setup_data.SetupError):
            setup_data.create_account(s, "t", code="1", name="Odd", kind="mystery")
        with pytest.raises(setup_data.SetupError):
            setup_data.create_recurring(s, "t", name="Rent", direction="sideways", amount_minor=1, cadence="monthly")
        assert setup_data.create_recurring(s, "t", name="Rent", direction="out", amount_minor=450_000, cadence="monthly").id


# ---- the command line loader ----

def run_loader(env_file: Path, *args: str):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "load_data.py"), "--env-file", str(env_file), *args], capture_output=True, text=True, cwd=ROOT)


def test_the_command_line_loader_sets_up_a_real_database(tmp_path):
    env = tmp_path / "x.env"
    env.write_text(f"DATABASE_URL=sqlite:///{tmp_path / 'cli.sqlite3'}\nBASE_CURRENCY=USD\n")
    vendors = tmp_path / "v.csv"
    vendors.write_text("name,currency,bank_account\nOrchard Parts Ltd,USD,021000021 123456789\n")
    assert "OK added 1" in run_loader(env, "vendors", str(vendors)).stdout
    assert "OK added 0, left as they were 1" in run_loader(env, "vendors", str(vendors)).stdout
    assert "OK bank account" in run_loader(env, "bank-account", "Main", "--currency", "USD", "--opening", "1000", "--opening-date", "2026-01-01").stdout
    assert "OK account 6200" in run_loader(env, "account", "6200", "Software", "expense").stdout
    bad = tmp_path / "bad.csv"
    bad.write_text("name,currency\nX,QQQ\n")
    r = run_loader(env, "vendors", str(bad))
    assert r.returncode == 1 and "PROBLEM" in r.stdout


def test_the_base_currency_setting_is_used_for_new_records(tmp_path):
    ctx = real_ctx(tmp_path, base_currency="EUR", **IDENTITY)
    with ctx.factory() as s:
        assert setup_data.create_vendor(s, ctx.settings, "t", name="Euro Co").currency == "EUR"
        assert setup_data.create_bank_account(s, ctx.settings, "t", name="Main", opening_date=date(2026, 1, 1)).currency == "EUR"


# ---- identity placeholders keep a live install in draft mode ----

def test_the_placeholder_company_name_is_a_problem_outside_demo():
    s = Settings(_env_file=None, demo_mode=False, session_secret="x" * 40, owner_password_hash="x", email_adapter="seed")
    assert any("COMPANY_NAME" in p for p in s.problems())
    ok = Settings(_env_file=None, demo_mode=False, session_secret="x" * 40, owner_password_hash="x", company_name="Rivera Works", email_adapter="seed")
    assert not any("COMPANY_NAME" in p for p in ok.problems())


def test_a_live_install_with_the_placeholder_identity_is_refused_at_start():
    from sendora_core.settings import ConfigError, Mode

    s = Settings(_env_file=None, demo_mode=False, mode=Mode.LIVE, session_secret="test-only-Rt7Kq2Vw9Xm4Zc8Lb3Nf6Hy1Js5Dp0Ga2Ue7Tq4Wi9", owner_password_hash="x")
    with pytest.raises(ConfigError, match="COMPANY_NAME"):
        s.check_runtime()


def test_a_bad_reply_to_or_timezone_or_short_address_is_named():
    s = Settings(_env_file=None, demo_mode=False, session_secret="x" * 40, owner_password_hash="x", company_name="Rivera Works", reply_to="not-an-address", default_timezone="Mars/Base", company_address="x", email_adapter="smtp")
    text = " ".join(s.problems())
    assert "REPLY_TO" in text and "DEFAULT_TIMEZONE" in text and "COMPANY_ADDRESS" in text
