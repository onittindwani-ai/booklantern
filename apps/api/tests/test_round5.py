"""Fixes from the Round 5 walk through the screens: each test fails on the code before the fix."""

from pathlib import Path

from sqlalchemy import select

from booklantern import bankservice
from booklantern.models import Bill, Match, PromiseToPay
from .test_api import client  # noqa: F401  (the fixture)

ROOT = Path(__file__).resolve().parents[3]


def _bills(client, status="needs_review,inbox"):
    return client.get(f"/api/bills?status={status}").json()


def _blank_scan(client):
    return next(b for b in _bills(client) if not b["vendor"] and b["total_minor"] == 0)


def test_a_blank_scan_cannot_be_approved_until_it_has_a_vendor_a_date_and_a_total(client):
    b = _blank_scan(client)
    r = client.post(f"/api/bills/{b['id']}/approve", json={"note": "just do it"})
    assert r.status_code == 409 and "vendor" in r.json()["error"]["message"] and "total" in r.json()["error"]["message"]
    assert client.patch(f"/api/bills/{b['id']}", json={"vendor": "Cobalt Office Supply", "number": "X-1", "issue_date": "2026-11-20", "subtotal_minor": 10000, "tax_minor": 0, "total_minor": 10000}).status_code == 200
    assert client.post(f"/api/bills/{b['id']}/approve", json={"note": ""}).status_code == 200


def test_a_vendor_typed_by_hand_is_saved_and_matched_to_the_vendor_list(client):
    b = _blank_scan(client)
    assert client.patch(f"/api/bills/{b['id']}", json={"vendor": "cobalt office supply"}).status_code == 200
    got = client.get(f"/api/bills/{b['id']}").json()
    assert got["vendor"] == "Cobalt Office Supply" and got["vendor_id"] is not None
    assert client.patch(f"/api/bills/{b['id']}", json={"vendor": "Somebody New Ltd"}).status_code == 200
    got = client.get(f"/api/bills/{b['id']}").json()
    assert got["vendor"] == "Somebody New Ltd" and got["vendor_id"] is None
    assert any(f["kind"] == "unknown_vendor" for f in got["flags"])


def test_an_empty_amount_or_a_due_date_before_the_bill_date_is_refused_not_a_crash(client):
    b = _bills(client)[3]
    assert client.patch(f"/api/bills/{b['id']}", json={"total_minor": None}).status_code == 422
    assert client.patch(f"/api/bills/{b['id']}", json={"issue_date": "2026-11-20", "due_date": "2026-11-01"}).status_code == 422
    assert client.patch(f"/api/bills/{b['id']}", json={"currency": "eur"}).status_code == 200
    assert client.get(f"/api/bills/{b['id']}").json()["currency"] == "EUR"


def test_a_row_that_is_gone_answers_404_never_500(client):
    for method, path, body in [("post", "/api/bills/99999/approve", {"note": ""}), ("post", "/api/bills/99999/reject", {"reason": "x"}), ("post", "/api/bills/99999/post", {}),
                               ("post", "/api/invoices/99999/promise", {"promised_on": "2026-12-20", "amount_minor": 100}), ("post", "/api/invoices/99999/dispute", {"disputed": True}),
                               ("post", "/api/invoices/99999/payment-link", {}), ("post", "/api/customers/99999/opt-out", {"opted_out": True}),
                               ("post", "/api/bank/links", {"txn_id": 99999, "kind": "invoice", "target_id": 1, "amount_minor": 1}), ("post", "/api/bank/matches/99999/confirm", {}),
                               ("delete", "/api/bank/matches/99999", None), ("post", "/api/exceptions/99999/resolve", {})]:
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (path, r.status_code)


def test_closing_a_blocking_finding_needs_a_written_reason_and_a_plain_one_does_not(client):
    ex = client.get("/api/exceptions").json()
    block = next(e for e in ex if e["severity"] == "block")
    assert client.post(f"/api/exceptions/{block['id']}/resolve", json={"note": "  "}).status_code == 409
    assert client.post(f"/api/exceptions/{block['id']}/resolve").status_code == 409
    warn = next(e for e in ex if e["severity"] != "block")
    assert client.post(f"/api/exceptions/{warn['id']}/resolve").status_code == 200
    assert client.post(f"/api/exceptions/{block['id']}/resolve", json={"note": "Vendor sent a corrected total"}).status_code == 200
    audit = client.get("/api/audit?limit=5").json()
    assert any(a["action"] == "exception.resolved" and a["detail"].get("note") == "Vendor sent a corrected total" for a in audit)


def test_a_bank_statement_in_another_currency_or_with_a_zero_line_is_refused_and_the_balance_is_unchanged(client):
    before = client.get("/api/overview").json()["cash_minor"]
    r = client.post("/api/bank/import", json={"text": "Date,Description,Amount,Currency,Reference\n2026-11-30,TEST EUR,12.34,EUR,Q2\n", "name": "e.csv"})
    assert r.status_code == 422 and "EUR" in r.json()["error"]["message"]
    r = client.post("/api/bank/import", json={"text": "Date,Description,Amount,Currency,Reference\n2026-11-30,TEST ZERO,0,USD,Q3\n", "name": "z.csv"})
    assert r.status_code == 422 and "zero" in r.json()["error"]["message"]
    assert client.get("/api/overview").json()["cash_minor"] == before


def test_the_balance_counts_only_lines_in_the_account_currency(seeded):
    from booklantern.models import BankAccount, BankTransaction

    with seeded.factory() as s:
        acct = s.scalars(select(BankAccount)).first()
        before = bankservice.balance(s)
        s.add(BankTransaction(bank_account_id=acct.id, ref="E1", posted_on=seeded.today(s), description="STRAY EUR", amount_minor=123456, currency="EUR", row_hash="stray-eur", batch="t"))
        s.flush()
        assert bankservice.balance(s) == before


def test_money_that_came_in_cannot_be_linked_to_a_bill_and_money_that_went_out_not_to_an_invoice(client):
    rows = client.get("/api/bank/transactions?limit=300").json()["rows"]
    deposit = next(r for r in rows if r["amount_minor"] > 0 and r["status"] != "matched")
    withdrawal = next(r for r in rows if r["amount_minor"] < 0 and r["status"] != "matched")
    bill = _bills(client)[0]
    inv = client.get("/api/invoices?status=open").json()[0]
    assert client.post("/api/bank/links", json={"txn_id": deposit["id"], "kind": "bill", "target_id": bill["id"], "amount_minor": 100}).status_code == 409
    assert client.post("/api/bank/links", json={"txn_id": withdrawal["id"], "kind": "invoice", "target_id": inv["id"], "amount_minor": 100}).status_code == 409


def test_a_promise_in_the_past_or_for_more_than_is_owed_is_refused_and_a_new_promise_replaces_the_old_one(client, seeded):
    inv = next(i for i in client.get("/api/invoices?status=open").json() if not i["disputed"])
    today = client.get("/api/demo/state").json()["now"][:10]
    assert client.post(f"/api/invoices/{inv['id']}/promise", json={"promised_on": "2020-01-01", "amount_minor": 100}).status_code == 422
    assert client.post(f"/api/invoices/{inv['id']}/promise", json={"promised_on": today, "amount_minor": inv["outstanding_minor"] + 1}).status_code == 422
    first = client.post(f"/api/invoices/{inv['id']}/promise", json={"promised_on": "2026-12-20", "amount_minor": 100}).json()["id"]
    second = client.post(f"/api/invoices/{inv['id']}/promise", json={"promised_on": "2026-12-10", "amount_minor": 100}).json()["id"]
    with seeded.factory() as s:
        assert s.get(PromiseToPay, first).status == "replaced" and s.get(PromiseToPay, second).status == "open"


def test_a_paid_invoice_takes_no_promise_and_no_payment_link(client):
    paid = client.get("/api/invoices?status=paid").json()[0]
    assert client.post(f"/api/invoices/{paid['id']}/promise", json={"promised_on": "2026-12-20", "amount_minor": 100}).status_code == 409
    assert client.post(f"/api/invoices/{paid['id']}/payment-link").status_code == 409


def test_approving_a_reminder_on_the_collections_page_closes_its_request_on_the_approvals_page(client):
    client.post("/api/demo/advance", json={"hours": 24})
    client.post("/api/demo/tick")
    pending = [a for a in client.get("/api/approvals").json() if a["status"] == "pending"]
    assert pending, "the demo day drafts a reminder and asks for approval"
    rid = pending[0]["payload"]["reminder_id"]
    assert client.post(f"/api/reminders/{rid}/approve").status_code == 200
    now = {a["id"]: a["status"] for a in client.get("/api/approvals").json()}
    assert now[pending[0]["id"]] == "approved"
    assert client.get("/api/overview").json()["pending_approvals"] == 0


def test_cancelling_a_reminder_on_the_collections_page_rejects_its_request(client):
    client.post("/api/demo/advance", json={"hours": 24})
    client.post("/api/demo/tick")
    pending = [a for a in client.get("/api/approvals").json() if a["status"] == "pending"]
    rid = pending[0]["payload"]["reminder_id"]
    assert client.post(f"/api/reminders/{rid}/cancel").status_code == 200
    assert {a["id"]: a["status"] for a in client.get("/api/approvals").json()}[pending[0]["id"]] == "rejected"


def test_a_photo_of_a_bill_is_served_as_a_picture_for_the_review_page(client):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    r = client.post("/api/documents/upload", content=png, headers={"x-filename": "photo.png", "content-type": "application/octet-stream"})
    assert r.status_code == 200
    doc = client.get(f"/api/bills/{r.json()['bill_id']}").json()["document"]
    page = client.get(f"/api/documents/{doc['id']}/page/1.png")
    assert page.status_code == 200 and page.headers["content-type"] == "image/png" and page.content == png


def test_reset_leaves_no_moment_without_tables(seeded):
    """The reset empties the tables and reloads them in one transaction. It must not drop them (a page refreshing at that moment got a 500)."""
    from booklantern import demo
    from sqlalchemy import event

    statements: list[str] = []
    event.listen(seeded.factory.kw["bind"], "before_cursor_execute", lambda c, cur, stmt, p, ctx, many: statements.append(stmt))
    with seeded.factory() as s:
        demo.reset(s, seeded)
    assert not any(st.lstrip().upper().startswith(("DROP TABLE", "CREATE TABLE")) for st in statements)


def test_the_month_end_pdf_uses_plain_words_and_never_cuts_a_sentence(client):
    import io

    import pypdfium2 as pdfium

    r = client.get("/api/reports/month-end.pdf")
    assert r.status_code == 200
    doc = pdfium.PdfDocument(io.BytesIO(r.content))
    text = " ".join(doc[i].get_textpage().get_text_range() for i in range(len(doc))).replace("\r\n", " ").replace("\n", " ")
    for raw in ("wrong_total", "possible_duplicate_line", "unmatched_line", "bank_txn", "unreadable_document", "wrong_company"):
        assert raw not in text
    assert "Total does not add up" in text and "Bank line 29" in text and "Not due yet" in text and "1 to 30 days late" in text
    assert "ask the vendor or your accountant." in text
