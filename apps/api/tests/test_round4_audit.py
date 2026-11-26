"""Round 4 audit: money read in the right currency, bank lines kept per account and counted from the opening date, bills that are not lost to a signature image, unknown currencies held,
matching that does not pay the wrong invoice, and a bill that cannot get stuck in "posting"."""

from datetime import date, timedelta
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import select

from booklantern import bankcsv, bankservice, intake, jobs, posting, reconcile as RC, setup_data
from booklantern.adapters.imap import ImapInbox
from booklantern.api.app import create_app
from booklantern.exceptions import raise_exception, resolve
from booklantern.extraction import offline
from booklantern.extraction.numbers import to_minor_units
from booklantern.models import BankAccount, BankTransaction, Bill, ExceptionItem, Invoice
from booklantern.money import parse_amount
from mock.mail_servers import StubMailServers
from sendora_core.audit import record_audit

from .test_hardening_intake import bill_pdf, imap_settings, pdf


# ---- 1. the amount reader knows the currency's decimals ----

EXP3 = ["KWD", "BHD", "OMR", "JOD", "TND"]


@pytest.mark.parametrize("cur", EXP3)
@pytest.mark.parametrize("text,minor", [("12.345", 12345), ("12,345", 12345), ("-12.345", -12345), ("(12,345)", -12345), ("0.500", 500), ("1,234.567", 1234567), ("1.234,567", 1234567), ("1,234,567", 1234567000)])
def test_a_currency_with_three_decimals_reads_a_single_separator_as_decimal(cur, text, minor):
    assert parse_amount(text, cur) == (minor, cur)


def test_a_two_decimal_and_a_no_decimal_currency_still_read_three_digits_as_thousands():
    assert parse_amount("12,345", "USD") == (1234500, "USD")
    assert parse_amount("12.345", "EUR") == (1234500, "EUR")
    assert parse_amount("12,345", "JPY") == (12345, "JPY")
    assert parse_amount("12.345", "JPY") == (12345, "JPY")


def test_an_amount_that_could_be_thousands_or_decimals_with_no_currency_is_refused():
    assert parse_amount("12,345") is None and parse_amount("-12.345") is None
    assert parse_amount("12,345.00") == (1234500, "USD") and parse_amount("12,50") == (1250, "USD")  # nothing ambiguous about these
    assert parse_amount("12,345 KWD") == (12345, "KWD") and parse_amount("$12,345") == (1234500, "USD")  # the code or the symbol says what it is


@pytest.mark.parametrize("cur,line,minor", [("KWD", "-12.345", -12345), ("BHD", "12,345", 12345), ("OMR", "7.500", 7500)])
def test_a_bank_statement_in_a_three_decimal_currency_imports_the_right_amount(ctx, cur, line, minor):
    rows = bankcsv.parse(f'Date,Description,Amount\n2026-03-01,RENT,"{line}"\n', cur)
    assert rows[0].amount_minor == minor and rows[0].currency == cur
    with ctx.factory() as s:
        s.add(BankAccount(name="Gulf", currency=cur, opening_minor=0, opening_date=date(2026, 1, 1)))
        s.flush()
        bankservice.import_csv(s, f'Date,Description,Amount\n2026-03-01,RENT,"{line}"\n', "b")
        assert bankservice.balance(s) == minor


def test_an_open_invoice_import_in_kuwaiti_dinar_keeps_three_decimals(ctx):
    with ctx.factory() as s:
        setup_data.import_customers(s, ctx.settings, "t", "name\nAl Noor Trading\n")
        setup_data.import_invoices(s, ctx.settings, "t", "number,customer,issue_date,due_date,total,currency\nK-1,Al Noor Trading,2026-03-01,2026-03-31,12.345,KWD\nK-2,Al Noor Trading,2026-03-01,2026-03-31,\"1,234.500\",KWD\n")
        got = {i.number: i.total_minor for i in s.scalars(select(Invoice))}
        assert got == {"K-1": 12345, "K-2": 1234500}


def test_the_bill_reader_reads_a_three_decimal_total_as_decimals():
    assert to_minor_units("12.345", 3) == 12345 and to_minor_units("12,345", 3) == 12345 and to_minor_units("1,234,567", 3) == 1234567000
    assert to_minor_units("12.345", 2) == 1234500 and to_minor_units("12.345", 0) == 12345


# ---- 2. the same line in two accounts ----

def two_accounts(s, cur="USD"):
    a = BankAccount(name="Operating", currency=cur, opening_minor=0, opening_date=date(2026, 1, 1))
    b = BankAccount(name="Savings", currency=cur, opening_minor=0, opening_date=date(2026, 1, 1))
    s.add_all([a, b])
    s.flush()
    return a, b


FEE = "Date,Description,Amount\n2026-03-01,TRANSFER FEE,-25.00\n"


def test_an_identical_line_in_a_second_account_is_imported_and_counted(ctx):
    with ctx.factory() as s:
        a, b = two_accounts(s)
        assert bankservice.import_csv(s, FEE, "a", a.id)["added"] == 1
        assert bankservice.import_csv(s, FEE, "b", b.id) == {"added": 1, "skipped_already_imported": 0, "possible_duplicates": 0}
        assert bankservice.balance(s, a.id) == -2500 and bankservice.balance(s, b.id) == -2500
        assert bankservice.import_csv(s, FEE, "again", a.id)["skipped_already_imported"] == 1 and s.query(BankTransaction).count() == 2  # the same file into the same account still adds nothing


def test_a_line_imported_before_the_account_was_part_of_the_hash_is_still_recognised_and_re_keyed(ctx):
    with ctx.factory() as s:
        a, b = two_accounts(s)
        old = bankcsv.parse(FEE)[0]  # no account number: the key an earlier version stored
        s.add(BankTransaction(bank_account_id=a.id, ref=old.ref, posted_on=old.posted_on, description=old.description, amount_minor=old.amount_minor, currency="USD", row_hash=old.row_hash, batch="old"))
        s.flush()
        assert bankservice.import_csv(s, FEE, "again", a.id) == {"added": 0, "skipped_already_imported": 1, "possible_duplicates": 0}
        assert s.scalars(select(BankTransaction.row_hash)).first() == bankcsv.parse(FEE, "USD", a.id)[0].row_hash  # re-keyed, so the next account is not blocked by it
        assert bankservice.import_csv(s, FEE, "other account", b.id)["added"] == 1


# ---- 3. the opening balance counts from its date ----

def test_lines_before_the_opening_date_do_not_count_in_the_balance_and_the_import_says_so(ctx):
    csv_text = "Date,Description,Amount\n2026-02-20,OLD RENT,-5000.00\n2026-02-28,OLD SALE,3000.00\n2026-03-01,FEE,-25.00\n2026-03-05,SALE,100.00\n"
    with ctx.factory() as s:
        s.add(BankAccount(name="Operating", currency="USD", opening_minor=1_000_000, opening_date=date(2026, 3, 1)))
        s.flush()
        r = bankservice.import_csv(s, csv_text, "b")
        assert r["added"] == 4 and r["ignored_before_opening_date"] == 2 and "opening date" in r["note"]
        assert bankservice.balance(s) == 1_000_000 - 2500 + 10_000  # the opening balance, the line on its day and what came after
        assert s.query(BankTransaction).count() == 4  # the older lines are kept, so they can still be matched to what they paid


def test_a_statement_with_no_older_lines_has_no_extra_keys(ctx):
    with ctx.factory() as s:
        s.add(BankAccount(name="Operating", currency="USD", opening_minor=0, opening_date=date(2026, 1, 1)))
        s.flush()
        assert bankservice.import_csv(s, FEE, "b") == {"added": 1, "skipped_already_imported": 0, "possible_duplicates": 0}


# ---- 4. a signature image is not a bill, and a second stop is shown ----

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 40


def outlook_message(sender: str, subject: str, text: str, extra_attachment: tuple[str, bytes] | None = None) -> bytes:
    """The shape Outlook makes: multipart/related holding the text (plain and html) and the signature picture as an inline part."""
    from email.mime.application import MIMEApplication
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain"))
    alt.attach(MIMEText(f"<html><body><p>{text}</p><img src='cid:sig1'></body></html>", "html"))
    root = MIMEMultipart("related")
    root.attach(alt)
    img = MIMEImage(PNG, "png")
    img.add_header("Content-ID", "<sig1>")
    img.add_header("Content-Disposition", "inline", filename="image001.png")
    root.attach(img)
    if extra_attachment:
        outer = MIMEMultipart("mixed")
        outer.attach(root)
        pdf_part = MIMEApplication(extra_attachment[1], "pdf")
        pdf_part.add_header("Content-Disposition", "attachment", filename=extra_attachment[0])
        outer.attach(pdf_part)
        root = outer
    root["From"], root["To"], root["Subject"] = sender, "bills@example.test", subject
    return root.as_bytes()


def test_the_test_message_really_is_the_shape_that_used_to_break_intake():
    import email
    from email.policy import default

    msg = email.message_from_bytes(outlook_message("a@customer.test", "Re: reminder", "Please stop."), policy=default)
    assert msg.get_content_type() == "multipart/related"
    assert [p.get_content_type() for p in msg.iter_attachments()] == ["image/png"]  # the standard library hands the signature over as an attachment


def make_customer(s, ctx, email="owner@customer.test", name="Customer One"):
    c = setup_data.create_customer(s, ctx.settings, "t", name=name, email=email)
    s.commit()
    return c


def test_a_stop_reply_with_a_signature_image_stays_unread_and_is_shown(ctx):
    with StubMailServers() as srv:
        with ctx.factory() as s:
            cust = make_customer(s, ctx)
        srv.store.deliver(outlook_message("owner@customer.test", "Re: Invoice INV-1 reminder", "Please stop sending me these reminders."))
        ctx.adapters.inbox = ImapInbox(imap_settings(srv))
        with ctx.factory() as s:
            out = intake.run_intake(s, ctx)
            s.commit()
            assert out["fetched"] == 0 and srv.store.inbox[0]["seen"] is False  # not a bill, not marked read
            shown = s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "stop_reply", ExceptionItem.ref_id == cust.id)).all()
            assert len(shown) == 1 and shown[0].status == "open"


def test_a_real_pdf_with_a_signature_image_in_the_same_message_is_still_read(ctx):
    with StubMailServers() as srv:
        srv.store.deliver(outlook_message("billing@vendor.test", "Invoice", "Invoice attached.", ("inv.pdf", bill_pdf(number="SIG-1"))))
        docs = ImapInbox(imap_settings(srv)).fetch_documents()
        assert [d.file_name for d in docs] == ["inv.pdf"]


def test_a_scanned_bill_attached_as_a_picture_is_still_taken():
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "billing@vendor.test", "bills@example.test", "Scan"
    m.set_content("scan attached")
    m.add_attachment(PNG, maintype="image", subtype="png", filename="scan.png")
    with StubMailServers() as srv:
        srv.store.deliver(m.as_bytes())
        assert [d.file_name for d in ImapInbox(imap_settings(srv)).fetch_documents()] == ["scan.png"]


def test_a_second_stop_request_is_shown_again_after_the_first_was_closed(ctx):
    with StubMailServers() as srv:
        with ctx.factory() as s:
            cust = make_customer(s, ctx)
        ctx.adapters.inbox = ImapInbox(imap_settings(srv))
        srv.store.deliver(outlook_message("owner@customer.test", "stop", "Please stop."))
        with ctx.factory() as s:
            intake.run_intake(s, ctx)
            row = s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "stop_reply")).one()
            resolve(s, row.id, "owner")
            s.commit()
            intake.run_intake(s, ctx)  # the same message is not raised again once it was dealt with
            s.commit()
            assert s.get(ExceptionItem, row.id).status == "resolved"
        srv.store.deliver(outlook_message("owner@customer.test", "stop", "Please stop."))  # the same words again, a new message
        with ctx.factory() as s:
            intake.run_intake(s, ctx)
            s.commit()
            rows = s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "stop_reply", ExceptionItem.ref_id == cust.id)).all()
            assert [r.status for r in rows] == ["open"]


def test_an_answer_from_a_customer_that_was_closed_is_shown_again_when_a_new_one_comes(ctx):
    with ctx.factory() as s:
        cust = make_customer(s, ctx)
        from booklantern.adapters.base import InboundNote

        class Notes:
            def __init__(self, notes):
                self.notes = notes

            def take_notes(self):
                out, self.notes = self.notes, []
                return out

        ctx.adapters.inbox = Notes([InboundNote("7", "owner@customer.test", "Re: reminder", "I paid on Friday")])
        assert intake.record_replies(s, ctx) == 1
        row = s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "customer_reply")).one()
        resolve(s, row.id, "owner")
        ctx.adapters.inbox = Notes([InboundNote("9", "owner@customer.test", "Re: reminder", "Where is my receipt?")])
        assert intake.record_replies(s, ctx) == 1
        assert s.get(ExceptionItem, row.id).status == "open" and "receipt" in s.get(ExceptionItem, row.id).detail


# ---- 5. a currency the system does not know is held ----

def tw_pdf(code="TWD", after=False):
    total = f"11,000.00 {code}" if after else f"{code} 11,000.00"
    return pdf(["Taipei Parts Co", "INVOICE", "Invoice No: TW-100", "Invoice Date: 2026-11-20", "Due Date: 2026-12-20", "Bill To: Birchfield Supply Co", f"Subtotal {total}", "Tax 0.00", f"Total Due {total}"])


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("code", ["TWD", "COP"])
def test_the_reader_reports_a_currency_code_it_does_not_know(code, after):
    assert offline.extract(tw_pdf(code, after)).value("currency_unknown") == code


def test_the_reader_reports_a_currency_sign_it_does_not_know():
    ex = offline.extract(pdf(["Taipei Parts Co", "INVOICE", "Invoice No: TW-100", "Invoice Date: 2026-11-20", "Bill To: Birchfield", "Total Due NT$11,000.00"]))
    assert ex.value("currency_unknown") == "NT$"


def test_a_bill_in_an_unknown_currency_is_blocked_and_says_its_amounts_are_only_a_placeholder(ctx):
    with ctx.factory() as s:
        doc = intake.ingest(s, ctx, "tw.pdf", tw_pdf(), "upload")
        bill = intake.process_document(s, ctx, doc)
        s.commit()
        row = s.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == bill.id, ExceptionItem.kind == "currency_unknown")).one()
        assert row.severity == "block" and "TWD" in row.detail and "NOT USD amounts" in row.detail


def test_a_model_that_answers_with_an_unknown_currency_is_held_too(ctx, monkeypatch):
    from booklantern.extraction.schema import Extraction, FieldValue

    ex = Extraction("model", True, {"vendor": FieldValue("Taipei Parts Co", 90), "number": FieldValue("TW-1", 90), "issue_date": FieldValue("2026-11-20", 90), "currency": FieldValue("TWD", 90), "total_minor": FieldValue(100000, 90)})
    monkeypatch.setattr(intake, "_extract", lambda session, ctx, doc, data: ex)
    with ctx.factory() as s:
        bill = intake.process_document(s, ctx, intake.ingest(s, ctx, "tw.pdf", tw_pdf(), "upload"))
        assert s.scalars(select(ExceptionItem).where(ExceptionItem.ref_id == bill.id, ExceptionItem.kind == "currency_unknown", ExceptionItem.severity == "block")).first() is not None


def test_ordinary_bills_are_not_held_for_currency(ctx):
    with ctx.factory() as s:
        doc = intake.ingest(s, ctx, "ok.pdf", bill_pdf(number="OK-1"), "upload")
        bill = intake.process_document(s, ctx, doc)
        s.commit()
        assert s.scalars(select(ExceptionItem).where(ExceptionItem.ref_id == bill.id, ExceptionItem.kind == "currency_unknown")).first() is None
    plain = offline.extract(pdf(["Orchard Parts Ltd", "INVOICE", "Invoice No: OP-7", "Invoice Date: 2026-11-20", "Bill To: Birchfield", "Total Due 100.00"]))
    assert plain.value("currency_unknown") is None


# ---- 6. a deposit that names a paid invoice does not pay another one ----

def paid_and_open(settled_number="INV-1001", open_number="INV-1002", amount=100_000):
    return [RC.Target("invoice", 1, settled_number, "Acme Corp", amount, date(2026, 1, 1), date(2026, 1, 31), settled=True),
            RC.Target("invoice", 2, open_number, "Acme Corp", amount, date(2026, 2, 1), date(2026, 2, 28))]


def test_a_deposit_that_names_a_paid_invoice_is_only_suggested_never_confirmed_against_another():
    res = RC.match_all([RC.Txn(1, date(2026, 3, 1), "ACH CREDIT ACME CORP INV-1001", 100_000)], paid_and_open(), [])[0]
    assert res.outcome == "suggested" and "INV-1001" in res.links[0].reason and "already marked paid" in res.links[0].reason


def test_a_deposit_that_names_the_open_invoice_is_still_confirmed():
    res = RC.match_all([RC.Txn(1, date(2026, 3, 1), "ACH CREDIT ACME CORP INV-1002", 100_000)], paid_and_open(), [])[0]
    assert res.outcome == "matched" and res.links[0].id == 2


def test_a_deposit_that_names_no_number_keeps_its_old_behaviour():
    res = RC.match_all([RC.Txn(1, date(2026, 3, 1), "ACH CREDIT ACME CORP", 100_000)], paid_and_open(), [])[0]
    assert res.links[0].id == 2  # the open one is preferred, as before


def test_paid_invoices_are_never_part_of_a_split():
    paid = [RC.Target("invoice", 1, "INV-1", "Acme Corp", 6000, date(2026, 1, 1), date(2026, 1, 31), settled=True), RC.Target("invoice", 2, "INV-2", "Acme Corp", 4000, date(2026, 1, 1), date(2026, 1, 31), settled=True)]
    assert RC.match_all([RC.Txn(1, date(2026, 3, 1), "WIRE ACME CORP", 10_000)], paid, [])[0].outcome == "unmatched"
    open_ = [RC.Target("invoice", 1, "INV-1", "Acme Corp", 6000, date(2026, 1, 1), date(2026, 1, 31)), RC.Target("invoice", 2, "INV-2", "Acme Corp", 4000, date(2026, 1, 1), date(2026, 1, 31))]
    res = RC.match_all([RC.Txn(1, date(2026, 3, 1), "WIRE ACME CORP", 10_000)], open_, [])[0]
    assert res.outcome == "matched" and sorted(l.id for l in res.links) == [1, 2]


# ---- 8. a bill cannot be stuck in "posting" ----

def posting_bill(s, status="posting", number="P-1"):
    v = setup_data.create_vendor(s, __import__("booklantern.config", fromlist=["Settings"]).Settings(_env_file=None), "t", name=f"Vendor {number}")
    b = Bill(vendor_id=v.id, vendor_name_read=v.name, number=number, issue_date=date(2026, 1, 2), due_date=date(2026, 2, 1), currency="USD", subtotal_minor=1000, tax_minor=0, total_minor=1000, status=status)
    s.add(b)
    s.flush()
    return b


def claimed(s, ctx, bill, minutes_ago):
    record_audit(s, "owner", "bill.post_claimed", f"bill:{bill.id}", {"claimed_at": (ctx.now(s) - timedelta(minutes=minutes_ago)).isoformat()})


def test_a_bill_left_in_posting_gets_the_finding_that_lets_a_person_settle_it(ctx):
    with ctx.factory() as s:
        old, fresh, none = posting_bill(s, number="P-1"), posting_bill(s, number="P-2"), posting_bill(s, number="P-3")
        claimed(s, ctx, old, posting.STALE_POST_MINUTES + 5)
        claimed(s, ctx, fresh, 1)
        s.commit()
        assert posting.sweep_stale_posts(s, ctx) == 2  # the old claim, and the bill that has no record of a claim at all (made before this check existed)
        s.commit()
        raised = {e.ref_id for e in s.scalars(select(ExceptionItem).where(ExceptionItem.kind == posting.UNKNOWN_POST, ExceptionItem.status == "open"))}
        assert raised == {old.id, none.id}
        assert posting.sweep_stale_posts(s, ctx) == 0  # nothing new the second time
        b = posting.resolve_unknown_post(s, old.id, "owner", False, note="I looked in the accounting system, no draft there")
        assert b.status == "approved"


def test_the_sweep_runs_with_the_reconcile_job(ctx):
    with ctx.factory() as s:
        b = posting_bill(s)
        claimed(s, ctx, b, posting.STALE_POST_MINUTES + 30)
        s.commit()
        jobs.job_reconcile(s, ctx)
        s.commit()
        assert s.scalars(select(ExceptionItem).where(ExceptionItem.ref_id == b.id, ExceptionItem.kind == posting.UNKNOWN_POST, ExceptionItem.status == "open")).first() is not None


def test_a_post_records_when_it_was_claimed(tmp_path):
    from .test_hardening_money import CountingAccounting, approved_bill, live_ctx

    ctx = live_ctx(tmp_path)
    ctx.adapters.accounting = CountingAccounting()
    with ctx.factory() as s:
        b = approved_bill(s)
        s.commit()
        assert posting.post_draft(s, ctx, b.id, "owner")["posted"] is True
        s.commit()
        from sendora_core.models import AuditEntry

        assert s.scalars(select(AuditEntry).where(AuditEntry.action == "bill.post_claimed", AuditEntry.target == f"bill:{b.id}")).first() is not None


def test_the_generic_close_route_cannot_free_a_bill_that_is_still_posting(ctx):
    with ctx.factory() as s:
        b = posting_bill(s)
        e = raise_exception(s, posting.UNKNOWN_POST, "block", "bill", b.id, "unclear")
        s.commit()
        bill_id, exc_id = b.id, e.id
    c = TestClient(create_app(ctx.settings, ctx))
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    c.headers["x-booklantern"] = "1"
    r = c.post(f"/api/exceptions/{exc_id}/resolve", json={"note": "I checked the accounting system, all fine"})
    assert r.status_code == 409 and "post-outcome" in r.json()["error"]["message"]
    with ctx.factory() as s:
        assert s.get(ExceptionItem, exc_id).status == "open" and s.get(Bill, bill_id).status == "posting"
    r2 = c.post(f"/api/bills/{bill_id}/post-outcome", json={"posted": False, "note": "I looked in the accounting system, no draft there"})
    assert r2.status_code == 200 and r2.json()["status"] == "approved"


def test_a_finding_about_a_post_that_is_no_longer_posting_can_be_closed_the_usual_way(ctx):
    with ctx.factory() as s:
        b = posting_bill(s, status="approved")
        e = raise_exception(s, posting.UNKNOWN_POST, "block", "bill", b.id, "unclear")
        s.commit()
        exc_id = e.id
    c = TestClient(create_app(ctx.settings, ctx))
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    c.headers["x-booklantern"] = "1"
    assert c.post(f"/api/exceptions/{exc_id}/resolve", json={"note": "The bill is approved again, nothing is left to settle"}).status_code == 200


# ---- the smaller things ----

def test_an_invoice_total_written_with_its_own_currency_is_read_in_that_currency(ctx):
    with ctx.factory() as s:
        setup_data.import_customers(s, ctx.settings, "t", "name\nAl Noor Trading\n")
        setup_data.import_invoices(s, ctx.settings, "t", "number,customer,issue_date,due_date,total\nE-1,Al Noor Trading,2026-03-01,2026-03-31,EUR 1.250\n")  # no currency column: the amount says it
        got = s.scalars(select(Invoice).where(Invoice.number == "E-1")).one()
        assert (got.currency, got.total_minor) == ("EUR", 125000)
        with pytest.raises(setup_data.SetupError, match="written in EUR but the currency column says USD"):
            setup_data.import_invoices(s, ctx.settings, "t", "number,customer,issue_date,due_date,total,currency\nE-2,Al Noor Trading,2026-03-01,2026-03-31,EUR 100.00,USD\n")


def test_a_sign_that_does_not_fit_the_currency_is_refused_not_ignored():
    assert parse_amount("€12.50", "USD") is None and parse_amount("£12.50", "EUR") is None
    assert parse_amount("$12.50", "CAD") == (1250, "CAD") and parse_amount("€12.50", "EUR") == (1250, "EUR") and parse_amount("£12.50", "GBP") == (1250, "GBP")
    assert parse_amount("€12.50") == (1250, "EUR")


def test_a_hand_link_cannot_pay_more_than_is_still_owed_on_an_invoice_imported_part_paid(ctx):
    with ctx.factory() as s:
        c = setup_data.create_customer(s, ctx.settings, "t", name="Marlowe Bakery")
        inv = Invoice(customer_id=c.id, number="INV-9", issue_date=date(2026, 1, 1), due_date=date(2026, 1, 31), currency="USD", total_minor=100_000, paid_minor=60_000, status="open")
        acct = BankAccount(name="x", currency="USD", opening_minor=0, opening_date=date(2026, 1, 1))
        s.add_all([inv, acct])
        s.flush()
        t = BankTransaction(bank_account_id=acct.id, ref="r", posted_on=date(2026, 2, 1), description="WIRE", amount_minor=100_000, currency="USD", row_hash="h", status="unmatched")
        s.add(t)
        s.flush()
        with pytest.raises(ValueError, match="more than the amount"):
            bankservice.link_manually(s, t.id, "invoice", inv.id, 50_000, "owner")
        assert bankservice.link_manually(s, t.id, "invoice", inv.id, 40_000, "owner").allocated_minor == 40_000


def test_a_file_that_says_it_is_a_pdf_but_is_not_is_listed_for_a_person(ctx):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "billing@vendor.test", "bills@example.test", "Invoice"
    m.set_content("attached")
    m.add_attachment(b"this is not a pdf at all", maintype="application", subtype="pdf", filename="inv.pdf")
    with StubMailServers() as srv:
        srv.store.deliver(m.as_bytes())
        ctx.adapters.inbox = ImapInbox(imap_settings(srv))
        with ctx.factory() as s:
            out = intake.run_intake(s, ctx)
            s.commit()
            assert out["fetched"] == 0
            row = s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "unsupported_file")).one()
            assert "inv.pdf" in row.detail and row.status == "open"


def test_an_approver_cannot_set_an_exchange_rate_but_the_owner_can(ctx):
    c = TestClient(create_app(ctx.settings, ctx))
    c.headers["x-booklantern"] = "1"
    body = {"currency": "GBP", "rate_date": "2026-12-01", "rate": "1.2700"}
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "approver@example.test", "password": "demo-password-1"}).json()["token"]
    assert c.post("/api/fx-rates", json=body).status_code == 403
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    assert c.post("/api/fx-rates", json=body).status_code == 200


def test_a_bill_edit_logs_the_old_and_the_new_value(ctx):
    from sendora_core.models import AuditEntry

    with ctx.factory() as s:
        b = posting_bill(s, status="needs_review")
        s.commit()
        bill_id = b.id
    c = TestClient(create_app(ctx.settings, ctx))
    c.headers["x-booklantern"] = "1"
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    assert c.patch(f"/api/bills/{bill_id}", json={"po_number": "PO-77", "total_minor": 1500}).status_code == 200
    with ctx.factory() as s:
        e = s.scalars(select(AuditEntry).where(AuditEntry.action == "bill.edited", AuditEntry.target == f"bill:{bill_id}")).one()
        assert e.detail["changes"]["po_number"] == {"old": "", "new": "PO-77"} and e.detail["changes"]["total_minor"] == {"old": 1000, "new": 1500}
