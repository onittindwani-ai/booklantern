"""Round 3 audit fixes. Each test fails on the code before the fix."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from booklantern import bankcsv, bankservice, intake, money, posting, setup_data
from booklantern.config import Settings
from booklantern.models import BankAccount, BankTransaction, Bill, Customer, ExceptionItem, Invoice, Match, Payment, Vendor
from sendora_core.settings import ConfigError, Mode

from .conftest import make_ctx
from .test_api import approver, client  # noqa: F401  (the fixture)


def _bill(s, ctx, vendor, number, total=5000, bank=None, bill_to=None, status="needs_review", issued=date(2026, 11, 20)):
    b = Bill(vendor_id=vendor.id if vendor else None, vendor_name_read=vendor.name if vendor else "Cobalt Office Supply Holdings Ltd", number=number, issue_date=issued, due_date=date(2026, 12, 20), currency="USD",
             bill_to=bill_to if bill_to is not None else ctx.settings.company_name, bank_account=vendor.bank_account if (bank is None and vendor) else (bank or ""), subtotal_minor=total, total_minor=total, status=status)
    s.add(b)
    s.flush()
    intake.validate_bill(s, ctx, b)
    return b


def _kinds(s, bill_id, status="open"):
    return {e.kind: e.severity for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == bill_id, ExceptionItem.status == status))}


# ---- 1. editing the blocking finding away does not turn off the two person rule ----------------------------------------------------------------------

def _world(client, seeded):
    """A vendor with an account on file and a clean earlier bill from it, in the app's own database."""
    with seeded.factory() as s:
        v = setup_data.create_vendor(s, seeded.settings, "owner", name="Hollis Print Co", bank_account="SMPL-5555-0000")
        first = _bill(s, seeded, v, "HP-0042")
        s.commit()
        return v.id, first.id


@pytest.mark.parametrize("path", ["wrong_company", "bank_details_not_read", "duplicate"])
def test_an_approver_who_edits_the_blocking_finding_away_cannot_approve_alone(client, seeded, path):  # noqa: F811
    vid, first = _world(client, seeded)
    with seeded.factory() as s:
        v = s.get(Vendor, vid)
        if path == "wrong_company":
            b = _bill(s, seeded, v, "HP-0100", bill_to="Someone Else Ltd")
            assert _kinds(s, b.id)["wrong_company"] == "block"
        elif path == "bank_details_not_read":
            b = _bill(s, seeded, v, "HP-0100", bank="")
            assert _kinds(s, b.id)["bank_details_not_read"] == "block"
        else:
            b = _bill(s, seeded, v, "HP-0042")  # the same number and amount as the first bill
            assert _kinds(s, b.id)["duplicate_exact"] == "block"
        bid = b.id
        s.commit()
    ap = approver(client)
    fix = {"wrong_company": {"bill_to": seeded.settings.company_name}, "bank_details_not_read": {"bank_account": "SMPL-5555-0000"}, "duplicate": {"number": "HP-0042X", "total_minor": 5000}}[path]
    assert client.patch(f"/api/bills/{bid}", json=fix, headers=ap).status_code == 200
    d = client.get(f"/api/bills/{bid}", headers=ap).json()
    assert d["had_block"] is True
    assert not any(e["severity"] == "block" and e["status"] == "open" for e in d["exceptions"]) or path == "duplicate"  # the edit really did make the finding go away (a near copy still blocks)
    assert client.post(f"/api/bills/{bid}/approve", json={"note": ""}, headers=ap).status_code == 409
    assert client.post(f"/api/bills/{bid}/approve", json={"note": "I checked it myself and it is fine"}, headers=ap).status_code == 409  # a reason does not let an approver approve their own edit
    assert client.get(f"/api/bills/{bid}", headers=ap).json()["self_review"] == "blocked"


def test_the_owner_who_edits_a_block_away_needs_a_real_reason_and_a_second_person_does_not(client, seeded):  # noqa: F811
    vid, first = _world(client, seeded)
    with seeded.factory() as s:
        b = _bill(s, seeded, s.get(Vendor, vid), "HP-0100", bill_to="Someone Else Ltd")
        bid = b.id
        s.commit()
    assert client.patch(f"/api/bills/{bid}", json={"bill_to": seeded.settings.company_name}).status_code == 200
    assert client.post(f"/api/bills/{bid}/approve", json={"note": ""}).status_code == 409
    assert client.post(f"/api/bills/{bid}/approve", json={"note": "x"}).status_code == 409
    assert client.post(f"/api/bills/{bid}/approve", json={"note": "aaaaaaaaaaaaaaaa"}).status_code == 409
    assert client.post(f"/api/bills/{bid}/approve", json={"note": "Owner checked the page: it was addressed to us"}).status_code == 200
    log = client.get("/api/audit?limit=30").json()
    assert any(a["action"] == "bill.approved" and a["detail"].get("self_review") is True for a in log)


def test_a_bill_that_never_had_a_block_is_still_approved_by_one_person(client, seeded):  # noqa: F811
    vid, first = _world(client, seeded)
    assert client.post(f"/api/bills/{first}/approve", json={"note": ""}, headers=approver(client)).status_code == 200


def test_the_flag_is_kept_by_the_database_and_old_files_get_it(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from booklantern.dbupgrade import add_missing_columns
    from sendora_core.db import Base
    import booklantern.models  # noqa: F401
    from sendora_core import models as _core  # noqa: F401

    url = f"sqlite:///{tmp_path / 'old.sqlite3'}"
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(text("INSERT INTO ll_bill (id, vendor_name_read, number, currency, subtotal_minor, tax_minor, total_minor, paid_minor, status, posted_external_id, edited_by, created_at, po_number, bill_to, bank_account) "
                       "VALUES (1, 'A', 'N1', 'USD', 0, 0, 100, 0, 'needs_review', '', '', '2026-11-01 00:00:00', '', '', '')"))
        c.execute(text("INSERT INTO ll_bill (id, vendor_name_read, number, currency, subtotal_minor, tax_minor, total_minor, paid_minor, status, posted_external_id, edited_by, created_at, po_number, bill_to, bank_account) "
                       "VALUES (2, 'B', 'N2', 'USD', 0, 0, 100, 0, 'needs_review', '', '', '2026-11-01 00:00:00', '', '', '')"))
        c.execute(text("INSERT INTO ll_exception (kind, severity, ref_type, ref_id, detail, status, resolved_by, created_at) VALUES ('wrong_total', 'block', 'bill', 2, '', 'resolved', 'x', '2026-11-01 00:00:00')"))
        c.execute(text("ALTER TABLE ll_bill DROP COLUMN had_block"))  # what a file made before this release looks like
    assert add_missing_columns(create_engine(url)) == ["ll_bill.had_block"]
    with create_engine(url).connect() as c:
        assert dict(c.execute(text("SELECT id, had_block FROM ll_bill")).all()) == {1: 0, 2: 1}  # a bill that already carried a block row keeps that fact
    assert "had_block" in {col["name"] for col in inspect(create_engine(url)).get_columns("ll_bill")}


# ---- 2. a lookalike vendor name hides neither the copy nor the changed account ----------------------------------------------------------------------

def test_a_lookalike_vendor_with_a_copied_bill_and_its_own_account_is_blocked_twice(ctx):
    with ctx.factory() as s:
        v = setup_data.create_vendor(s, ctx.settings, "owner", name="Cobalt Office Supply", bank_account="SMPL-7777-1111")
        real = _bill(s, ctx, v, "COB-5521", total=250_000)
        copy = _bill(s, ctx, None, "COB-5521", total=250_000, bank="SMPL-6666-9999")
        found = _kinds(s, copy.id)
        assert found.get("duplicate_exact") == "block"  # the same number and total, whatever the vendor is called
        assert found.get("unknown_vendor") == "block"  # an unknown vendor that asks to be paid into an account
        assert real.id != copy.id


def test_an_unknown_vendor_without_bank_details_is_still_only_a_warning(ctx):
    with ctx.factory() as s:
        b = _bill(s, ctx, None, "ZZ-1", total=1000, bank="")
        assert _kinds(s, b.id)["unknown_vendor"] == "warning"


def test_two_bills_from_different_listed_vendors_with_the_same_number_are_not_duplicates(ctx):
    with ctx.factory() as s:
        a = setup_data.create_vendor(s, ctx.settings, "owner", name="Alpha Tools", bank_account="SMPL-1")
        b = setup_data.create_vendor(s, ctx.settings, "owner", name="Beta Tools", bank_account="SMPL-2")
        _bill(s, ctx, a, "INV-1", total=1000)
        second = _bill(s, ctx, b, "INV-1", total=1000)
        assert "duplicate_exact" not in _kinds(s, second.id)


def test_a_number_changed_by_a_character_on_the_same_total_blocks(ctx):
    with ctx.factory() as s:
        v = setup_data.create_vendor(s, ctx.settings, "owner", name="Hollis Print Co", bank_account="SMPL-5555-0000")
        _bill(s, ctx, v, "HP-0042")
        again = _bill(s, ctx, v, "HP-0042X")
        assert _kinds(s, again.id)["duplicate_near"] == "block"


def test_the_sender_allow_list_blocks_a_bill_from_anyone_else(tmp_path):
    from pathlib import Path

    c = make_ctx(tmp_path, intake_allowed_senders="billing@vendor.example, @trusted.example")
    root = Path(__file__).resolve().parents[3]
    data = (root / "data/heldout/documents/H001.pdf").read_bytes()
    assert c.settings.sender_allowed("Billing@Vendor.example") and c.settings.sender_allowed("anyone@trusted.example") and not c.settings.sender_allowed("evil@elsewhere.example")
    with c.factory() as s:
        doc = intake.ingest(s, c, "a.pdf", data, "inbox", "evil@elsewhere.example", "invoice")
        bill = intake.process_document(s, c, doc, data)
        assert _kinds(s, bill.id).get("sender_not_allowed") == "block"
        s.commit()
    (tmp_path / "b").mkdir()
    c2 = make_ctx(tmp_path / "b", intake_allowed_senders="")
    with c2.factory() as s:
        doc = intake.ingest(s, c2, "a.pdf", data, "inbox", "evil@elsewhere.example", "invoice")
        assert "sender_not_allowed" not in _kinds(s, intake.process_document(s, c2, doc, data).id)  # empty list: anyone, as before


# ---- 3. one strict money reader: a minus sign is never lost --------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,want", [("\u2212500.00", -50000), ("\u2013500.00", -50000), ("-500.00", -50000), ("(500.00)", -50000), ("500.00-", -50000), ("500.00\u2212", -50000), ("500.00 DR", -50000), ("500.00 CR", 50000),
                                       ("\u2212 1,234.50", -123450), ("500", 50000), ("1.234,50", 123450)])
def test_the_bank_reader_keeps_the_sign_in_every_form(text, want):
    assert money.parse_amount(text, "USD", debit_credit=True)[0] == want


@pytest.mark.parametrize("text", ["500.00 DR", "500.00 CR", "12 abc", "--5", "-5 DR", "(5)-", "5.00 USD EUR", "∞", "5\u2212\u2212", "1 2", "()", "-", ""])
def test_anything_unclear_is_not_an_amount(text):
    assert money.parse_amount(text, "USD") is None


def test_the_bill_reader_keeps_a_minus_written_as_a_dash():
    from booklantern.extraction import numbers as N

    for line in ("Credit \u2013250.00", "Credit \u2212250.00", "Credit -250.00", "Total 250.00\u2013", "Total 250.00\u2212"):
        assert N.money_tokens(line)[0][2] == -25000, line  # the en dash used to be skipped and the credit read as a charge
    assert N.parse_money("\u2013250.00") == -25000 and N.parse_money("1\u00a0234,50") == 123450
    assert N.money_tokens("Period 1\u201330") == [] and N.money_tokens("Ref 12-30") == []  # a dash between two numbers is a range, not a minus


def test_a_statement_line_with_a_real_minus_sign_is_money_out(tmp_path):
    c = make_ctx(tmp_path)
    csv_text = "Date,Description,Amount\n2026-11-01,RENT,\u2212500.00\n2026-11-02,FEE,\u2013 12.50\n2026-11-03,SUPPLIER,40.00 DR\n2026-11-04,REFUND,15.00 CR\n2026-11-05,CARD,(7.00)\n"
    with c.factory() as s:
        s.add(BankAccount(name="Main", currency="USD", opening_minor=0, opening_date=date(2026, 1, 1)))
        s.flush()
        assert bankservice.import_csv(s, csv_text, "t")["added"] == 5
        amounts = {t.description: t.amount_minor for t in s.scalars(select(BankTransaction))}
    assert amounts == {"RENT": -50000, "FEE": -1250, "SUPPLIER": -4000, "REFUND": 1500, "CARD": -700}


def test_an_unreadable_amount_stops_the_import_and_every_bad_line_is_listed(tmp_path):
    c = make_ctx(tmp_path)
    csv_text = "Date,Description,Amount\n2026-11-01,GOOD,10.00\n2026-11-02,ODD,12x5\n2026-11-03,TWO,--4\n2026-11-04,BADDATE,5.00\n"
    csv_text = csv_text.replace("BADDATE,5.00", "BADDATE,5.00").replace("2026-11-04", "04/11/2026")
    with c.factory() as s:
        s.add(BankAccount(name="Main", currency="USD", opening_minor=0, opening_date=date(2026, 1, 1)))
        s.flush()
        with pytest.raises(bankcsv.CsvError) as e:
            bankservice.import_csv(s, csv_text, "t")
        assert len(e.value.lines) == 3 and "Line 3" in str(e.value) and "Line 4" in str(e.value) and "Line 5" in str(e.value) and "Nothing was imported" in str(e.value)
        assert s.scalars(select(BankTransaction)).first() is None  # not even the good line


def test_the_statement_must_say_which_account_when_there_is_more_than_one(tmp_path):
    c = make_ctx(tmp_path)
    csv_text = "Date,Description,Amount\n2026-11-01,X,10.00\n"
    with c.factory() as s:
        a = BankAccount(name="Main", currency="USD", opening_minor=0, opening_date=date(2026, 1, 1))
        b = BankAccount(name="Savings", currency="USD", opening_minor=0, opening_date=date(2026, 1, 1))
        s.add_all([a, b])
        s.flush()
        with pytest.raises(bankcsv.CsvError, match="more than one bank account"):
            bankservice.import_csv(s, csv_text, "t")
        assert bankservice.import_csv(s, csv_text, "t", b.id)["added"] == 1
        assert s.scalars(select(BankTransaction)).first().bank_account_id == b.id
        with pytest.raises(bankcsv.CsvError, match="no bank account with the number"):
            bankservice.import_csv(s, csv_text, "t", 99)


# ---- 4. a customer's stop reply is not marked read, and a person is shown it ------------------------------------------------------------------------

def _imap_settings(srv, **kw):
    return Settings(_env_file=None, session_secret="x" * 40, demo_mode=False, owner_password_hash="x", imap_host=srv.host, imap_port=srv.imap_port, imap_use_ssl=False, smtp_user="demo", smtp_password="demo-password",
                    smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, mode=Mode.LIVE, company_name="Rivera Works", **kw)


def _mail(sender, subject, body, attach=False):
    from email.message import EmailMessage

    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "ap@us.example.test", subject
    m.set_content(body)
    if attach:
        m.add_attachment(b"%PDF-1.4 stub", maintype="application", subtype="pdf", filename="inv.pdf")
    return m.as_bytes()


def test_mail_with_no_bill_stays_unread_and_is_handed_over_once():
    from booklantern.adapters.imap import ImapInbox
    from mock.mail_servers import StubMailServers

    with StubMailServers() as srv:
        srv.store.deliver(_mail("cust@marlowe.example.test", "Re: Reminder", "Please stop sending these reminders."))
        srv.store.deliver(_mail("vendor@x.example.test", "Invoice", "attached", attach=True))
        box = ImapInbox(_imap_settings(srv))
        docs = box.fetch_documents()
        assert [d.file_name for d in docs] == ["inv.pdf"]
        assert [m["seen"] for m in srv.store.inbox] == [False, False]  # the stop reply was not marked read (it used to be, on the first poll)
        notes = box.take_notes()
        assert [(n.from_addr, n.subject) for n in notes] == [("cust@marlowe.example.test", "Re: Reminder")] and "stop sending" in notes[0].snippet
        assert box.fetch_documents() and box.take_notes() == []  # not fetched and not handed over again (the bill was not acknowledged, so it comes again)
        box.acknowledge([d.ack for d in docs])
        assert [m["seen"] for m in srv.store.inbox] == [False, True]


def test_a_stop_reply_from_a_customer_shows_up_as_an_exception_for_a_person(tmp_path):
    from booklantern.adapters.imap import ImapInbox
    from mock.mail_servers import StubMailServers

    with StubMailServers() as srv:
        c = make_ctx(tmp_path)
        c.adapters.inbox = ImapInbox(_imap_settings(srv))
        with c.factory() as s:
            cust = setup_data.create_customer(s, c.settings, "owner", name="Marlowe Bakery", email="cust@marlowe.example.test")
            s.commit()
            cid = cust.id
        srv.store.deliver(_mail("cust@marlowe.example.test", "Re: Reminder", "Please STOP these emails."))
        srv.store.deliver(_mail("stranger@elsewhere.example.test", "Unsubscribe me", "remove me from your list"))
        srv.store.deliver(_mail("newsletter@shop.example.test", "Sale", "big sale today"))
        with c.factory() as s:
            intake.run_intake(s, c)
            s.commit()
            rows = {(e.kind, e.ref_type): e for e in s.scalars(select(ExceptionItem))}
        assert ("stop_reply", "customer") in rows and rows[("stop_reply", "customer")].ref_id == cid
        assert any(k == "stop_reply" and t == "mail" for k, t in rows)  # a stop request from an address that is no customer is shown too
        assert not any("newsletter" in e.detail for e in rows.values())  # ordinary mail is left alone
        assert all(m["seen"] is False for m in srv.store.inbox)


def test_an_empty_reply_to_with_one_mailbox_for_both_is_a_live_mode_problem():
    base = dict(_env_file=None, session_secret="x" * 40, demo_mode=False, owner_password_hash="x", company_name="Rivera Works", company_address="1 Main Street, Springfield", email_from="accounts@rivera.example",
                inbox_adapter="imap", email_adapter="smtp", imap_host="imap.example", smtp_host="smtp.example", smtp_user="bills@rivera.example", smtp_password="x")
    assert any("REPLY_TO" in p for p in Settings(mode=Mode.LIVE, **base).runtime_errors())
    assert any("REPLY_TO" in p for p in Settings(mode=Mode.LIVE, reply_to="bills@rivera.example", **base).runtime_errors())  # the bills mailbox itself
    assert not any("REPLY_TO" in p for p in Settings(mode=Mode.LIVE, reply_to="ap@rivera.example", **base).runtime_errors())
    assert any("REPLY_TO" in p for p in Settings(mode=Mode.DRAFT, **base).problems())  # draft mode lists it but sends nothing


# ---- 5. a demo (no owner password) cannot hold real connections or real writes -----------------------------------------------------------------------

def test_a_start_with_no_demo_mode_line_cannot_hold_quickbooks_smtp_and_writes():
    s = Settings(_env_file=None, mode=Mode.LIVE, accounting_adapter="quickbooks", email_adapter="smtp", accounting_write=True, qbo_client_id="a", qbo_client_secret="b", qbo_refresh_token="c", qbo_realm_id="d")
    assert s.demo_mode is True and s.demo_shortcuts  # the base default: nothing says DEMO_MODE
    with pytest.raises(ConfigError, match="DEMO_MODE"):
        s.check_runtime()
    msgs = " ".join(s.runtime_errors())
    assert "ACCOUNTING_ADAPTER=quickbooks" in msgs and "EMAIL_ADAPTER=smtp" in msgs and "ACCOUNTING_WRITE=true" in msgs


def test_the_offline_demo_and_the_owners_own_choice_still_start():
    Settings(_env_file=None, mode=Mode.LIVE).check_runtime()  # offline adapters, nothing written: the browser tests run like this
    Settings(_env_file=None, mode=Mode.LIVE, accounting_adapter="quickbooks", accounting_write=True, allow_demo_server=True).check_runtime()  # a written choice for a throw away trial
    real = Settings(_env_file=None, mode=Mode.LIVE, accounting_adapter="quickbooks", accounting_write=True, demo_mode=False, owner_password_hash="x", session_secret="q" * 40, company_name="Rivera Works")
    assert not any("DEMO_MODE is true" in p for p in real.runtime_errors())


def test_the_container_image_starts_with_the_demo_off():
    from pathlib import Path

    assert "DEMO_MODE=false" in (Path(__file__).resolve().parents[3] / "apps/api/Dockerfile").read_text()


# ---- 6. a later deposit pays the invoice that is still open ---------------------------------------------------------------------------------------

def _bank_ctx(tmp_path):
    c = make_ctx(tmp_path)
    with c.factory() as s:
        s.add(BankAccount(name="Main", currency="USD", opening_minor=0, opening_date=date(2026, 1, 1)))
        cust = setup_data.create_customer(s, c.settings, "owner", name="Marlowe Bakery", email="a@marlowe.example.test")
        s.commit()
        return c, cust.id


def _invoice(s, cust_id, number, total, paid=0, status=None, issued=date(2026, 10, 1), paid_on=None):
    inv = Invoice(customer_id=cust_id, number=number, issue_date=issued, due_date=date(2026, 10, 31), currency="USD", total_minor=total, paid_minor=paid,
                  status=status or ("paid" if paid >= total else "open"), paid_on=paid_on)
    s.add(inv)
    s.flush()
    return inv


def test_a_later_deposit_pays_the_open_invoice_not_the_one_already_paid(tmp_path):
    c, cust = _bank_ctx(tmp_path)
    with c.factory() as s:
        old = _invoice(s, cust, "INV-1", 100_000, paid=100_000, status="paid", paid_on=date(2026, 10, 20))
        new = _invoice(s, cust, "INV-2", 100_000, issued=date(2026, 10, 2))
        s.add(BankTransaction(bank_account_id=1, ref="a", posted_on=date(2026, 11, 20), description="ACH CREDIT MARLOWE BAKERY", amount_minor=100_000, currency="USD", row_hash="h1"))
        s.flush()
        bankservice.run_matching(s, c)
        bankservice.record_payments(s)
        m = s.scalars(select(Match)).one()
        assert m.invoice_id == new.id and m.invoice_id != old.id
        s.refresh(new)
        assert new.status == "paid" and new.paid_minor == 100_000 and new.paid_on == date(2026, 11, 20)  # the real open invoice is paid, with the real date


def test_a_part_paid_imported_invoice_offers_only_what_is_owed_and_ends_paid(tmp_path):
    c, cust = _bank_ctx(tmp_path)
    with c.factory() as s:
        inv = _invoice(s, cust, "INV-9", 100_000, paid=40_000)
        s.add(BankTransaction(bank_account_id=1, ref="a", posted_on=date(2026, 11, 20), description="ACH CREDIT MARLOWE BAKERY INV-9", amount_minor=60_000, currency="USD", row_hash="h1"))
        s.flush()
        bankservice.run_matching(s, c)
        bankservice.record_payments(s)
        m = s.scalars(select(Match)).one()
        assert m.allocated_minor == 60_000 and m.status == "confirmed"  # the open amount was 600.00, not the whole 1,000.00
        s.refresh(inv)
        assert (inv.status, inv.paid_minor, inv.paid_on) == ("paid", 100_000, date(2026, 11, 20))  # 400 already paid and 600 now, not 600 in all


def test_taking_a_match_back_reopens_only_what_that_payment_paid(tmp_path):
    c, cust = _bank_ctx(tmp_path)
    with c.factory() as s:
        inv = _invoice(s, cust, "INV-9", 100_000, paid=40_000)
        s.add(BankTransaction(bank_account_id=1, ref="a", posted_on=date(2026, 11, 20), description="ACH CREDIT MARLOWE BAKERY INV-9", amount_minor=60_000, currency="USD", row_hash="h1"))
        s.flush()
        bankservice.run_matching(s, c)
        bankservice.record_payments(s)
        bankservice.unlink(s, s.scalars(select(Match)).one().id, "owner")
        s.refresh(inv)
        assert (inv.status, inv.paid_minor, inv.paid_on) == ("open", 40_000, None)  # the 400 that came with the import stays
        assert s.scalars(select(Payment)).first() is None


def test_an_invoice_already_marked_paid_keeps_its_date_when_a_line_is_linked_to_it(tmp_path):
    c, cust = _bank_ctx(tmp_path)
    with c.factory() as s:
        inv = _invoice(s, cust, "INV-1", 100_000, paid=100_000, status="paid", paid_on=date(2026, 10, 20))
        s.add(BankTransaction(bank_account_id=1, ref="a", posted_on=date(2026, 11, 20), description="ACH CREDIT MARLOWE BAKERY INV-1", amount_minor=100_000, currency="USD", row_hash="h1"))
        s.flush()
        bankservice.run_matching(s, c)
        bankservice.record_payments(s)
        s.refresh(inv)
        assert (inv.status, inv.paid_minor, inv.paid_on) == ("paid", 100_000, date(2026, 10, 20))
        bankservice.unlink(s, s.scalars(select(Match)).one().id, "owner")
        s.refresh(inv)
        assert (inv.status, inv.paid_minor) == ("paid", 100_000)  # linking and unlinking a settled invoice changes nothing about it


# ---- 7. a mail that may have gone is never sent twice -----------------------------------------------------------------------------------------------

@pytest.fixture()
def noon(monkeypatch):
    """A weekday at 09:00 in New York, so the reminder window is open whatever time the test runs."""
    from datetime import UTC, datetime

    monkeypatch.setattr("booklantern.clock.now", lambda session, demo: datetime(2026, 12, 1, 14, 0, tzinfo=UTC))


def _reminder_world(tmp_path, srv, **kw):
    from booklantern.adapters.imap import SmtpSender
    from booklantern.models import Reminder

    c = make_ctx(tmp_path, mode=Mode.LIVE, smtp_user="demo", smtp_password="demo-password", smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, email_adapter="smtp", demo_mode=False, owner_password_hash="x",
                 company_name="Rivera Works", company_address="1 Main Street, Springfield", email_from="accounts@rivera.example", **kw)
    c.adapters.email = SmtpSender(c.settings)
    with c.factory() as s:
        cust = setup_data.create_customer(s, c.settings, "owner", name="Marlowe Bakery", email="a@marlowe.example.test")
        inv = _invoice(s, cust.id, "INV-1", 100_000)
        r = Reminder(invoice_id=inv.id, step=1, tone="friendly", status="approved", scheduled_for=c.now(s), subject="s", body="b")
        s.add(r)
        s.commit()
        return c, r.id


def _send(c):
    from booklantern import collections

    with c.factory() as s:
        out = collections.send_approved(s, c)
        s.commit()
        return out


def _status(c, rid):
    from booklantern.models import Reminder

    with c.factory() as s:
        r = s.get(Reminder, rid)
        return r.status, r.cancel_reason


def test_a_connection_that_drops_after_the_text_was_handed_over_is_never_sent_again(tmp_path, noon):
    from mock.mail_servers import StubMailServers

    with StubMailServers() as srv:
        srv.store.drop_after_data = True  # the server keeps the mail and the line goes dead before it answers
        c, rid = _reminder_world(tmp_path, srv)
        assert _send(c)["unconfirmed"] == 1
        assert _status(c, rid)[0] == "sending" and len(srv.store.outbox) == 1
        srv.store.drop_after_data = False
        _send(c)
        _send(c)
        assert len(srv.store.outbox) == 1 and _status(c, rid)[0] == "sending"  # not sent again, and a person is told
        with c.factory() as s:
            assert s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "reminder_unconfirmed")).first() is not None


def test_a_failure_while_saying_goodbye_after_the_server_accepted_the_mail_still_counts_as_sent(tmp_path, noon):
    from mock.mail_servers import StubMailServers

    with StubMailServers() as srv:
        srv.store.quit_reply = "500 go away"
        c, rid = _reminder_world(tmp_path, srv)
        assert _send(c)["sent"] == 1
        assert _status(c, rid)[0] == "sent" and len(srv.store.outbox) == 1


def test_a_refused_address_is_one_try_not_a_retry_loop(tmp_path, noon):
    from mock.mail_servers import StubMailServers

    with StubMailServers() as srv:
        srv.store.rcpt_reply = "550 no such user"
        c, rid = _reminder_world(tmp_path, srv)
        assert _send(c)["cancelled"] == 1
        assert _status(c, rid) == ("cancelled", "mail_server_refused") and srv.store.outbox == []
        _send(c)
        assert srv.store.outbox == []
        with c.factory() as s:
            assert s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "reminder_refused")).first() is not None


def test_a_server_that_keeps_failing_is_given_up_on_after_five_tries(tmp_path, noon):
    from mock.mail_servers import StubMailServers

    with StubMailServers() as srv:
        srv.store.rcpt_reply = "450 mailbox busy"  # a temporary refusal: fine to try again
        c, rid = _reminder_world(tmp_path, srv)
        for _ in range(4):
            _send(c)
            assert _status(c, rid)[0] == "approved"
        _send(c)
        assert _status(c, rid) == ("cancelled", "send_failed_repeatedly")


# ---- 8. posting: an unclear outcome is not retried when the accounting system cannot recognise a repeat -------------------------------------------------

class _Flaky:
    """An accounting adapter that times out after the request went out. It has no idempotency key unless `keyed`."""

    def __init__(self, keyed):
        self.calls = 0
        if keyed:
            self.carries_idempotency_key = True

    def create_draft_bill(self, bill):
        import httpx

        self.calls += 1
        raise httpx.ReadTimeout("slow")

    def healthcheck(self):
        return True, ""


def _approved(tmp_path, adapter):
    c = make_ctx(tmp_path, mode=Mode.LIVE, accounting_write=True)
    c.adapters.accounting = adapter
    with c.factory() as s:
        v = setup_data.create_vendor(s, c.settings, "owner", name="Hollis Print Co", bank_account="SMPL-1")
        b = _bill(s, c, v, "HP-1", status="approved")
        s.commit()
        return c, b.id


def test_an_unclear_post_to_an_adapter_with_no_key_stays_unknown_until_a_person_resolves_it(tmp_path):
    c, bid = _approved(tmp_path, _Flaky(keyed=False))
    with c.factory() as s:
        r = posting.post_draft(s, c, bid, "owner")
        s.commit()
        assert r["posted"] is False and "will not post this bill again" in r["reason"] and "never a second one" not in r["reason"]
        assert s.get(Bill, bid).status == "posting" and _kinds(s, bid)["post_outcome_unknown"] == "block"
        with pytest.raises(ValueError, match="Only an approved bill"):
            posting.post_draft(s, c, bid, "owner")  # nothing is posted again by itself
    assert c.adapters.accounting.calls == 1
    with c.factory() as s:
        with pytest.raises(ValueError, match="real reason|Say what"):
            posting.resolve_unknown_post(s, bid, "owner", False, "", "no")
        with pytest.raises(ValueError, match="id the accounting system gave"):
            posting.resolve_unknown_post(s, bid, "owner", True, "", "Looked in the books, it is there")
        posting.resolve_unknown_post(s, bid, "owner", True, "BILL-77", "Looked in the books, it is there")
        s.commit()
        b = s.get(Bill, bid)
        assert (b.status, b.posted_external_id) == ("posted_draft", "BILL-77") and "post_outcome_unknown" not in _kinds(s, bid)


def test_an_unclear_post_that_was_not_made_goes_back_to_approved_on_the_owners_word(tmp_path):
    c, bid = _approved(tmp_path, _Flaky(keyed=False))
    with c.factory() as s:
        posting.post_draft(s, c, bid, "owner")
        s.commit()
        posting.resolve_unknown_post(s, bid, "owner", False, "", "Looked in the books, nothing there")
        assert s.get(Bill, bid).status == "approved"
        with pytest.raises(ValueError, match="no unclear posting"):
            posting.resolve_unknown_post(s, bid, "owner", False, "", "Looked in the books, nothing there")


def test_an_adapter_that_carries_a_key_may_be_tried_again_and_says_so(tmp_path):
    c, bid = _approved(tmp_path, _Flaky(keyed=True))
    with c.factory() as s:
        r = posting.post_draft(s, c, bid, "owner")
        assert r["posted"] is False and "never a second one" in r["reason"]
        assert s.get(Bill, bid).status == "approved" and "post_outcome_unknown" not in _kinds(s, bid)


def test_a_refused_connection_never_sent_anything_so_it_is_not_unclear(tmp_path):
    import httpx

    class Refused(_Flaky):
        def create_draft_bill(self, bill):
            self.calls += 1
            raise httpx.ConnectError("refused")

    c, bid = _approved(tmp_path, Refused(keyed=False))
    with c.factory() as s:
        r = posting.post_draft(s, c, bid, "owner")
        assert r["posted"] is False and "Nothing was sent" in r["reason"] and s.get(Bill, bid).status == "approved"


def test_the_post_outcome_route_needs_a_real_reason(client, seeded):  # noqa: F811
    with seeded.factory() as s:
        v = setup_data.create_vendor(s, seeded.settings, "owner", name="Hollis Print Co", bank_account="SMPL-1")
        b = _bill(s, seeded, v, "HP-1", status="posting")
        from booklantern.exceptions import raise_exception
        raise_exception(s, posting.UNKNOWN_POST, "block", "bill", b.id, "unclear")
        s.commit()
        bid = b.id
    assert client.post(f"/api/bills/{bid}/post-outcome", json={"posted": False, "note": "ok"}).status_code == 409
    r = client.post(f"/api/bills/{bid}/post-outcome", json={"posted": False, "note": "Looked in the books, nothing there"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.post("/api/bills/99999/post-outcome", json={"posted": False, "note": "Looked in the books, nothing there"}).status_code == 404


# ---- Lows ----------------------------------------------------------------------------------------------------------------------------------------------

def test_a_bill_that_changed_after_the_page_loaded_it_is_not_approved_unseen(client, seeded):  # noqa: F811
    vid, first = _world(client, seeded)
    tag = client.get(f"/api/bills/{first}").json()["etag"]
    assert client.get(f"/api/bills/{first}").json()["etag"] == tag  # the same bill gives the same tag
    assert client.patch(f"/api/bills/{first}", json={"po_number": "PO-1234"}, headers=approver(client)).status_code == 200
    r = client.post(f"/api/bills/{first}/approve", json={"note": "", "etag": tag})
    assert r.status_code == 409 and "changed after you opened it" in r.json()["error"]["message"]
    fresh = client.get(f"/api/bills/{first}").json()["etag"]
    assert fresh != tag
    assert client.post(f"/api/bills/{first}/approve", json={"note": "", "etag": fresh}).status_code == 200


def test_a_vendors_changed_account_sends_an_approved_bill_back_to_review(client, seeded):  # noqa: F811
    vid, first = _world(client, seeded)
    assert client.post(f"/api/bills/{first}/approve", json={"note": ""}).status_code == 200
    r = client.patch(f"/api/vendors/{vid}", json={"bank_account": "SMPL-9999-9999"})
    assert r.status_code == 200 and r.json()["sent_back_for_review"] == [first]
    d = client.get(f"/api/bills/{first}").json()
    assert d["status"] == "needs_review" and any(e["kind"] == "bank_detail_changed" and e["status"] == "open" for e in d["exceptions"])
    assert client.patch(f"/api/vendors/{vid}", json={"terms_days": 45}).json()["sent_back_for_review"] == []  # a field the checks do not use changes nothing


def test_an_imported_paid_invoice_keeps_no_made_up_payment_date(ctx):
    with ctx.factory() as s:
        setup_data.create_customer(s, ctx.settings, "owner", name="Marlowe Bakery", email="a@marlowe.example.test")
        setup_data.import_invoices(s, ctx.settings, "owner", "number,customer,issue_date,due_date,total,paid,paid_on\nA-1,Marlowe Bakery,2026-10-01,2026-10-31,100.00,100.00,2026-11-05\nA-2,Marlowe Bakery,2026-10-01,2026-10-31,100.00,100.00,\n")
        got = {i.number: i.paid_on for i in s.scalars(select(Invoice))}
        assert got == {"A-1": date(2026, 11, 5), "A-2": None}  # the second used to be given its issue date, which made its customer look 30 days early


def test_a_reason_must_say_something():
    for bad in ("", " ", "x", "ok", "aaaaaaaaaaaaaaaa", "ok ok ok ok ok ok", "............", "a a a a a a a a"):
        assert posting.real_reason(bad) is False, bad
    for good in ("Phoned the vendor", "Vendor confirmed the total by phone"):
        assert posting.real_reason(good) is True, good


def test_a_blocking_finding_is_closed_only_with_a_real_reason(client, seeded):  # noqa: F811
    vid, first = _world(client, seeded)
    with seeded.factory() as s:
        b = _bill(s, seeded, s.get(Vendor, vid), "HP-0100", bill_to="Someone Else Ltd")
        bid = b.id
        s.commit()
    row = next(e for e in client.get(f"/api/bills/{bid}").json()["exceptions"] if e["kind"] == "wrong_company")
    assert client.post(f"/api/exceptions/{row['id']}/resolve", json={"note": "fine"}).status_code == 409
    assert client.post(f"/api/exceptions/{row['id']}/resolve", json={"note": "Checked the page, it is our old trading name"}).status_code == 200


def test_the_counts_file_is_checked_against_what_can_be_measured():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("check_docs", root / "tools/check_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.count_problems({"tables": 1, "api_paths": 1, "api_operations": 1, "e2e": {"tests": 1}, "tests": {"passed": 1}})  # a stale file is reported
    import json

    assert mod.count_problems(json.loads((root / "data/counts.json").read_text())) == []


def test_the_web_app_sends_a_content_security_policy():
    from pathlib import Path

    cfg = (Path(__file__).resolve().parents[3] / "apps/web/next.config.ts").read_text()
    assert "Content-Security-Policy" in cfg and "frame-ancestors 'none'" in cfg and "object-src 'none'" in cfg and "default-src 'self'" in cfg


# ---- the save happens before the answer is sent (FastAPI 0.165 runs a default scope dependency's exit after the body has gone out)
def test_every_route_asks_for_its_session_with_the_function_scope():
    import re
    from pathlib import Path

    bare = []
    for f in (Path(__file__).resolve().parents[1] / "src" / "booklantern" / "api").glob("*.py"):
        bare += [f.name for _ in re.finditer(r"Depends\(db\)", f.read_text())]
    assert bare == []  # `Depends(db)` saves AFTER the answer has gone out: a failed save would still read "ok"


def test_a_change_that_cannot_be_saved_is_an_error_not_a_success_message(client, seeded):  # noqa: F811
    from fastapi.testclient import TestClient
    from sqlalchemy import event

    bill = next(b for b in client.get("/api/bills?status=needs_review").json())
    quiet = TestClient(client.app, raise_server_exceptions=False)
    state = {"on": True}

    def boom(session):
        if state["on"]:
            raise RuntimeError("disk full")

    event.listen(seeded.factory, "before_commit", boom)
    r = quiet.post(f"/api/bills/{bill['id']}/reject", headers={"x-session": client.owner_token}, json={"reason": "Not one of ours, wrong company."})
    state["on"] = False
    event.remove(seeded.factory, "before_commit", boom)
    assert r.status_code == 500  # before the fix the 200 went out first and the save failed afterwards
    with seeded.factory() as s:
        assert s.get(Bill, bill["id"]).status == "needs_review"


def test_the_claim_to_post_is_saved_before_the_accounting_system_is_asked(tmp_path):
    seen = {}

    class Watcher(_Flaky):
        def create_draft_bill(self, bill):
            with c.factory() as other:  # a second connection sees only what is already saved
                seen["status"] = other.get(Bill, bid).status
            return "BILL-9"

    c, bid = _approved(tmp_path, Watcher(keyed=True))
    with c.factory() as s:
        posting.post_draft(s, c, bid, "owner")
    assert seen["status"] == "posting"  # before the fix the claim was only pending in the request's session


def test_a_deposit_that_fits_only_a_paid_invoice_is_suggested_not_confirmed_unless_it_names_the_number():
    from datetime import date as d

    from booklantern.reconcile import Target, Txn, match_all

    paid = Target("invoice", 1, "INV-77", "Northfield Dental", 100_000, d(2026, 9, 1), d(2026, 10, 1), settled=True)
    bare = Txn(1, d(2026, 11, 20), "DEPOSIT NORTHFIELD DENTAL", 100_000)
    named = Txn(2, d(2026, 11, 20), "DEPOSIT NORTHFIELD DENTAL INV-77", 100_000)
    one, two = match_all([bare], [paid], [])[0], match_all([named], [paid], [])[0]
    assert one.outcome == "suggested" and "a person confirms" in one.links[0].reason  # a repeat deposit with no number is looked at by a person
    assert two.outcome == "matched"  # a statement line that names the number of an old payment still confirms
