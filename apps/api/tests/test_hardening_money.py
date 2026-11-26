"""Money moves: posting, bank matching, reminders. Each one stops when the owner's switch in the app says stop, and none can be done twice by two clicks."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from booklantern import bankservice, collections, posting, setup_data
from booklantern.config import Settings
from booklantern.models import BankAccount, BankTransaction, Bill, Customer, Invoice, Match, Payment, Reminder, State, Vendor
from booklantern.util import csv_safe
from sendora_core.adapters import AdapterError
from sendora_core.settings import Mode

from .conftest import freeze_clock, make_ctx

# Reminders go out on business days and in business hours of the customer's own time zone, so these tests run on a clock that is always a Tuesday at 11:00 in New York
# (the real time made them pass only from Monday to Friday between 9 and 17 there). Everything below that depends on "now" sees this moment.
PINNED_NOW = datetime(2026, 12, 1, 16, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _tuesday_morning(monkeypatch):
    freeze_clock(monkeypatch, PINNED_NOW)


class CountingAccounting:
    def __init__(self):
        self.calls = []

    def create_draft_bill(self, draft):
        self.calls.append(draft)
        return f"EXT-{len(self.calls)}"


class CountingEmail:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def send(self, *, from_addr, to, subject, body, **kw):
        if to in self.fail_for:
            raise AdapterError("the mail server said no")
        self.sent.append({"from": from_addr, "to": to, "subject": subject, "body": body})


def live_ctx(tmp_path, **kw):
    """A live install: example identity values replaced, accounting writes and email on."""
    base = dict(demo_mode=False, mode=Mode.LIVE, session_secret="test-only-Rt7Kq2Vw9Xm4Zc8Lb3Nf6Hy1Js5Dp0Ga2Ue7Tq4Wi9", owner_password_hash="x", company_name="Rivera Works", company_address="10 Elm St, Austin TX 78701",
                email_from="accounts@riveraworks.test", accounting_write=True)
    base.update(kw)
    return make_ctx(tmp_path, **base)


def add_customer_invoice(s, ctx, email="pay@customer.test", number="INV-1", due=date(2026, 1, 10), total=100_000):
    c = setup_data.create_customer(s, ctx.settings, "t", name=f"Customer {number}", email=email)
    inv = Invoice(customer_id=c.id, number=number, issue_date=date(2025, 12, 10), due_date=due, currency="USD", total_minor=total)
    s.add(inv)
    s.flush()
    return inv


def approved_bill(s, number="B-1"):
    v = setup_data.create_vendor(s, Settings(_env_file=None), "t", name=f"Vendor {number}")
    b = Bill(vendor_id=v.id, vendor_name_read=v.name, number=number, issue_date=date(2026, 1, 2), due_date=date(2026, 2, 1), currency="USD", subtotal_minor=1000, tax_minor=0, total_minor=1000, status="approved", document_id=None)
    s.add(b)
    s.flush()
    return b


# ---- posting ----

def test_the_kill_switch_set_in_the_app_stops_a_post_even_when_the_environment_says_live(tmp_path):
    ctx = live_ctx(tmp_path)
    ctx.adapters.accounting = CountingAccounting()
    with ctx.factory() as s:
        b = approved_bill(s)
        s.add(State(key="kill_switch", value="1"))
        s.commit()
        out = posting.post_draft(s, ctx, b.id, "owner")
        assert out["posted"] is False and ctx.adapters.accounting.calls == [] and s.get(Bill, b.id).status == "approved"


def test_force_draft_set_in_the_app_stops_a_post_and_the_switch_off_lets_it_through(tmp_path):
    ctx = live_ctx(tmp_path)
    ctx.adapters.accounting = CountingAccounting()
    with ctx.factory() as s:
        b = approved_bill(s)
        s.add(State(key="force_draft", value="1"))
        s.commit()
        assert posting.post_draft(s, ctx, b.id, "owner")["posted"] is False and ctx.adapters.accounting.calls == []
        s.get(State, "force_draft").value = "0"
        s.commit()
        out = posting.post_draft(s, ctx, b.id, "owner")
        assert out["posted"] is True and len(ctx.adapters.accounting.calls) == 1 and ctx.adapters.accounting.calls[0].idempotency_key == f"booklantern-bill-{b.id}"


def test_a_bill_cannot_be_posted_twice_or_approved_twice(tmp_path):
    ctx = live_ctx(tmp_path)
    ctx.adapters.accounting = CountingAccounting()
    with ctx.factory() as s:
        b = approved_bill(s)
        assert posting.post_draft(s, ctx, b.id, "owner")["posted"] is True
        with pytest.raises(ValueError):
            posting.post_draft(s, ctx, b.id, "owner")
        assert len(ctx.adapters.accounting.calls) == 1
        with pytest.raises(ValueError):
            posting.approve(s, b.id, "owner")


def test_a_failed_post_puts_the_bill_back_so_it_can_be_tried_again(tmp_path):
    ctx = live_ctx(tmp_path)

    class Down(CountingAccounting):
        def create_draft_bill(self, draft):
            raise RuntimeError("accounting system is down")

    ctx.adapters.accounting = Down()
    with ctx.factory() as s:
        b = approved_bill(s)
        with pytest.raises(RuntimeError):
            posting.post_draft(s, ctx, b.id, "owner")
        assert s.get(Bill, b.id).status == "approved"


def test_a_bill_with_nothing_on_it_cannot_be_approved(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.factory() as s:
        b = Bill(vendor_name_read="", number="", currency="USD", total_minor=0, status="needs_review")
        s.add(b)
        s.flush()
        with pytest.raises(ValueError, match="vendor"):
            posting.approve(s, b.id, "owner")


# ---- bank matching ----

def bank_with_line(s, ctx, amount=100_000, currency="USD"):
    a = setup_data.create_bank_account(s, ctx.settings, "t", name="Main", currency=currency, opening_minor=0, opening_date=date(2026, 1, 1))
    t = BankTransaction(bank_account_id=a.id, ref="R1", posted_on=date(2026, 1, 5), description="PAYMENT", amount_minor=amount, currency=currency, row_hash="h1")
    s.add(t)
    s.flush()
    return t


def test_a_bank_file_with_no_account_says_so(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.factory() as s:
        with pytest.raises(Exception, match="no bank account"):
            bankservice.import_csv(s, "Date,Description,Amount\n2026-01-05,X,1.00\n", "b1")


def test_a_manual_link_cannot_pay_more_than_the_line_or_the_invoice_or_mix_currencies(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.factory() as s:
        inv = add_customer_invoice(s, ctx, total=100_000)
        t = bank_with_line(s, ctx, amount=60_000)
        with pytest.raises(ValueError, match="more than the bank line"):
            bankservice.link_manually(s, t.id, "invoice", inv.id, 70_000, "owner")
        eur = Invoice(customer_id=inv.customer_id, number="EUR-1", issue_date=date(2026, 1, 1), due_date=date(2026, 2, 1), currency="EUR", total_minor=5_000)
        s.add(eur)
        s.flush()
        with pytest.raises(ValueError, match="in USD and the invoice is in EUR"):
            bankservice.link_manually(s, t.id, "invoice", eur.id, 1_000, "owner")
        bankservice.link_manually(s, t.id, "invoice", inv.id, 60_000, "owner")
        t2 = BankTransaction(bank_account_id=t.bank_account_id, ref="R2", posted_on=date(2026, 1, 6), description="MORE", amount_minor=90_000, currency="USD", row_hash="h2")
        s.add(t2)
        s.flush()
        with pytest.raises(ValueError, match="more than the amount on the document"):
            bankservice.link_manually(s, t2.id, "invoice", inv.id, 50_000, "owner")


def test_taking_a_link_back_reopens_the_invoice_and_removes_the_payment(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.factory() as s:
        inv = add_customer_invoice(s, ctx, total=100_000)
        t = bank_with_line(s, ctx, amount=100_000)
        m = bankservice.link_manually(s, t.id, "invoice", inv.id, 100_000, "owner")
        bankservice.record_payments(s)
        s.flush()
        s.refresh(inv)
        assert inv.status == "paid" and s.scalars(select(Payment)).first() is not None
        bankservice.unlink(s, m.id, "owner")
        s.flush()
        s.refresh(inv)
        assert inv.status == "open" and inv.paid_minor == 0 and s.scalars(select(Payment)).first() is None and s.scalars(select(Match)).first() is None
        assert s.get(BankTransaction, t.id).status == "unmatched"


# ---- reminders ----

def due_ctx(tmp_path, **kw):
    ctx = live_ctx(tmp_path, **kw)
    ctx.adapters.email = CountingEmail()
    return ctx


def drafted(s, ctx, who="pay@customer.test", number="INV-1"):
    inv = add_customer_invoice(s, ctx, email=who, number=number, due=date(2025, 11, 1))
    collections.plan_reminders(s, ctx)
    r = s.scalars(select(Reminder).where(Reminder.invoice_id == inv.id)).first()
    assert r is not None, "a reminder was drafted for an invoice long overdue"
    return inv, r


def test_a_reminder_carries_the_company_name_and_address_and_a_way_to_stop(tmp_path):
    ctx = due_ctx(tmp_path)
    with ctx.factory() as s:
        _, r = drafted(s, ctx)
        assert "Rivera Works" in r.body and "10 Elm St, Austin TX 78701" in r.body and "reply to this email and say so" in r.body
        assert "Accounts" not in r.body.split("Thank you,")[1].split("\n")[1]  # signed with the company, not the placeholder word


def test_a_draft_payment_link_is_never_stored_or_shown_to_a_customer(tmp_path):
    ctx = due_ctx(tmp_path)
    with ctx.factory() as s:
        inv = add_customer_invoice(s, ctx, due=date(2025, 11, 1))
        s.add(State(key="force_draft", value="1"))
        s.commit()
        out = collections.create_payment_link(s, ctx, inv.id, "owner")
        s.refresh(inv)
        assert out["real"] is False and out["url"].startswith(collections.DRAFT_LINK_PREFIX) and inv.payment_link_url == ""
        _, body = collections.render(inv, "friendly", datetime(2026, 1, 20, tzinfo=timezone.utc), out["url"], settings=ctx.settings)
        assert collections.DRAFT_LINK_PREFIX not in body


def test_the_kill_switch_in_the_app_holds_every_approved_reminder(tmp_path):
    ctx = due_ctx(tmp_path)
    with ctx.factory() as s:
        _, r = drafted(s, ctx)
        collections.approve_reminder(s, r.id, "owner")
        s.add(State(key="kill_switch", value="1"))
        s.commit()
        out = collections.send_approved(s, ctx)
        assert ctx.adapters.email.sent == [] and out["sent"] == 0


def test_a_reminder_goes_out_once_when_the_switches_are_clear(tmp_path):
    ctx = due_ctx(tmp_path)
    with ctx.factory() as s:
        _, r = drafted(s, ctx)
        collections.approve_reminder(s, r.id, "owner")
        s.commit()
        first, second = collections.send_approved(s, ctx), collections.send_approved(s, ctx)
        assert first["sent"] == 1 and second["sent"] == 0 and len(ctx.adapters.email.sent) == 1


def test_one_refused_message_does_not_stop_the_others_and_the_sent_ones_stay_sent(tmp_path):
    ctx = due_ctx(tmp_path)
    ctx.adapters.email = CountingEmail(fail_for={"bad@customer.test"})
    with ctx.factory() as s:
        _, r1 = drafted(s, ctx, "bad@customer.test", "INV-1")
        _, r2 = drafted(s, ctx, "good@customer.test", "INV-2")
        for r in (r1, r2):
            collections.approve_reminder(s, r.id, "owner")
        s.commit()
        out = collections.send_approved(s, ctx)
        assert out["sent"] == 1 and out["held"] == 1 and [m["to"] for m in ctx.adapters.email.sent] == ["good@customer.test"]
        assert s.get(Reminder, r1.id).status == "approved" and s.get(Reminder, r2.id).status == "sent"


def test_a_reminder_for_a_customer_with_no_valid_address_cannot_be_approved(tmp_path):
    ctx = due_ctx(tmp_path)
    with ctx.factory() as s:
        inv, r = drafted(s, ctx, "a@customer.test", "INV-9")
        inv.customer.email = "not-an-address"  # an address that went bad after the draft was made
        s.flush()
        with pytest.raises(ValueError, match="valid email"):
            collections.approve_reminder(s, r.id, "owner")


def test_only_the_owner_can_clear_an_opt_out(tmp_path):
    from fastapi.testclient import TestClient

    from booklantern.api.app import create_app

    ctx = make_ctx(tmp_path)
    with ctx.factory() as s:
        c = setup_data.create_customer(s, ctx.settings, "t", name="Stopper", email="x@y.test")
        collections.set_opt_out(s, c.id, True, "owner")
        s.commit()
        cid = c.id
    client = TestClient(create_app(ctx.settings, ctx))
    tok = client.post("/api/auth/login", json={"email": "approver@example.test", "password": "demo-password-1"}).json()["token"]
    r = client.post(f"/api/customers/{cid}/opt-out", json={"opted_out": False}, headers={"x-session": tok})
    assert r.status_code == 403
    with ctx.factory() as s:
        assert s.get(Customer, cid).opted_out is True


# ---- files that leave the system ----

@pytest.mark.parametrize("raw", ["=SUM(A1)", "+1", "-1", "@x", "\tx", "\rx"])
def test_a_cell_that_starts_like_a_formula_is_neutralised(raw):
    assert csv_safe(raw) == "'" + raw


def test_an_ordinary_cell_and_an_empty_one_are_left_alone():
    assert csv_safe("Acme") == "Acme" and csv_safe(None) == "" and csv_safe(12) == "12"


def test_accounting_calls_carry_a_repeat_key():
    from booklantern.adapters.base import DraftBill

    d = DraftBill("V", "N", "2026-01-01", "2026-02-01", "USD", idempotency_key="k" * 200)
    assert len(d.idempotency_key) == 200  # the adapters cut it to the width each system allows (50 and 128)


def test_these_tests_run_on_the_pinned_clock_not_the_wall_clock(tmp_path):
    ctx = live_ctx(tmp_path)
    with ctx.factory() as s:
        assert ctx.now(s) == PINNED_NOW and ctx.today(s) == date(2026, 12, 1)
