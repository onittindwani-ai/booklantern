import base64
from email.message import EmailMessage

import httpx
import pytest
from fastapi.testclient import TestClient

from booklantern.adapters.base import DraftBill, safe_base_url
from booklantern.adapters.imap import ImapInbox, SmtpSender
from booklantern.adapters.others import AkauntingAccounting, CsvAccounting, StripePayments, XeroAccounting
from booklantern.adapters.quickbooks import QuickBooksAccounting
from booklantern.config import Settings
from booklantern.registry import build_adapters, build_registry
from mock.accounting_mocks import AkauntingMock, XeroMock
from mock.mail_servers import FakeMailServers
from mock.qbo_mock import QboMock
from mock.stripe_mock import StripeMock
from sendora_core.adapters import AdapterError
from sendora_core.safety import DraftModeError, KillSwitchError
from sendora_core.settings import Mode

BILL = DraftBill("Alderbank Packaging Ltd", "ALD-1", "2026-11-01", "2026-12-01", "USD", [{"description": "Cartons", "quantity": 1, "unit_minor": 1000, "total_minor": 1000}], 1000, 80, 1080)


def S(**kw):
    return Settings(_env_file=None, session_secret="x" * 20, demo_mode=False, owner_password_hash="x", **kw)


def qbo(mode=Mode.DRAFT, write=False, **kw):
    q = QboMock()
    s = S(mode=mode, accounting_write=write, qbo_client_id="mock-client", qbo_client_secret="mock-secret", qbo_refresh_token="mock-refresh-1", qbo_realm_id=q.realm_id, **kw)
    base = TestClient(q.app, base_url="https://qbo.example.test")
    return q, QuickBooksAccounting(s, client=base, token_client=TestClient(q.app, base_url="https://oauth.example.test")), s


def test_quickbooks_refreshes_the_token_and_keeps_the_new_refresh_token():
    q, a, _ = qbo()
    q.invoices["1"] = {"Id": "1", "DocNumber": "INV-9", "CustomerRef": {"name": "Marlowe Bakery"}, "TotalAmt": 120.5, "Balance": 60.25, "DueDate": "2026-12-31"}
    got = a.list_open_invoices()
    assert got[0].total_minor == 12050 and got[0].balance_minor == 6025
    assert a.refresh_token != "mock-refresh-1"  # the new one is kept for next time
    assert q.minor_versions[-1] == "75"


def test_quickbooks_retries_once_after_an_expired_token_then_gives_up():
    q, a, _ = qbo()
    a.list_open_invoices()
    q.expire_next = True
    assert a.list_open_invoices() == []  # one 401 is absorbed by a fresh token
    bad = QboMock()
    s = S(qbo_client_id="wrong", qbo_client_secret="x", qbo_refresh_token="x", qbo_realm_id=bad.realm_id)
    with pytest.raises(AdapterError, match="refresh token"):
        QuickBooksAccounting(s, client=TestClient(bad.app, base_url="https://q"), token_client=TestClient(bad.app, base_url="https://o")).list_open_invoices()


def test_quickbooks_writes_are_blocked_in_draft_mode_by_default_and_by_the_kill_switch():
    q, a, s = qbo(Mode.DRAFT, True)
    with pytest.raises(DraftModeError):
        a.create_draft_bill(BILL)
    q, a, s = qbo(Mode.LIVE, False)
    with pytest.raises(AdapterError, match="ACCOUNTING_WRITE"):
        a.create_draft_bill(BILL)
    q, a, s = qbo(Mode.LIVE, True, kill_switch=True)
    with pytest.raises(KillSwitchError):
        a.create_draft_bill(BILL)
    assert q.bills == {}
    q, a, s = qbo(Mode.LIVE, True)
    assert a.create_draft_bill(BILL) and len(q.bills) == 1


def test_quickbooks_needs_its_settings():
    with pytest.raises(AdapterError):
        QuickBooksAccounting(S())


def test_xero_and_akaunting_read_and_write_only_when_allowed():
    x = XeroMock(); xs = S(mode=Mode.LIVE, accounting_write=True, xero_access_token="mock-xero-token", xero_tenant_id="mock-tenant-1")
    xa = XeroAccounting(xs, client=TestClient(x.app, base_url="https://x.example.test"))
    assert xa.create_draft_bill(BILL) and x.invoices[0]["Status"] == "DRAFT" and x.invoices[0]["Type"] == "ACCPAY"
    assert xa.healthcheck()[0]
    bad = XeroAccounting(S(xero_access_token="nope", xero_tenant_id="mock-tenant-1"), client=TestClient(x.app, base_url="https://x.example.test"))
    assert bad.healthcheck()[0] is False
    k = AkauntingMock(); ks = S(mode=Mode.LIVE, accounting_write=True, akaunting_base_url="https://a.example.test", akaunting_user="owner@example.test", akaunting_password="mock-password")
    ka = AkauntingAccounting(ks, client=TestClient(k.app, base_url="https://a.example.test"))
    assert ka.healthcheck()[0]
    with pytest.raises(AdapterError):
        ka.create_draft_bill(BILL)  # the mock needs a contact id, and the adapter does not invent one: it shows the error


def test_csv_adapter_round_trip(tmp_path):
    (tmp_path / "invoices.csv").write_text("Number,Customer,Total,Balance,Due\nINV-1,Marlowe Bakery,\"1,200.00\",600.00,2026-12-31\n")
    a = CsvAccounting(S(csv_folder=str(tmp_path), mode=Mode.LIVE))
    assert a.list_open_invoices()[0].balance_minor == 60000
    a.create_draft_bill(BILL)
    assert "ALD-1" in (tmp_path / "draft-bills.csv").read_text()
    with pytest.raises(AdapterError):
        CsvAccounting(S(csv_folder=str(tmp_path / "none"))).list_open_invoices()


def test_stripe_payment_link_and_draft_guard():
    st = StripeMock()
    c = TestClient(st.app, base_url="https://api.stripe.example.test")
    live = StripePayments(S(mode=Mode.LIVE, stripe_secret_key="sk_test_mock_key"), client=c)
    url = live.create_payment_link(invoice_number="INV-7", amount_minor=12500, currency="USD", description="Invoice INV-7")
    assert url.startswith("https://buy.stripe.example.test") and st.links[0]["_amount"] == "12500" and st.links[0]["metadata"]["invoice"] == "INV-7"
    assert live.create_payment_link(invoice_number="INV-7", amount_minor=12500, currency="USD", description="x") == url  # same call, same link
    with pytest.raises(AdapterError, match="rejected the key"):
        StripePayments(S(mode=Mode.LIVE, stripe_secret_key="sk_test_wrong"), client=c).create_payment_link(invoice_number="a", amount_minor=1, currency="USD", description="x")
    with pytest.raises(DraftModeError):
        StripePayments(S(mode=Mode.DRAFT, stripe_secret_key="sk_test_mock_key"), client=c).create_payment_link(invoice_number="a", amount_minor=1, currency="USD", description="x")


def test_imap_inbox_takes_pdf_attachments_only_and_smtp_sends():
    with FakeMailServers() as srv:
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = "billing@vendor.example.test", "ap@us.example.test", "Invoice 1"
        m.set_content("see attached")
        m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="inv.pdf")
        m.add_attachment(b"MZ", maintype="application", subtype="octet-stream", filename="run.exe")
        srv.store.deliver(m.as_bytes())
        s = S(imap_host=srv.host, imap_port=srv.imap_port, imap_use_ssl=False, smtp_user="demo", smtp_password="demo-password", smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, mode=Mode.LIVE)
        docs = ImapInbox(s).fetch_documents()
        assert [d.file_name for d in docs] == ["inv.pdf"] and ImapInbox(s).fetch_documents() == []  # marked as seen
        SmtpSender(s).send(from_addr="accounts@us.example.test", to="ap@c.example.test", subject="Hi\r\nBcc: x@y", body="b")
        import email as _email
        assert _email.message_from_string(srv.store.outbox[0]["data"])["Bcc"] is None  # a line break in the subject cannot add a header
        assert ImapInbox(s).healthcheck()[0]
        with pytest.raises(AdapterError):
            ImapInbox(S()).fetch_documents()


def test_ssrf_guard():
    for bad in ("http://example.com", "https://127.0.0.1", "https://user:pw@example.com", "ftp://x.test", "https://169.254.169.254/latest"):
        with pytest.raises(AdapterError):
            safe_base_url(bad)
    assert safe_base_url("http://127.0.0.1:9", allow_http_local=True) == "http://127.0.0.1:9"


def test_registry_demo_mode_allows_only_offline_adapters():
    s = Settings(_env_file=None, demo_mode=True, accounting_adapter="quickbooks")
    with pytest.raises(AdapterError, match="DEMO_MODE"):
        build_adapters(s)
    rows = build_registry(Settings(_env_file=None)).describe()
    assert {r["tier"] for r in rows} == {"A", "B"} and not any(r["live_verified"] for r in rows)
