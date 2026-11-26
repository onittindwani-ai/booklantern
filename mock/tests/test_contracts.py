"""Contract tests: the Tier A adapters against excerpts saved in mock/contracts/ (see each SOURCE.txt for what was read, when, and what could not be fetched).

QuickBooks has no fetchable machine readable spec: its token request follows the OAuth standard and the verified endpoint; its bill and invoice excerpts are our own written contract
(UNVERIFIED against Intuit). Nothing here ran against a real service.
"""

import base64
import csv
import json
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import httpx
from sendora_core.settings import Mode

from booklantern.adapters.base import DraftBill
from booklantern.adapters.imap import SmtpSender
from booklantern.adapters.others import CsvAccounting
from booklantern.adapters.quickbooks import QuickBooksAccounting

C = Path(__file__).resolve().parents[1] / "contracts"


def load(vendor, name):
    return json.loads((C / vendor / name).read_text(encoding="utf-8"))


def settings(**kw):
    base = dict(qbo_client_id="cid", qbo_client_secret="sec", qbo_refresh_token="rt", qbo_realm_id="123", qbo_environment="sandbox", qbo_minor_version="75", qbo_api_base="", qbo_token_url="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer", accounting_write=True,
                mode=Mode.LIVE, kill_switch=False)
    base.update(kw)
    return SimpleNamespace(**base)


def qbo(handler, **kw):
    tok = httpx.Client(transport=httpx.MockTransport(handler))
    api = httpx.Client(base_url="https://sandbox-quickbooks.api.intuit.com", transport=httpx.MockTransport(handler))
    return QuickBooksAccounting(settings(**kw), api, tok)


def test_every_contract_folder_says_where_it_came_from():
    names = {d.name for d in C.iterdir() if d.is_dir()}
    assert names == {"quickbooks", "csv", "smtp_imap"}
    for d in C.iterdir():
        if d.is_dir():
            assert "2026-11-23" in (d / "SOURCE.txt").read_text(encoding="utf-8") or d.name == "csv"


def test_quickbooks_token_request_matches_the_documented_refresh_grant():
    doc, seen = load("quickbooks", "token_refresh.json"), {}

    def handler(req):
        if str(req.url).startswith(doc["url"]):
            seen["h"], seen["form"] = req.headers, dict(urllib.parse.parse_qsl(req.content.decode()))
            return httpx.Response(200, json={"access_token": "a", "refresh_token": "r2", "expires_in": 3600, "token_type": "bearer"})
        return httpx.Response(200, json={"QueryResponse": {}})

    qbo(handler).healthcheck()
    assert seen["h"]["authorization"] == "Basic " + base64.b64encode(b"cid:sec").decode()
    assert seen["h"]["content-type"] == doc["request_headers"]["Content-Type"] and seen["h"]["accept"] == "application/json"
    assert seen["form"] == {"grant_type": "refresh_token", "refresh_token": "rt"}
    assert {"access_token", "refresh_token", "expires_in"} <= set(doc["response_fields"])


def test_quickbooks_bill_request_keeps_to_the_written_contract_and_reads_the_id():
    doc, seen = load("quickbooks", "bill_create.json"), {}

    def handler(req):
        if req.url.host == "oauth.platform.intuit.com":
            return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
        seen["m"], seen["p"], seen["q"], seen["b"] = req.method, req.url.path, dict(req.url.params), json.loads(req.content)
        return httpx.Response(200, json={"Bill": {"Id": "77"}})

    draft = DraftBill("Test Vendor", "T-1", "2026-11-02", "2026-12-02", "USD", [{"description": "Work", "quantity": 1, "unit_minor": 10000, "total_minor": 10000}], 10000, 1000, 11000, "memo")
    assert qbo(handler).create_draft_bill(draft) == "77"
    assert seen["m"] == doc["method"] and seen["p"] == doc["path"].replace("{realmId}", "123") and set(doc["query"]) >= set(seen["q"])
    assert set(doc["request_required"]) <= set(seen["b"])
    line = seen["b"]["Line"][0]
    assert set(doc["request_line_fields"]) <= set(line) and line["DetailType"] == doc["request_line_detail_type"] and line["Amount"] == 100.0


def test_quickbooks_invoice_query_and_parse_keep_to_the_written_contract():
    doc, seen = load("quickbooks", "invoice_query.json"), {}

    def handler(req):
        if req.url.host == "oauth.platform.intuit.com":
            return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
        seen["p"], seen["q"] = req.url.path, req.url.params["query"]
        return httpx.Response(200, json={"QueryResponse": {"Invoice": [{"Id": "9", "DocNumber": "INV-9", "CustomerRef": {"value": "1", "name": "Ada"}, "TotalAmt": 120.5, "Balance": 20.25, "DueDate": "2026-12-01", "CurrencyRef": {"value": "USD"}}]}})

    inv = qbo(handler).list_open_invoices()
    assert seen["p"] == doc["path"].replace("{realmId}", "123") and seen["q"] == doc["query_text"]
    assert (inv[0].number, inv[0].customer, inv[0].total_minor, inv[0].balance_minor, inv[0].due, inv[0].currency) == ("INV-9", "Ada", 12050, 2025, "2026-12-01", "USD")


def test_csv_adapter_reads_and_writes_the_documented_columns(tmp_path):
    (tmp_path / "invoices.csv").write_text("Number,Customer,Total,Balance,Due\nINV-1,Ada,\"1,200.00\",300.00,2026-12-01\n", encoding="utf-8")
    a = CsvAccounting(settings(csv_folder=str(tmp_path)))
    inv = a.list_open_invoices()[0]
    assert (inv.number, inv.customer, inv.total_minor, inv.balance_minor, inv.due) == ("INV-1", "Ada", 120000, 30000, "2026-12-01")
    a.create_draft_bill(DraftBill("V", "N-1", "2026-11-02", "2026-12-02", "USD", [], 100, 10, 110, "m"))
    rows = list(csv.reader((tmp_path / "draft-bills.csv").open()))
    assert rows[0] == ["Vendor", "Number", "Issued", "Due", "Currency", "Subtotal", "Tax", "Total"] and rows[1][-1] == "110"


def test_smtp_message_has_the_rfc_5322_header_fields(monkeypatch):
    sent = []

    class StubSmtp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, m):
            sent.append(m)

    s = SmtpSender(settings(smtp_host="mail.example.test"))
    monkeypatch.setattr(s, "_smtp", lambda: StubSmtp())
    mid = s.send(from_addr="accounts@example.test", to="ada@example.test", subject="Hello", body="Body")
    m = sent[0]
    assert m["From"] and m["To"] and m["Subject"] == "Hello" and m["Message-ID"] == mid and mid.startswith("<") and mid.endswith(">")
