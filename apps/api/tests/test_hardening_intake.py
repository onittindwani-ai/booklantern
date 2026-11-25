"""Bills that arrive from outside: one hostile file never costs the others, nothing overflows a column, vendor checks work without a seeded list, and the month end PDF survives odd text."""

import hashlib
import io
import logging
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import select

from booklantern import intake, limits, setup_data
from booklantern.adapters.base import InboundDocument
from booklantern.adapters.imap import ImapInbox, SmtpSender
from booklantern.api.app import create_app
from booklantern.exceptions import raise_exception
from booklantern.extraction import offline
from booklantern.extraction.cells import Cell, Page
from booklantern.extraction.numbers import to_minor_units
from booklantern.extraction.schema import Extraction, FieldValue, LineItem
from booklantern.models import Bill, Document, ExceptionItem
from mock.mail_servers import FakeMailServers
from sendora_core.adapters import AdapterError

from .conftest import make_ctx


def pdf(lines: list[str], size=letter) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    y = size[1] - 72
    for ln in lines:
        c.drawString(72, y, ln)
        y -= 18
    c.save()
    return buf.getvalue()


def bill_pdf(vendor="Orchard Parts Ltd", number="OP-100", total="100.00", extra=()):
    return pdf([vendor, "INVOICE", f"Invoice No: {number}", "Invoice Date: 2026-11-20", "Due Date: 2026-12-20", "Bill To: Birchfield Supply Co", *extra, f"Subtotal USD {total}", "Tax USD 0.00", f"Total Due USD {total}"])


class FakeInbox:
    """A mailbox that hands over a fixed list and remembers what it was told to mark read."""

    def __init__(self, docs):
        self.docs, self.acked = docs, []

    def fetch_documents(self):
        return list(self.docs)

    def acknowledge(self, acks):
        self.acked += acks

    def healthcheck(self):
        return True, "fake"


def doc(name, data, ack, external_id=None):
    return InboundDocument(external_id or f"<{ack}@x.test>:{name}", name, data, "billing@vendor.test", "Invoice", ack=ack)


@pytest.fixture()
def demo_ctx(tmp_path):
    return make_ctx(tmp_path)


# ---- one bad document, the others stay ----

def test_one_failing_document_does_not_take_the_others_with_it(demo_ctx, monkeypatch, caplog):
    inbox = FakeInbox([doc("good1.pdf", bill_pdf(number="G-1"), "1"), doc("bad.pdf", bill_pdf(number="BAD-1", extra=["SECRET BILL TEXT"]), "2"), doc("good2.pdf", bill_pdf(number="G-2", total="250.00"), "3")])
    demo_ctx.adapters.inbox = inbox
    real = intake.process_document

    def flaky(session, ctx, d, data=None):
        if d.file_name == "bad.pdf":
            session.add(Bill(vendor_name_read="half written", number="HALF", total_minor=1))  # work done before the failure must be rolled back with it
            session.flush()
            raise OverflowError("Python int too large to convert to SQLite INTEGER")
        return real(session, ctx, d, data)

    monkeypatch.setattr(intake, "process_document", flaky)
    caplog.set_level(logging.INFO)
    with demo_ctx.factory() as s:
        out = intake.run_intake(s, demo_ctx)
    assert out["failed"] == 1 and out["processed"] == 2
    with demo_ctx.factory() as s:
        numbers = sorted(b.number for b in s.scalars(select(Bill)))
        assert numbers == ["G-1", "G-2"]  # both good bills are there, and the half written one is not
        bad = s.scalars(select(Document).where(Document.file_name == "bad.pdf")).one()
        assert bad.status == "unreadable"
        assert s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "unreadable_document", ExceptionItem.ref_type == "document", ExceptionItem.ref_id == bad.id)).first() is not None
    assert sorted(inbox.acked) == ["1", "2", "3"]  # told to mark read only after everything was stored
    assert "SECRET BILL TEXT" not in caplog.text and "OverflowError" in caplog.text  # the failure is logged by its class, never with the text of the bill


def test_a_mailbox_message_stays_unread_when_its_document_cannot_even_be_stored(demo_ctx, monkeypatch):
    inbox = FakeInbox([doc("a.pdf", bill_pdf(number="A-1"), "1"), doc("b.pdf", bill_pdf(number="B-1"), "2")])
    demo_ctx.adapters.inbox = inbox
    real = intake.ingest

    def broken(session, ctx, name, data, *a, **k):
        if name == "a.pdf":
            raise RuntimeError("disk full")
        return real(session, ctx, name, data, *a, **k)

    monkeypatch.setattr(intake, "ingest", broken)
    with demo_ctx.factory() as s:
        intake.run_intake(s, demo_ctx)
    assert inbox.acked == ["2"]  # message 1 is looked at again next time
    with demo_ctx.factory() as s:
        assert [b.number for b in s.scalars(select(Bill))] == ["B-1"]


def test_colliding_message_ids_and_names_never_make_a_reference_clash(demo_ctx):
    same = "<D1>:inv.pdf"
    inbox = FakeInbox([doc("inv.pdf", bill_pdf(number="X-1"), "1", same), doc("inv.pdf", bill_pdf(number="X-2", total="55.00"), "2", same)])
    demo_ctx.adapters.inbox = inbox
    with demo_ctx.factory() as s:
        out = intake.run_intake(s, demo_ctx)
        refs = [d.ref for d in s.scalars(select(Document))]
    assert out["processed"] == 2 and out["failed"] == 0 and len(set(refs)) == 2 and all(r.startswith("DOC-") for r in refs)  # a reference is counted by the system, never copied from a sender's text


def test_the_stored_file_name_is_the_full_hash_so_two_files_never_share_one(demo_ctx):
    with demo_ctx.factory() as s:
        a = intake.ingest(s, demo_ctx, "a.pdf", bill_pdf(number="H-1"))
        b = intake.ingest(s, demo_ctx, "b.pdf", bill_pdf(number="H-2"))
        assert a.stored_path != b.stored_path and a.sha256 in a.stored_path


# ---- nothing overflows a column ----

def fake_extract(**fields):
    def extract(session, ctx, d, data):
        f = {k: FieldValue(v, 90) for k, v in fields.items() if k != "lines"}
        return Extraction("fake", True, f, fields.get("lines", []))
    return extract


def test_huge_values_and_long_text_are_clamped_and_flagged(demo_ctx, monkeypatch):
    monkeypatch.setattr(intake, "_extract", fake_extract(vendor="V" * 5000, number="N" * 500, currency="NOTACURRENCYCODE" * 20, po="P" * 400, bill_to="B" * 900, bank_account="A" * 300, issue_date="not a date",
                                                         subtotal_minor=10**25, tax_minor=0, total_minor=10**25, lines=[LineItem("L" * 900, 10**15, 10**25, 10**25)]))
    with demo_ctx.factory() as s:
        d = intake.ingest(s, demo_ctx, "x.pdf", bill_pdf(number="CLAMP-1"))
        b = intake.process_document(s, demo_ctx, d)
        s.commit()
        assert len(b.vendor_name_read) == 200 and len(b.number) == 80 and len(b.po_number) == 60 and len(b.bill_to) == 200 and len(b.bank_account) == 80
        assert b.currency == "USD" and b.issue_date is None and b.total_minor == 0 and b.lines[0].total_minor == 0 and len(b.lines[0].description) == 240
        kinds = {e.kind: e.severity for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_id == b.id))}
        assert kinds["implausible_amount"] == "block"


def test_a_number_with_twenty_digits_is_not_read_as_an_amount():
    assert to_minor_units("99999999999999999999.00", 2) is None
    assert to_minor_units("1,250.00", 2) == 125000


def test_a_twenty_digit_total_on_a_real_page_gives_a_bill_nobody_can_approve(demo_ctx):
    with demo_ctx.factory() as s:
        d = intake.ingest(s, demo_ctx, "huge.pdf", bill_pdf(number="HUGE-1", total="99999999999999999999.00"))
        b = intake.process_document(s, demo_ctx, d)
        s.commit()
        assert b.total_minor == 0 and b.status == "needs_review"


def test_a_negative_total_is_a_blocking_finding_not_a_payable_bill(demo_ctx):
    with demo_ctx.factory() as s:
        d = intake.ingest(s, demo_ctx, "neg.pdf", pdf(["Orchard Parts Ltd", "Invoice No: NEG-1", "Invoice Date: 2026-11-20", "Due Date: 2026-12-20", "Bill To: Birchfield Supply Co", "Subtotal USD (1,250.00)", "Tax USD 0.00", "Total Due USD (1,250.00)"]))
        b = intake.process_document(s, demo_ctx, d)
        s.commit()
        kinds = {e.kind: e.severity for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_id == b.id))}
        assert kinds.get("negative_amount") == "block" and "credit_note" in kinds


def test_the_model_path_flags_a_negative_amount_too():
    from booklantern.extraction.schema import Extraction as E  # the shape the model path returns for a negative reading
    ex = E("model", True, {"negative_amount": FieldValue(1, 90), "doc_type": FieldValue("credit_note", 60)})
    assert ex.value("negative_amount") == 1


# ---- vendor checks without a seeded vendor list ----

def test_the_same_bill_twice_is_a_duplicate_even_with_no_vendor_list(demo_ctx):
    with demo_ctx.factory() as s:
        first = intake.process_document(s, demo_ctx, intake.ingest(s, demo_ctx, "a.pdf", bill_pdf(number="DUP-1")))
        second = intake.process_document(s, demo_ctx, intake.ingest(s, demo_ctx, "b.pdf", bill_pdf(number="DUP-1", extra=["Page 1 of 1"])))  # a different file: another hash
        s.commit()
        assert first.vendor_id is None and second.vendor_id is None
        kinds = {e.kind for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_id == second.id, ExceptionItem.ref_type == "bill"))}
        assert "duplicate_exact" in kinds


def test_a_vendor_with_an_account_on_file_and_a_bill_with_none_read_is_held_back(demo_ctx):
    with demo_ctx.factory() as s:
        setup_data.create_vendor(s, demo_ctx.settings, "owner", name="Orchard Parts Ltd", bank_account="021000021 123456789")
        b = intake.process_document(s, demo_ctx, intake.ingest(s, demo_ctx, "a.pdf", bill_pdf(number="NB-1")))
        s.commit()
        kinds = {e.kind: e.severity for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_id == b.id, ExceptionItem.ref_type == "bill"))}
        assert kinds.get("bank_details_not_read") == "block"


def test_routing_and_account_labels_are_read_and_compared(demo_ctx):
    with demo_ctx.factory() as s:
        setup_data.create_vendor(s, demo_ctx.settings, "owner", name="Orchard Parts Ltd", bank_account="021000021 123456789")
        same = intake.process_document(s, demo_ctx, intake.ingest(s, demo_ctx, "a.pdf", bill_pdf(number="RT-1", extra=["Bank: First Example Bank", "Routing number: 021000021", "Account number: 123456789"])))
        changed = intake.process_document(s, demo_ctx, intake.ingest(s, demo_ctx, "b.pdf", bill_pdf(number="RT-2", extra=["Bank: First Example Bank", "Routing number: 021000021", "Account number: 999999999"])))
        s.commit()
        assert same.bank_account == "021000021 123456789" and changed.bank_account == "021000021 999999999"
        flags = lambda b: {e.kind for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_id == b.id, ExceptionItem.ref_type == "bill"))}  # noqa: E731
        assert "bank_detail_changed" not in flags(same) and "bank_detail_changed" in flags(changed)


def test_an_account_number_alone_is_not_taken_for_bank_details():
    rows = offline._rows([Page(600, 800, [Cell("Account number: 4471123", 10, 10, 200, 20)], 25)])
    assert offline.labelled_bank_details(rows) is None  # usually the customer's own account with the vendor


# ---- the month end PDF ----

def test_text_that_looks_like_markup_cannot_break_the_month_end_pdf(demo_ctx):
    ctx = demo_ctx
    with ctx.factory() as s:
        d = intake.ingest(s, ctx, "m.pdf", bill_pdf(number="<b>BR-1"))
        b = intake.process_document(s, ctx, d)
        b.bill_to = "<b>Acme <font color=red>Co & <a href='https://evil.example'>click"
        raise_exception(s, "wrong_company", "block", "bill", b.id, f"The bill is addressed to {b.bill_to}, not X.")
        s.commit()
    c = TestClient(create_app(ctx.settings, ctx))
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    r = c.get("/api/reports/month-end.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


# ---- the page picture ----

def test_a_page_that_claims_to_be_enormous_is_drawn_small(demo_ctx):
    from PIL import Image

    big = pdf(["Huge Page Co", "Invoice No: BIG-1", "Total Due USD 5.00"], size=(14400, 14400))
    with demo_ctx.factory() as s:
        d = intake.ingest(s, demo_ctx, "big.pdf", big)
        intake.process_document(s, demo_ctx, d)
        s.commit()
        doc_id = d.id
    c = TestClient(create_app(demo_ctx.settings, demo_ctx))
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    r = c.get(f"/api/documents/{doc_id}/page/1.png")
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    w, h = Image.open(io.BytesIO(r.content)).size
    assert w * h <= 4_100_000


# ---- the mailbox ----

def mail(attachments, subject="Invoice"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "billing@vendor.example.test", "ap@us.example.test", subject
    m.set_content("see attached")
    for name, data in attachments:
        m.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return m.as_bytes()


def imap_settings(srv, **kw):
    from booklantern.config import Settings

    return Settings(_env_file=None, imap_host=srv.host, imap_port=srv.imap_port, imap_use_ssl=False, smtp_user="demo", smtp_password="demo-password", smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, **kw)


def test_reading_a_message_does_not_mark_it_read_and_a_poll_through_the_real_adapter_acknowledges_after_storing(demo_ctx):
    with FakeMailServers() as srv:
        srv.store.deliver(mail([("a.pdf", bill_pdf(number="MB-1"))]))
        srv.store.deliver(mail([("b.pdf", b"%PDF-1.4 broken \x00\x01")]))
        srv.store.deliver(b"From: x@y.test\r\nSubject: hello\r\n\r\nno attachment here\r\n")
        demo_ctx.adapters.inbox = ImapInbox(imap_settings(srv))
        assert len(demo_ctx.adapters.inbox.fetch_documents()) == 2 and [m["seen"] for m in srv.store.inbox] == [False, False, True]  # only the message with nothing to lose was marked
        with demo_ctx.factory() as s:
            out = intake.run_intake(s, demo_ctx)
        assert out["fetched"] == 2 and [m["seen"] for m in srv.store.inbox] == [True, True, True]


def test_an_oversized_message_is_skipped_unread_into_memory(monkeypatch):
    from booklantern.adapters import imap

    monkeypatch.setattr(imap, "MAX_MESSAGE_BYTES", 500)
    with FakeMailServers() as srv:
        srv.store.deliver(mail([("a.pdf", bill_pdf())]))
        assert ImapInbox(imap_settings(srv)).fetch_documents() == [] and srv.store.inbox[0]["seen"] is True


def test_a_poll_takes_at_most_a_set_number_of_messages(monkeypatch):
    from booklantern.adapters import imap

    monkeypatch.setattr(imap, "MAX_MESSAGES_PER_POLL", 2)
    with FakeMailServers() as srv:
        for i in range(5):
            srv.store.deliver(mail([(f"{i}.pdf", bill_pdf(number=f"CAP-{i}"))]))
        assert len(ImapInbox(imap_settings(srv)).fetch_documents()) == 2


# ---- TLS ----

def test_plain_text_mail_is_refused_for_any_host_but_this_computer():
    from booklantern.config import Settings

    remote = Settings(_env_file=None, smtp_host="mail.example.test", smtp_use_tls=False, imap_host="mail.example.test", imap_use_ssl=False, smtp_user="u", smtp_password="p")
    with pytest.raises(AdapterError, match="SMTP_USE_TLS=false"):
        SmtpSender(remote)._smtp()
    with pytest.raises(AdapterError, match="IMAP_USE_SSL=false"):
        ImapInbox(remote)._imap()


def test_mail_connections_pass_a_verifying_context(monkeypatch):
    from booklantern.config import Settings

    seen = {}

    class Boom(Exception):
        pass

    def smtp_ssl(host, port, timeout=None, context=None):
        seen["smtp_ssl"] = context
        raise Boom

    def imap_ssl(host, port, ssl_context=None, timeout=None):
        seen["imap_ssl"] = ssl_context
        raise Boom

    monkeypatch.setattr(smtplib, "SMTP_SSL", smtp_ssl)
    import imaplib

    monkeypatch.setattr(imaplib, "IMAP4_SSL", imap_ssl)
    s = Settings(_env_file=None, smtp_host="mail.example.test", smtp_port=465, imap_host="mail.example.test", smtp_user="u", smtp_password="p")
    for fn in (SmtpSender(s)._smtp, ImapInbox(s)._imap):
        with pytest.raises(Boom):
            fn()
    for ctx in seen.values():
        assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True


def test_a_sent_reminder_carries_an_unsubscribe_header():
    from booklantern.config import Settings

    with FakeMailServers() as srv:
        s = imap_settings(srv, mode="live", reply_to="ar@riveraworks.test")
        SmtpSender(s).send(from_addr="accounts@riveraworks.test", to="c@customer.test", subject="Reminder", body="hello")
        import email as _email

        got = _email.message_from_string(srv.store.outbox[0]["data"])
        assert got["List-Unsubscribe"] == "<mailto:ar@riveraworks.test?subject=stop%20reminders>" and got["Reply-To"] == "ar@riveraworks.test"


# ---- forms and csv ----

def test_bounds_on_what_a_person_can_type(demo_ctx):
    c = TestClient(create_app(demo_ctx.settings, demo_ctx))
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    bill = next(b for b in c.get("/api/bills").json())
    url = f"/api/bills/{bill['id']}"
    assert c.patch(url, json={"lines": [{"description": "x", "quantity_milli": 1000, "unit_minor": -5, "total_minor": 1}]}).status_code == 422
    assert c.patch(url, json={"lines": [{"description": "x", "quantity_milli": 1000, "unit_minor": 1, "total_minor": 10**30}]}).status_code == 422
    assert c.patch(url, json={"currency": "ZZZ"}).status_code == 422  # an unknown code would break the month end pack
    assert c.patch(url, json={"vendor_id": 99999}).status_code == 422


def test_a_short_csv_row_is_a_clear_error_not_a_crash(demo_ctx):
    c = TestClient(create_app(demo_ctx.settings, demo_ctx))
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    r = c.post("/api/bank/import", json={"text": "Date,Description,Amount\n2026-03-01,ONLY TWO\n", "name": "x" * 40})
    assert r.status_code == 422 and "fewer columns" in r.json()["error"]["message"]
    long = "Date,Description,Amount,Reference\n2026-03-01," + "D" * 400 + ",1.00," + "R" * 90 + "\n"
    assert c.post("/api/bank/import", json={"text": long}).status_code == 200
    assert c.post("/api/bank/import", json={"text": "x", "name": "n" * 41}).status_code == 422


def test_a_model_backed_page_never_costs_a_read_only_visitor_a_paid_call(tmp_path):
    from booklantern.offline_llm import OfflineBackend
    from sendora_core.llm_anthropic import AnthropicBackend

    ctx = make_ctx(tmp_path, llm_backend="anthropic", anthropic_api_key="test-only-key-123456")
    with ctx.factory() as s:
        assert isinstance(ctx.llm(s).backend, AnthropicBackend)
        assert isinstance(ctx.llm(s, live=False).backend, OfflineBackend)
