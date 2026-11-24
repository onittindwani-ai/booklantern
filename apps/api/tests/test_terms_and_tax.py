"""Decided defaults that need a test of their own: net 30 for a bill with no due date, and tax read from the bill, never advised."""

from datetime import date, timedelta

from sqlalchemy import select

from booklantern import validation as V
from booklantern.intake import DEFAULT_TERMS_DAYS, vm_terms
from booklantern.models import Bill, ExceptionItem

from .test_api import client  # noqa: F401
from .test_security import _pdf


def test_a_bill_with_no_due_date_gets_net_30_and_says_so(client, seeded):
    data = _pdf(["Unlisted Supplies Ltd", "INVOICE", "Invoice No: NT-1", "Invoice Date: 2026-11-20", "Total Due USD 100.00"])
    r = client.post("/api/documents/upload", content=data, headers={"x-filename": "nt1.pdf"})
    assert r.status_code == 200, r.text
    with seeded.factory() as s:
        b = s.get(Bill, r.json()["bill_id"])
        assert DEFAULT_TERMS_DAYS == 30
        assert b.issue_date == date(2026, 11, 20) and b.due_date == b.issue_date + timedelta(days=30)
        ex = s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "due_date_assumed", ExceptionItem.ref_id == b.id)).first()
        assert ex is not None and "net 30" in ex.detail and ex.severity == "info"


def test_a_known_vendor_uses_its_own_terms(seeded):
    from booklantern.models import Vendor

    class VM:  # a matched vendor
        def __init__(self, i):
            self.id = i

    with seeded.factory() as s:
        v = s.scalars(select(Vendor)).first()
        v.terms_days = 45
        s.flush()
        assert vm_terms(s, VM(v.id)) == 45
        assert vm_terms(s, None) == 30


def test_the_tax_finding_compares_and_does_not_advise():
    b = V.BillData(1, 1, "T-1", date(2026, 11, 1), "USD", "", "", "", 10_000, 500, 10_500, [10_000], 725)
    out = [f for f in V.check_math(b, None) if f.kind == "wrong_tax"]
    assert out and "not tax advice" in out[0].detail and "should be" not in out[0].detail
