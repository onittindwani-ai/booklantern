"""Round 2 audit fixes. Each test fails on the code before the fix."""

from __future__ import annotations

import pytest

from .test_api import approver, client  # noqa: F401  (the fixture)


def _clean_bill(client):
    """A bill waiting for review that has a vendor with a bank account on file and no blocking finding of its own."""
    for b in client.get("/api/bills?status=needs_review").json():
        d = client.get(f"/api/bills/{b['id']}").json()
        if d.get("vendor_id") and d.get("bank_account") and not any(e["severity"] == "block" and e["status"] == "open" for e in d["exceptions"]) and d["total_minor"] > 0 and d["issue_date"]:
            return d
    raise AssertionError("no clean bill in the seed")


def _blocks(client, bill_id):
    return [e for e in client.get(f"/api/bills/{bill_id}").json()["exceptions"] if e["severity"] == "block"]


def test_an_approver_cannot_clear_their_own_bank_detail_edit_and_approve_alone(client):  # noqa: F811
    d = _clean_bill(client)
    ap = approver(client)
    assert client.patch(f"/api/bills/{d['id']}", json={"bank_account": "SMPL-9999-0000"}, headers=ap).status_code == 200
    block = next(e for e in _blocks(client, d["id"]) if e["kind"] == "bank_detail_changed")
    assert client.post(f"/api/bills/{d['id']}/approve", json={"note": ""}, headers=ap).status_code == 409  # the old rule held this far
    # the person who made the edit may not close the finding it raised ...
    assert client.post(f"/api/exceptions/{block['id']}/resolve", json={"note": "it is fine"}, headers=ap).status_code == 409
    # ... and still cannot approve once somebody else has closed it
    assert client.post(f"/api/exceptions/{block['id']}/resolve", json={"note": "Phoned the vendor on the number on file"}).status_code == 200
    assert client.post(f"/api/bills/{d['id']}/approve", json={"note": "second attempt"}, headers=ap).status_code == 409
    assert client.get(f"/api/bills/{d['id']}").json()["status"] == "needs_review"


def test_a_closed_finding_comes_back_when_the_check_fires_again(client):  # noqa: F811
    d = _clean_bill(client)
    assert client.patch(f"/api/bills/{d['id']}", json={"bank_account": "SMPL-9999-0000"}).status_code == 200
    block = next(e for e in _blocks(client, d["id"]) if e["kind"] == "bank_detail_changed")
    assert client.post(f"/api/exceptions/{block['id']}/resolve", json={"note": "Phoned the vendor, the new account is right"}).status_code == 200
    assert client.patch(f"/api/bills/{d['id']}", json={"bank_account": "SMPL-1234-5678", "total_minor": d["total_minor"] + 100, "subtotal_minor": d["subtotal_minor"] + 100}).status_code == 200
    again = next(e for e in _blocks(client, d["id"]) if e["kind"] == "bank_detail_changed")
    assert again["status"] == "open"  # a second edit of the account is not covered by the first person's reason
    assert client.post(f"/api/bills/{d['id']}/approve", json={"note": ""}).status_code == 409


# ---- Medium 3: a hostile PDF cannot make the text layout grow without limit -------------------------------------------------------------------------

def hostile_wide_pdf(lines: int = 60, x: int = 100_000_000) -> bytes:
    """A tiny PDF whose text runs sit 100 million points to the right of the page."""
    body = "BT /F1 10 Tf\n" + "".join(f"1 0 0 1 {x} {760 - 10 * i} Tm (Total {i}) Tj\n" for i in range(lines)) + "ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(body)} >>\nstream\n{body}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def test_a_pdf_with_text_far_off_the_page_gives_a_short_layout_and_a_small_memory_peak():
    import time
    import tracemalloc

    from booklantern.extraction.cells import read_page
    from booklantern.extraction.textpages import layout_text

    data = hostile_wide_pdf()
    assert len(data) < 3000
    page = read_page(data, 0)
    assert page.cells, "the hostile file must really put text on the page for this test to mean anything"
    tracemalloc.start()
    t0 = time.monotonic()
    text = layout_text([page])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert time.monotonic() - t0 < 2 and peak < 5_000_000
    assert max(len(line) for line in text.splitlines()) < 700 and len(text) < 24_001


# ---- High: the owner and a second person -------------------------------------------------------------------------------------------------------------

def test_the_owner_edits_and_closes_the_finding_and_a_second_person_approves(client):  # noqa: F811
    d = _clean_bill(client)
    assert client.patch(f"/api/bills/{d['id']}", json={"bank_account": "SMPL-9999-0000"}).status_code == 200
    block = next(e for e in _blocks(client, d["id"]) if e["kind"] == "bank_detail_changed")
    assert client.post(f"/api/exceptions/{block['id']}/resolve", json={"note": "Phoned the vendor, the new account is right"}).status_code == 200  # the owner may close a finding on their own edit, with a reason
    assert client.post(f"/api/bills/{d['id']}/approve", json={"note": ""}).status_code == 409  # but the owner approving it too needs a written reason
    r = client.post(f"/api/bills/{d['id']}/approve", json={"note": ""}, headers=approver(client))
    assert r.status_code == 200 and r.json()["status"] == "approved"  # someone else who did neither: no override needed
    log = client.get("/api/audit?limit=20").json()
    assert any(a["action"] == "exception.resolved" and a["detail"].get("self_review") is True for a in log)


def test_the_owner_can_approve_their_own_reviewed_bill_with_a_written_reason_and_it_is_audited(client):  # noqa: F811
    d = _clean_bill(client)
    assert client.patch(f"/api/bills/{d['id']}", json={"bank_account": "SMPL-9999-0000"}).status_code == 200
    block = next(e for e in _blocks(client, d["id"]) if e["kind"] == "bank_detail_changed")
    assert client.post(f"/api/exceptions/{block['id']}/resolve", json={"note": "Phoned the vendor on the number on file"}).status_code == 200
    assert client.post(f"/api/bills/{d['id']}/approve", json={"note": "Owner decision: the vendor confirmed the new account by phone"}).status_code == 200
    log = client.get("/api/audit?limit=20").json()
    assert any(a["action"] == "bill.approved" and a["detail"].get("self_review") is True and a["detail"].get("override") for a in log)


def test_a_bill_nobody_touched_is_approved_by_one_person_as_before(client):  # noqa: F811
    d = _clean_bill(client)
    assert client.post(f"/api/bills/{d['id']}/approve", json={"note": ""}, headers=approver(client)).status_code == 200


def test_an_approver_cannot_close_a_finding_on_a_bill_they_edited_even_when_it_is_the_only_one_open(client):  # noqa: F811
    d = _clean_bill(client)
    ap = approver(client)
    assert client.patch(f"/api/bills/{d['id']}", json={"bank_account": "SMPL-9999-0000"}, headers=ap).status_code == 200
    ids = [e["id"] for e in _blocks(client, d["id"]) if e["status"] == "open"]
    assert ids and all(client.post(f"/api/exceptions/{i}/resolve", json={"note": "fine"}, headers=ap).status_code == 409 for i in ids)


# ---- Low: CSRF header, login lock out, account clash -----------------------------------------------------------------------------------------------

def test_a_change_made_with_the_cookie_alone_needs_the_custom_header(seeded):
    from fastapi.testclient import TestClient

    from booklantern.api.app import create_app

    app = create_app(seeded.settings, seeded)
    c = TestClient(app)
    tok = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    jar = TestClient(app, cookies={"sx_session": tok})  # what a browser holds: the cookie, and nothing else
    bill = next(b for b in jar.get("/api/bills").json())
    assert jar.get(f"/api/bills/{bill['id']}").status_code == 200  # reading needs no header
    r = jar.post(f"/api/bills/{bill['id']}/post")  # a post with no body, as a form on another site could send it
    assert r.status_code == 403 and "x-booklantern" in r.json()["error"]["message"]
    assert jar.post(f"/api/bills/{bill['id']}/post", headers={"x-booklantern": "1"}).status_code in (200, 409)  # past the gate (the bill itself may not be postable)
    assert c.post(f"/api/bills/{bill['id']}/post", headers={"x-session": tok}).status_code in (200, 409)  # the web app's server sends the session in a header


def test_a_stranger_hammering_the_owners_email_cannot_lock_the_owner_out(seeded):
    from fastapi.testclient import TestClient

    from booklantern.api.app import create_app

    app = create_app(seeded.settings, seeded)
    for n in range(60):  # sixty different addresses, five wrong tries each
        stranger = TestClient(app, base_url="http://api.test", client=(f"203.0.113.{n + 1}", 40000))
        for _ in range(5):
            stranger.post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong"})
    owner = TestClient(app, base_url="http://api.test", client=("198.51.100.77", 40000))
    assert owner.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).status_code == 200


def test_an_approver_email_equal_to_the_owners_is_refused_at_startup(tmp_path):
    import pytest

    from booklantern.api.app import create_app
    from booklantern.config import Settings
    from sendora_core.settings import ConfigError

    kw = dict(_env_file=None, database_url=f"sqlite:///{tmp_path / 'x.sqlite3'}", session_secret="test-only-Rt7Kq2Vw9Xm4Zc8Lb3Nf6Hy1Js5Dp0Ga2Ue7Tq4Wi9", demo_mode=False, owner_password_hash="x")
    for second in ("approver_email", "viewer_email"):
        s = Settings(owner_email="Owner@Example.test", **{second: " owner@example.test "}, **kw)
        assert any("same address" in p for p in s.runtime_errors())
        with pytest.raises(ConfigError):
            create_app(s)
    Settings(owner_email="a@example.test", approver_email="b@example.test", viewer_email="c@example.test", **kw).check_runtime()  # three different people are fine


# ---- Medium 1: a bill paid by a matched bank line is paid ---------------------------------------------------------------------------------------------

def _bank_world(ctx, bill_total=10_000):
    from datetime import date

    from sqlalchemy import select

    from booklantern import setup_data
    from booklantern.models import BankAccount, BankTransaction, Bill

    with ctx.factory() as s:
        v = setup_data.create_vendor(s, ctx.settings, "owner", name="Hollis Print Co", bank_account="SMPL-5555")
        acct = BankAccount(name="Main", currency="USD", opening_minor=1_000_000, opening_date=date(2026, 1, 1))
        s.add(acct)
        s.flush()
        bill = Bill(vendor_id=v.id, vendor_name_read=v.name, number="HP-1", issue_date=date(2026, 1, 2), due_date=date(2026, 2, 1), currency="USD", subtotal_minor=bill_total, tax_minor=0, total_minor=bill_total, status="approved")
        t = BankTransaction(bank_account_id=acct.id, ref="r1", posted_on=date(2026, 1, 20), description="HOLLIS PRINT", amount_minor=-bill_total, currency="USD", row_hash="h1", batch="b")
        s.add_all([bill, t])
        s.commit()
        return bill.id, t.id


def test_a_bill_paid_by_a_matched_bank_line_is_marked_paid_and_leaves_payables_and_the_forecast(ctx):
    from datetime import date

    from sqlalchemy import select

    from booklantern import bankservice, fxservice
    from booklantern.models import Bill

    bill_id, txn_id = _bank_world(ctx)
    with ctx.factory() as s:
        before = fxservice.payables(s, ctx, date(2026, 1, 25))
        m = bankservice.link_manually(s, txn_id, "bill", bill_id, 10_000, "owner")
        bankservice.record_payments(s)
        b = s.get(Bill, bill_id)
        assert (b.status, b.paid_minor, b.paid_on) == ("paid", 10_000, date(2026, 1, 20))
        assert before == 10_000 and fxservice.payables(s, ctx, date(2026, 1, 25)) == 0  # the full bill was counted as owed after it was paid
        bankservice.unlink(s, m.id, "owner")
        s.flush()
        b = s.get(Bill, bill_id)
        assert (b.status, b.paid_minor, b.paid_on) == ("approved", 0, None)  # taking the match back makes it payable again
        assert fxservice.payables(s, ctx, date(2026, 1, 25)) == 10_000


def test_a_part_payment_lowers_what_is_owed_and_a_posted_bill_goes_back_to_posted(ctx):
    from datetime import date

    from booklantern import bankservice, fxservice
    from booklantern.models import Bill

    bill_id, txn_id = _bank_world(ctx)
    with ctx.factory() as s:
        s.get(Bill, bill_id).status, s.get(Bill, bill_id).posted_external_id = "posted_draft", "EXT-9"
        m = bankservice.link_manually(s, txn_id, "bill", bill_id, 4_000, "owner")
        bankservice.record_payments(s)
        b = s.get(Bill, bill_id)
        assert (b.status, b.paid_minor) == ("posted_draft", 4_000) and fxservice.payables(s, ctx, date(2026, 1, 25)) == 6_000
        # the rest of the money later: now it is paid
        from booklantern.models import BankTransaction
        t2 = BankTransaction(bank_account_id=s.get(BankTransaction, txn_id).bank_account_id, ref="r2", posted_on=date(2026, 1, 28), description="HOLLIS PRINT 2", amount_minor=-6_000, currency="USD", row_hash="h2", batch="b")
        s.add(t2)
        s.flush()
        m2 = bankservice.link_manually(s, t2.id, "bill", bill_id, 6_000, "owner")
        bankservice.record_payments(s)
        b = s.get(Bill, bill_id)
        assert (b.status, b.paid_minor, b.paid_on) == ("paid", 10_000, date(2026, 1, 28))
        bankservice.unlink(s, m2.id, "owner")
        s.flush()
        assert (s.get(Bill, bill_id).status, s.get(Bill, bill_id).paid_minor) == ("posted_draft", 4_000)


# ---- Medium 2: the same bill with another date is still the same bill ----------------------------------------------------------------------------------

def test_the_same_vendor_number_and_total_a_month_later_or_with_no_date_is_a_duplicate():
    from datetime import date

    from booklantern.validation import BillData, check_duplicates, norm_number

    def bill(i, number, issued, total=50_000, vendor=7):
        return BillData(i, vendor, number, issued, "USD", "", "", "", total, 0, total, [total])

    first = bill(1, "INV-0042", date(2026, 10, 1))
    for later in (bill(2, "INV-0042", date(2026, 11, 2)), bill(3, "inv 42", None), bill(4, " Inv.42 ", date(2027, 1, 1))):
        f = check_duplicates(later, [first])
        assert [x.kind for x in f] == ["duplicate_exact"] and f[0].severity == "block", later.number
    assert check_duplicates(bill(5, "INV-0043", date(2026, 11, 2)), [first]) == []  # another number is another bill
    assert check_duplicates(bill(6, "INV-0042", date(2026, 11, 2), total=50_001), [first]) == []  # another amount is not flagged here
    assert check_duplicates(bill(7, "", date(2026, 12, 1)), [bill(8, "", date(2026, 11, 1))]) == []  # two bills with no number say nothing about each other (see the test below)
    assert norm_number("1-0042") != norm_number("10042") and norm_number("A-007") == norm_number("a7") and norm_number("100") == "100"


def test_a_bill_sent_again_a_month_later_is_blocked_through_the_whole_pipeline(ctx):
    from datetime import date

    from booklantern import intake, setup_data
    from booklantern.models import Bill, ExceptionItem
    from sqlalchemy import select

    with ctx.factory() as s:
        v = setup_data.create_vendor(s, ctx.settings, "owner", name="Hollis Print Co", bank_account="SMPL-5555")
        a = Bill(vendor_id=v.id, vendor_name_read=v.name, number="HP-0042", issue_date=date(2026, 10, 1), currency="USD", subtotal_minor=5000, total_minor=5000, status="needs_review", bank_account="SMPL-5555")
        b = Bill(vendor_id=v.id, vendor_name_read=v.name, number="hp 42", issue_date=date(2026, 11, 3), currency="USD", subtotal_minor=5000, total_minor=5000, status="needs_review", bank_account="SMPL-5555")
        s.add_all([a, b])
        s.flush()
        intake.validate_bill(s, ctx, b)
        kinds = {e.kind: e.severity for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == b.id))}
        assert kinds.get("duplicate_exact") == "block"


# ---- Medium 3: a document that kills the reader is given up on ------------------------------------------------------------------------------------

class _EmptyInbox:
    def fetch_documents(self):
        return []

    def acknowledge(self, acks):
        return None


def test_a_document_that_keeps_killing_the_reader_goes_to_a_person_and_stops_blocking_intake(ctx, monkeypatch):
    import pytest
    from sqlalchemy import select

    from booklantern import intake
    from booklantern.models import Document, ExceptionItem

    ctx.adapters.inbox = _EmptyInbox()
    with ctx.factory() as s:
        poison = intake.ingest(s, ctx, "poison.pdf", hostile_wide_pdf(10))
        s.commit()
        poison_id = poison.id
    real = intake.process_document

    def dies_on_poison(session, c, doc, data=None):
        if doc.id == poison_id:
            raise SystemExit("the reader was killed")  # what an out of memory kill looks like to the program: nothing catches it, nothing is saved
        return real(session, c, doc, data)

    monkeypatch.setattr(intake, "process_document", dies_on_poison)
    for attempt in range(intake.MAX_READ_ATTEMPTS):
        with ctx.factory() as s, pytest.raises(SystemExit):
            intake.run_intake(s, ctx)
    with ctx.factory() as s:
        assert s.get(Document, poison_id).read_attempts == intake.MAX_READ_ATTEMPTS and s.get(Document, poison_id).status == "new"
        good = intake.ingest(s, ctx, "later.pdf", hostile_wide_pdf(3, x=100))  # a normal document that arrived behind it
        s.commit()
        good_id = good.id
    with ctx.factory() as s:
        out = intake.run_intake(s, ctx)  # this pass does not read the poison file again, and goes on to the next document
        s.commit()
    with ctx.factory() as s:
        assert s.get(Document, poison_id).status == "unreadable" and s.get(Document, good_id).status != "new" and out["processed"] == 1
        assert s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "unreadable_document", ExceptionItem.ref_id == poison_id)).first() is not None


# ---- Medium 4: the posted draft carries the approved bill, and a wrong total is not a success -----------------------------------------------------

def _draft(**kw):
    from booklantern.adapters.base import DraftBill

    base = dict(vendor_name="Alderbank Packaging Ltd", number="ALD-1", issue_date="2026-11-01", due_date="2026-12-01", currency="USD",
                lines=[{"description": "Cartons", "quantity": 2, "unit_minor": 500, "total_minor": 1000}, {"description": "Tape", "quantity": 1, "unit_minor": 250, "total_minor": 250}],
                subtotal_minor=1250, tax_minor=100, total_minor=1350)
    base.update(kw)
    return DraftBill(**base)


def test_quickbooks_draft_carries_the_tax_and_reports_the_total_it_holds():
    from fastapi.testclient import TestClient

    from booklantern.adapters.quickbooks import QuickBooksAccounting
    from mock.qbo_mock import QboMock
    from sendora_core.settings import Mode

    from .test_adapters import S

    q = QboMock()
    s = S(mode=Mode.LIVE, accounting_write=True, qbo_client_id="mock-client", qbo_client_secret="mock-secret", qbo_refresh_token="mock-refresh-1", qbo_realm_id=q.realm_id)
    a = QuickBooksAccounting(s, client=TestClient(q.app, base_url="https://qbo.example.test"), token_client=TestClient(q.app, base_url="https://oauth.example.test"))
    made = a.create_draft_bill(_draft())
    sent = next(iter(q.bills.values()))
    assert sent["TxnTaxDetail"]["TotalTax"] == 1.0 and made.total_minor == 1350 and made.external_id == sent["Id"]  # without the tax the vendor held 1250


def test_xero_draft_carries_the_tax_and_reports_the_total_it_holds():
    from fastapi.testclient import TestClient

    from booklantern.adapters.others import XeroAccounting
    from mock.accounting_mocks import XeroMock
    from sendora_core.settings import Mode

    from .test_adapters import S

    x = XeroMock()
    a = XeroAccounting(S(mode=Mode.LIVE, accounting_write=True, xero_access_token="mock-xero-token", xero_tenant_id="mock-tenant-1"), client=TestClient(x.app, base_url="https://x.example.test"))
    made = a.create_draft_bill(_draft())
    items = x.invoices[0]["LineItems"]
    assert round(sum(i["TaxAmount"] for i in items), 2) == 1.0 and made.total_minor == 1350
    assert a.create_draft_bill(_draft(lines=[], subtotal_minor=1250)).total_minor == 1350  # a bill with no readable lines is still posted, with its subtotal on one line


def test_akaunting_draft_carries_lines_and_tax_and_reports_the_total_it_holds():
    from fastapi.testclient import TestClient

    from booklantern.adapters.others import AkauntingAccounting
    from mock.accounting_mocks import AkauntingMock
    from sendora_core.settings import Mode

    from .test_adapters import S

    k = AkauntingMock(require_contact=False)
    a = AkauntingAccounting(S(mode=Mode.LIVE, accounting_write=True, akaunting_base_url="https://a.example.test", akaunting_user="owner@example.test", akaunting_password="mock-password"),
                            client=TestClient(k.app, base_url="https://a.example.test"))
    made = a.create_draft_bill(_draft())
    assert len(k.documents[0]["items"]) == 3 and made.total_minor == 1350  # two lines and the tax; the old request sent a document with no amounts at all


def _sub(tmp_path):
    (tmp_path / "two").mkdir()
    return tmp_path / "two"


def _live(tmp_path, accounting):
    from sqlalchemy import select

    from booklantern.models import Bill

    from .test_hardening_money import approved_bill, live_ctx

    ctx = live_ctx(tmp_path)
    ctx.adapters.accounting = accounting
    return ctx, approved_bill


class _Reports:
    def __init__(self, total_minor):
        self.total_minor, self.calls = total_minor, []

    def create_draft_bill(self, draft):
        from booklantern.adapters.base import PostedDraft

        self.calls.append(draft)
        return PostedDraft(f"EXT-{len(self.calls)}", self.total_minor, draft.currency)


def test_a_draft_that_comes_back_with_another_total_is_not_recorded_as_posted(tmp_path):
    from sqlalchemy import select

    from booklantern import posting
    from booklantern.models import Bill, ExceptionItem

    acc = _Reports(total_minor=1050)  # the accounting system dropped 0.50 somewhere
    ctx, approved_bill = _live(tmp_path, acc)
    with ctx.factory() as s:
        b = approved_bill(s)
        out = posting.post_draft(s, ctx, b.id, "owner")
        assert out["posted"] is False and out["needs_review"] is True and out["external_id"] == "EXT-1" and "EXT-1" in out["reason"]
        row = s.get(Bill, b.id)
        assert row.status == "needs_review" and row.posted_external_id == "EXT-1"  # not posted_draft, and the draft's id is kept so a person can remove it
        assert s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "post_total_mismatch", ExceptionItem.ref_id == b.id, ExceptionItem.severity == "block")).first() is not None
        with pytest.raises(ValueError):  # it cannot be approved again without looking at the finding
            posting.approve(s, b.id, "owner")
        # a person fixes it and approves again with a reason: the new try uses a new idempotency key, so the wrong draft is not handed back
        posting.approve(s, b.id, "owner", "Removed draft EXT-1 in the accounting system and checked the lines")
        acc.total_minor = 1000
        out = posting.post_draft(s, ctx, b.id, "owner")
        assert out["posted"] is True and acc.calls[0].idempotency_key != acc.calls[1].idempotency_key and s.get(Bill, b.id).status == "posted_draft"
        assert s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "post_total_mismatch", ExceptionItem.ref_id == b.id)).first() is None  # nothing left open about the wrong draft


def test_a_draft_with_the_right_total_is_recorded_and_an_adapter_that_reports_none_still_works(tmp_path):
    from booklantern import posting
    from booklantern.models import Bill

    ctx, approved_bill = _live(tmp_path, _Reports(total_minor=1000))
    with ctx.factory() as s:
        b = approved_bill(s)
        assert posting.post_draft(s, ctx, b.id, "owner")["posted"] is True and s.get(Bill, b.id).status == "posted_draft"
    ctx2, approved_bill = _live(_sub(tmp_path), _Reports(total_minor=None))
    with ctx2.factory() as s:
        b = approved_bill(s)
        assert posting.post_draft(s, ctx2, b.id, "owner")["posted"] is True  # the CSV and offline adapters read nothing back: nothing to compare


def test_a_network_error_while_posting_gives_a_safe_message_an_audit_row_and_puts_the_bill_back(tmp_path):
    import httpx
    from sqlalchemy import select

    from booklantern import posting
    from booklantern.models import Bill
    from sendora_core.models import AuditEntry

    class Unreachable:
        def create_draft_bill(self, draft):
            raise httpx.ConnectError("secret-host.internal refused the connection")

    ctx, approved_bill = _live(tmp_path, Unreachable())
    with ctx.factory() as s:
        b = approved_bill(s)
        out = posting.post_draft(s, ctx, b.id, "owner")
        assert out["posted"] is False and "ConnectError" in out["reason"] and "secret-host" not in out["reason"]
        assert s.get(Bill, b.id).status == "approved"
        assert s.scalars(select(AuditEntry).where(AuditEntry.action == "bill.post_skipped", AuditEntry.target == f"bill:{b.id}")).first() is not None


# ---- Low ------------------------------------------------------------------------------------------------------------------------------------------

def test_an_edit_that_loses_the_race_with_an_approval_changes_nothing(client, monkeypatch):  # noqa: F811
    from sqlalchemy import update

    from booklantern.api import routes_write
    from booklantern.models import Bill

    d = _clean_bill(client)
    ctx = client.app.state.ctx
    real = routes_write._found

    def approved_meanwhile(obj, what):
        out = real(obj, what)
        if what == "bill":  # the bill was read as waiting for review, and is approved by someone else before this edit writes
            with ctx.factory() as other:
                other.execute(update(Bill).where(Bill.id == d["id"]).values(status="approved"))
                other.commit()
        return out

    monkeypatch.setattr(routes_write, "_found", approved_meanwhile)
    r = client.patch(f"/api/bills/{d['id']}", json={"total_minor": d["total_minor"] + 5, "subtotal_minor": d["subtotal_minor"] + 5})
    assert r.status_code == 409
    monkeypatch.undo()
    got = client.get(f"/api/bills/{d['id']}").json()
    assert got["status"] == "approved" and got["total_minor"] == d["total_minor"]


def test_the_csv_adapter_names_a_missing_column_and_a_bad_amount_instead_of_a_key_error(tmp_path):
    from booklantern.adapters.others import CsvAccounting
    from sendora_core.adapters import AdapterError
    from sendora_core.settings import Mode

    from .test_adapters import S

    a = CsvAccounting(S(csv_folder=str(tmp_path), mode=Mode.LIVE))
    (tmp_path / "invoices.csv").write_text("Number,Customer,Total,Due\nINV-1,Marlowe Bakery,100.00,2026-12-31\n")
    with pytest.raises(AdapterError, match="Balance"):
        a.list_open_invoices()
    (tmp_path / "invoices.csv").write_text("Number,Customer,Total,Balance,Due\nINV-1,Marlowe Bakery,n/a,50.00,2026-12-31\n")
    with pytest.raises(AdapterError, match="line 2"):
        a.list_open_invoices()
    (tmp_path / "invoices.csv").write_text("﻿Number,Customer,Total,Balance,Due\nINV-1,Marlowe Bakery,100.00,50.00,2026-12-31\nINV-2,Paid Ltd,80.00,0.00,2026-12-31\nINV-3,Blank Ltd,80.00,,2026-12-31\n")
    got = a.list_open_invoices()
    assert [i.number for i in got] == ["INV-1"] and got[0].balance_minor == 5000  # a byte order mark from a spreadsheet is fine, paid or blank rows are not open invoices


def test_a_reminder_is_never_sent_twice_when_the_save_after_sending_fails(tmp_path, monkeypatch):
    from sqlalchemy import select

    from booklantern import collections
    from booklantern.models import Reminder
    from sendora_core.models import AuditEntry

    from .conftest import freeze_clock
    from .test_hardening_money import PINNED_NOW, CountingEmail, add_customer_invoice, live_ctx

    freeze_clock(monkeypatch, PINNED_NOW)  # reminders only go out on business days in business hours, so the test never depends on the day it runs
    ctx = live_ctx(tmp_path)
    ctx.adapters.email = CountingEmail()
    with ctx.factory() as s:
        inv = add_customer_invoice(s, ctx)
        r = Reminder(invoice_id=inv.id, step=1, tone="friendly", status="approved", scheduled_for=ctx.now(s), subject="Reminder", body="Please pay")
        s.add(r)
        s.commit()
        rid = r.id

    class DiesAfterSend(Exception):
        pass

    with ctx.factory() as s:
        real_audit = collections.record_audit

        def boom(*a, **k):
            if a[2] == "reminder.sent":
                raise DiesAfterSend()  # the mail is out, the program stops before it can write "sent"
            return real_audit(*a, **k)

        collections.record_audit = boom
        try:
            with pytest.raises(DiesAfterSend):
                collections.send_approved(s, ctx)
        finally:
            collections.record_audit = real_audit
    assert len(ctx.adapters.email.sent) == 1
    with ctx.factory() as s:
        assert s.get(Reminder, rid).status == "sending"  # the intent was saved first
        out = collections.send_approved(s, ctx)  # the next pass must not send it again
        s.commit()
        assert out["sent"] == 0 and len(ctx.adapters.email.sent) == 1
        from booklantern.models import ExceptionItem
        assert s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "reminder_unconfirmed", ExceptionItem.ref_id == rid)).first() is not None  # a person is told to look


def test_a_reminder_that_could_not_be_sent_goes_back_to_approved(tmp_path):
    from booklantern import collections
    from booklantern.models import Reminder

    from .test_hardening_money import CountingEmail, add_customer_invoice, live_ctx

    ctx = live_ctx(tmp_path)
    ctx.adapters.email = CountingEmail(fail_for={"pay@customer.test"})
    with ctx.factory() as s:
        inv = add_customer_invoice(s, ctx)
        r = Reminder(invoice_id=inv.id, step=1, tone="friendly", status="approved", scheduled_for=ctx.now(s), subject="Reminder", body="Please pay")
        s.add(r)
        s.commit()
        out = collections.send_approved(s, ctx)
        assert out["held"] == 1 and s.get(Reminder, r.id).status == "approved" and s.get(Reminder, r.id).sent_at is None


def test_the_constraints_header_names_a_make_target_that_exists():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    import re

    header = "\n".join(line for line in (root / "constraints.txt").read_text().splitlines() if line.startswith("#"))
    makefile = (root / "Makefile").read_text()
    for target in (a or b for a, b in re.findall(r"`make ([a-z][a-z-]*)`|: make ([a-z][a-z-]*)", header)):
        assert re.search(rf"^{target}:", makefile, re.M), f"constraints.txt says make {target} but the Makefile has no such target"
    assert "pip freeze" in header or "uv pip freeze" in header  # it says how the file is really refreshed


# ---- found while checking the round 2 fixes ----------------------------------------------------------------------------------------------------------

def test_taking_back_a_payment_never_moves_a_bill_into_a_state_nobody_approved(ctx):
    from datetime import date

    from booklantern import bankservice
    from booklantern.models import Bill

    bill_id, txn_id = _bank_world(ctx)
    with ctx.factory() as s:
        b = s.get(Bill, bill_id)
        b.status, b.posted_external_id = "needs_review", "EXT-OLD"  # waiting for review (with a draft id left by a wrong post)
        m = bankservice.link_manually(s, txn_id, "bill", bill_id, 10_000, "owner")
        bankservice.record_payments(s)
        assert s.get(Bill, bill_id).status == "needs_review" and s.get(Bill, bill_id).paid_minor == 10_000  # the money is recorded, the decision is still a person's
        bankservice.unlink(s, m.id, "owner")
        s.flush()
        assert s.get(Bill, bill_id).status == "needs_review" and s.get(Bill, bill_id).paid_minor == 0  # not approved, not posted


def test_two_bills_with_no_number_are_one_bill_only_when_the_dates_match_too():
    from datetime import date

    from booklantern.validation import BillData, check_duplicates

    def bill(i, issued):
        return BillData(i, 7, "", issued, "USD", "", "", "", 5000, 0, 5000, [5000])

    assert [f.kind for f in check_duplicates(bill(2, date(2026, 11, 1)), [bill(1, date(2026, 11, 1))])] == ["duplicate_exact"]  # as before
    assert check_duplicates(bill(2, date(2026, 12, 1)), [bill(1, date(2026, 11, 1))]) == []  # no number to go on: a month apart is a different bill


def test_the_second_person_approving_is_not_logged_as_self_review_and_the_page_is_told_what_to_do(client):  # noqa: F811
    d = _clean_bill(client)
    ap = approver(client)
    assert client.patch(f"/api/bills/{d['id']}", json={"bank_account": "SMPL-9999-0000"}).status_code == 200
    block = next(e for e in _blocks(client, d["id"]) if e["kind"] == "bank_detail_changed")
    assert client.get(f"/api/bills/{d['id']}").json()["self_review"] == "owner"  # the owner edited it: the page asks for a written reason
    assert client.get(f"/api/bills/{d['id']}", headers=ap).json()["self_review"] == ""
    assert client.post(f"/api/exceptions/{block['id']}/resolve", json={"note": "Phoned the vendor on the number on file"}).status_code == 200
    assert client.post(f"/api/bills/{d['id']}/approve", json={"note": ""}, headers=ap).status_code == 200
    approved = next(a for a in client.get("/api/audit?limit=20").json() if a["action"] == "bill.approved" and a["target"] == f"bill:{d['id']}")
    assert approved["detail"]["self_review"] is False  # the approval itself used to put the approver's name on the bill and then count it as their own edit


def test_an_approver_who_edited_a_bill_is_told_by_the_page_that_someone_else_must_approve(client):  # noqa: F811
    d = _clean_bill(client)
    ap = approver(client)
    assert client.patch(f"/api/bills/{d['id']}", json={"bank_account": "SMPL-9999-0000"}, headers=ap).status_code == 200
    assert client.get(f"/api/bills/{d['id']}", headers=ap).json()["self_review"] == "blocked"


def test_a_reminder_left_in_sending_can_be_cancelled_by_a_person(client):  # noqa: F811
    from booklantern.models import Reminder

    ctx = client.app.state.ctx
    with ctx.factory() as s:
        r = s.scalars(__import__("sqlalchemy").select(Reminder)).first()
        r.status = "sending"
        s.commit()
        rid = r.id
    assert client.post(f"/api/reminders/{rid}/cancel").status_code == 200


def test_an_old_sqlite_file_without_the_new_column_is_upgraded_at_startup(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from booklantern.api.app import create_app
    from booklantern.config import Settings
    from booklantern.dbupgrade import add_missing_columns
    from sendora_core.db import Base

    import booklantern.models  # noqa: F401
    from sendora_core import models as _core  # noqa: F401

    url = f"sqlite:///{tmp_path / 'old.sqlite3'}"
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(text("ALTER TABLE ll_document DROP COLUMN read_attempts"))  # what a file made by release 1.0.0 looks like
    assert "read_attempts" not in {c["name"] for c in inspect(eng).get_columns("ll_document")}
    s = Settings(_env_file=None, database_url=url, session_secret="test-only-Rt7Kq2Vw9Xm4Zc8Lb3Nf6Hy1Js5Dp0Ga2Ue7Tq4Wi9", demo_mode=False, owner_password_hash="x",
                 company_name="Rivera Works", upload_dir=str(tmp_path / "up"))
    create_app(s)  # startup adds the column
    assert "read_attempts" in {c["name"] for c in inspect(create_engine(url)).get_columns("ll_document")}
    assert add_missing_columns(create_engine(url)) == []  # and a second start changes nothing
