import base64

from fastapi.testclient import TestClient

from mock.accounting_mocks import AkauntingMock, XeroMock
from mock.qbo_mock import QboMock
from mock.stripe_mock import StripeMock


def _basic(a, b):
    return {"authorization": "Basic " + base64.b64encode(f"{a}:{b}".encode()).decode(), "content-type": "application/x-www-form-urlencoded"}


def test_qbo_token_refresh_and_bill_create():
    q = QboMock()
    c = TestClient(q.app)
    assert c.post("/oauth2/v1/tokens/bearer", content="grant_type=authorization_code&code=x", headers=_basic("bad", "bad")).status_code == 401
    r = c.post("/oauth2/v1/tokens/bearer", content="grant_type=refresh_token&refresh_token=mock-refresh-1", headers=_basic("mock-client", "mock-secret"))
    assert r.status_code == 200 and r.json()["expires_in"] == 3600
    tok = r.json()["access_token"]
    h = {"authorization": f"Bearer {tok}"}
    base = f"/v3/company/{q.realm_id}"
    assert c.post(f"{base}/bill", json={"Line": []}, headers=h).status_code == 400
    ok = c.post(f"{base}/bill?minorversion=75", json={"VendorRef": {"value": "1"}, "Line": [{"Amount": 10}]}, headers=h)
    assert ok.status_code == 200 and ok.json()["Bill"]["Id"]
    assert q.minor_versions[-1] == "75"
    assert c.get(f"{base}/query", params={"query": "select * from Bill"}, headers=h).json()["QueryResponse"]["Bill"]
    assert c.get(f"{base}/query", params={"query": "select * from Bill"}).status_code == 401
    assert c.get("/v3/company/999/query", params={"query": "select * from Bill"}, headers=h).status_code == 400


def test_qbo_expired_token_is_a_401_once():
    q = QboMock(); c = TestClient(q.app); q.expire_next = True
    assert c.get(f"/v3/company/{q.realm_id}/query", params={"query": "select * from Bill"}, headers={"authorization": f"Bearer {q.access}"}).status_code == 401


def test_stripe_payment_link_idempotent():
    s = StripeMock(); c = TestClient(s.app)
    h = {"authorization": "Basic " + base64.b64encode(b"sk_test_mock_key:").decode(), "idempotency-key": "k1"}
    body = "line_items[0][price_data][currency]=usd&line_items[0][price_data][unit_amount]=12500&line_items[0][quantity]=1&metadata[invoice]=INV-1"
    assert c.post("/v1/payment_links", content=body).status_code == 401
    assert c.post("/v1/payment_links", content="x=1", headers=h).status_code == 400
    a = c.post("/v1/payment_links", content=body, headers=h).json(); b = c.post("/v1/payment_links", content=body, headers=h).json()
    assert a["id"] == b["id"] and len(s.links) == 1 and a["metadata"]["invoice"] == "INV-1"


def test_xero_and_akaunting():
    x = XeroMock(); c = TestClient(x.app)
    h = {"authorization": "Bearer mock-xero-token", "xero-tenant-id": "mock-tenant-1"}
    assert c.get("/api.xro/2.0/Invoices", headers={"authorization": "Bearer nope"}).status_code == 401
    assert c.post("/api.xro/2.0/Invoices", json={"Type": "ACCPAY"}, headers=h).json()["Invoices"][0]["Status"] == "DRAFT"
    a = AkauntingMock(); d = TestClient(a.app)
    ah = {"authorization": a.cred}
    assert d.post("/api/documents", json={"type": "bill"}, headers=ah).status_code == 422
    assert d.post("/api/documents", json={"type": "bill", "contact_id": 1}, headers=ah).json()["data"]["status"] == "draft"
