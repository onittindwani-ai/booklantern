from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from booklantern.api.app import create_app

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def client(seeded):
    app = create_app(seeded.settings, seeded)
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"})
    assert r.status_code == 200
    c.headers["x-session"] = r.json()["token"]
    c.owner_token = r.json()["token"]
    return c


def approver(client):
    r = client.post("/api/auth/login", json={"email": "approver@example.test", "password": "demo-password-1"})
    return {"x-session": r.json()["token"]}


def test_every_route_needs_a_session(seeded):
    c = TestClient(create_app(seeded.settings, seeded))
    for path in ("/api/overview", "/api/bills", "/api/forecast", "/api/audit", "/api/demo/state"):
        assert c.get(path).status_code == 401
    assert c.post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong"}).status_code == 401
    assert c.get("/health").status_code == 200


def test_login_is_rate_limited(seeded):
    c = TestClient(create_app(seeded.settings, seeded))
    codes = [c.post("/api/auth/login", json={"email": "owner@example.test", "password": "nope"}).status_code for _ in range(8)]
    assert 429 in codes


def test_overview_and_forecast_scenarios(client):
    o = client.get("/api/overview").json()
    assert o["cash_minor"] == 3200000 and o["open_invoices"] == 16 and o["bills_to_review"] > 0
    base = client.get("/api/forecast").json()
    late = client.get("/api/forecast", params={"collect_delay_days": 14, "hire_monthly_minor": 400000, "hire_week": 3}).json()
    assert len(base["weeks"]) == 13 and late["closing_minor"] < base["closing_minor"] and late["base_closing"] == [w["closing_minor"] for w in base["weeks"]]
    assert client.get("/api/forecast", params={"collect_delay_days": 999}).status_code == 422
    assert "forecast code" in client.get("/api/forecast/explain").json()["text"]


def test_bills_documents_and_page_boxes(client):
    bills = client.get("/api/bills", params={"status": "needs_review"}).json()
    flagged = next(b for b in bills if any(f["kind"] == "wrong_total" for f in b["flags"]))
    d = client.get(f"/api/bills/{flagged['id']}").json()
    assert d["document"]["pages"] == 1 and d["lines"] and d["exceptions"]
    for f in d["document"]["extraction"]["fields"].values():
        assert f["box"] is None or all(0 <= v <= 1 for v in f["box"])
    png = client.get(f"/api/documents/{d['document']['id']}/page/1.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert client.get(f"/api/documents/{d['document']['id']}/page/9.png").status_code == 404


def test_upload_new_and_duplicate_documents(client):
    data = (ROOT / "data/heldout/documents/H001.pdf").read_bytes()
    r = client.post("/api/documents/upload", content=data, headers={"x-filename": "H001.pdf"})
    assert r.status_code == 200 and r.json()["bill_id"]
    assert client.post("/api/documents/upload", content=data, headers={"x-filename": "H001.pdf"}).json() == {"duplicate": True}
    assert client.post("/api/documents/upload", content=b"not a pdf", headers={"x-filename": "x.pdf"}).status_code == 415
    assert client.post("/api/documents/upload", content=b"", headers={"x-filename": "x.pdf"}).status_code == 413


def test_edit_approve_and_post_in_draft_mode(client):
    bills = client.get("/api/bills", params={"status": "needs_review"}).json()
    block = next(b for b in bills if any(f["severity"] == "block" for f in b["flags"]))
    assert client.post(f"/api/bills/{block['id']}/approve", json={}).status_code == 409
    clean = next(b for b in bills if not b["flags"] and b["total_minor"] > 0)
    r = client.patch(f"/api/bills/{clean['id']}", json={"po_number": "PO-9999", "total_minor": clean["total_minor"] + 5})
    assert r.status_code == 200 and "wrong_total" in r.json()["findings"]  # editing re runs the checks
    client.patch(f"/api/bills/{clean['id']}", json={"total_minor": clean["total_minor"]})
    # the wrong total raised a blocking finding, and putting the total back removed it: the bill still remembers it, so the owner who made both edits needs a real reason (round 3)
    assert client.post(f"/api/bills/{clean['id']}/approve", json={}).status_code == 409
    assert client.post(f"/api/bills/{clean['id']}/approve", json={"note": "Put the total back to what the page shows"}).json()["status"] == "approved"
    res = client.post(f"/api/bills/{clean['id']}/post").json()
    assert res["posted"] is False and "draft" in res["reason"].lower()
    assert client.patch(f"/api/bills/{clean['id']}", json={"po_number": "x"}).status_code == 409  # approved bills are not edited
    assert client.post(f"/api/bills/{block['id']}/approve", json={"note": "Phoned the vendor, total confirmed"}).json()["status"] == "approved"


def test_kill_switch_is_owner_only_and_audited(client):
    assert client.post("/api/settings", json={"kill_switch": True}, headers=approver(client)).status_code == 403
    assert client.post("/api/settings", json={"kill_switch": True}).json()["kill_switch"] is True
    assert client.post("/api/settings", json={"kill_switch": False}).json()["kill_switch"] is False
    assert client.get("/api/audit/verify").json()["ok"] is True
    assert any(a["action"] == "settings.kill_switch" for a in client.get("/api/audit").json())


def test_approvals_drive_reminders(client, seeded):
    client.post("/api/demo/advance", json={"hours": 24 * 14})
    client.post("/api/demo/tick")
    pend = [a for a in client.get("/api/approvals").json() if a["status"] == "pending" and a["action"] == "reminder.send"]
    assert pend
    assert client.post(f"/api/approvals/{pend[0]['id']}/decide", json={"approve": True, "note": "ok"}, headers=approver(client)).json()["status"] == "approved"
    col = client.get("/api/collections").json()
    assert any(r["status"] == "approved" for r in col["reminders"]) and col["ladder"][0]["tone"] == "friendly"
    assert client.post(f"/api/approvals/{pend[0]['id']}/decide", json={"approve": True}).status_code == 409  # already decided


def test_collections_actions(client):
    inv = next(i for i in client.get("/api/invoices", params={"status": "open"}).json() if not i["disputed"])
    assert client.post(f"/api/invoices/{inv['id']}/dispute", json={"disputed": True, "note": "short delivery"}).json()["disputed"] is True
    assert client.post(f"/api/invoices/{inv['id']}/promise", json={"promised_on": "2026-12-20", "amount_minor": 1000}).status_code == 200
    link = client.post(f"/api/invoices/{inv['id']}/payment-link").json()
    assert link["real"] is False and "example.test" in link["url"]  # draft mode makes a placeholder
    assert client.get("/api/aging").json()["total_minor"] > 0
    cust = client.get("/api/customers").json()[0]
    assert client.post(f"/api/customers/{cust['id']}/opt-out", json={"opted_out": True}).json()["opted_out"] is True


def test_bank_import_dedupe_manual_link_and_exceptions(client):
    csv = "Date,Description,Amount\n2026-11-30,ACH CREDIT UNKNOWN PERSON,12.34\n"
    r = client.post("/api/bank/import", json={"text": csv}).json()
    assert r["added"] == 1 and client.post("/api/bank/import", json={"text": csv}).json()["added"] == 0
    assert client.post("/api/bank/import", json={"text": "a,b\n1,2"}).status_code == 422
    rows = client.get("/api/bank/transactions", params={"status": "exception", "limit": 50}).json()["rows"]
    t = next(x for x in rows if x["description"].endswith("UNKNOWN PERSON"))
    cands = client.get("/api/bank/candidates", params={"txn_id": t["id"]}).json()
    assert cands and client.post("/api/bank/links", json={"txn_id": t["id"], "kind": "invoice", "target_id": cands[0]["id"], "amount_minor": 99999999}).status_code == 409
    m = client.post("/api/bank/links", json={"txn_id": t["id"], "kind": "invoice", "target_id": cands[0]["id"], "amount_minor": 1234}).json()
    assert client.delete(f"/api/bank/matches/{m['match_id']}").json()["ok"]
    ex = client.get("/api/exceptions").json()
    assert ex and client.post(f"/api/exceptions/{ex[0]['id']}/resolve").json()["status"] == "resolved"


def test_reports_integrations_demo(client):
    pdf = client.get("/api/reports/month-end.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    integ = client.get("/api/integrations").json()
    assert {a["category"] for a in integ["adapters"]} == {"accounting", "payments", "inbox", "email"} and all(not a["live_verified"] for a in integ["adapters"])
    assert client.post("/api/integrations/accounting/test").json()["ok"] is True
    assert client.post("/api/integrations/nope/test").status_code == 404
    assert client.post("/api/demo/reset", headers=approver(client)).status_code == 403
    assert client.post("/api/demo/reset").status_code == 200
    assert client.post("/api/demo/stress-bank", json={"n": 5000}).json()["added"] == 5000
    assert client.get("/api/bank/transactions", params={"limit": 6000}).json()["total"] >= 5184


def viewer(client):
    r = client.post("/api/auth/login", json={"email": "viewer@example.test", "password": "demo-password-1"})
    assert r.status_code == 200 and r.json()["role"] == "viewer"
    return {"x-session": r.json()["token"]}


def test_viewer_reads_everything_and_changes_nothing(client):
    h = viewer(client)
    for path in ("/api/overview", "/api/bills", "/api/forecast", "/api/approvals", "/api/audit"):
        assert client.get(path, headers=h).status_code == 200, path
    assert client.post("/api/settings", json={"kill_switch": True}, headers=h).status_code == 403
    assert client.post("/api/approvals/1/decide", json={"approve": True}, headers=h).status_code == 403
    assert client.post("/api/demo/reset", headers=h).status_code == 403
    assert client.post("/api/bills/1/approve", json={}, headers=h).status_code == 403
    assert client.post("/api/bank/match/run", headers=h).status_code == 403


def test_the_model_backend_switch_picks_the_stand_in_by_default(seeded):
    from booklantern.context import Ctx  # noqa: F401
    from sendora_core.llm import LLM  # noqa: F401

    with seeded.factory() as s:
        assert seeded.settings.effective_llm_backend.value == "offline"
        assert seeded.llm(s).backend.__class__.__name__ == "OfflineBackend"
