from datetime import date, timedelta

from booklantern import validation as V

AS_OF = date(2026, 12, 1)
VEND = V.VendorData(1, "Alderbank Packaging Ltd", "USD", 800, True, "FICT-0101-2201")


def bill(**kw):
    base = dict(id=10, vendor_id=1, number="ALD-1", issue_date=AS_OF - timedelta(days=5), currency="USD", po="PO-1", bill_to="Birchfield Supply Co", bank_account="FICT-0101-2201",
                subtotal=10000, tax=800, total=10800, line_totals=[6000, 4000], tax_rate_bp=800)
    base.update(kw)
    return V.BillData(**base)


def kinds(b, others=(), hist=(10000, 11000, 9000), vendor=VEND):
    return {f.kind for f in V.validate(b, vendor, list(others), list(hist), "Birchfield Supply Co", AS_OF)}


def test_clean_bill_has_no_findings():
    assert kinds(bill()) == set()


def test_each_math_check():
    assert "wrong_total" in kinds(bill(total=11800))
    assert "line_sum_mismatch" in kinds(bill(line_totals=[6000, 4500]))
    assert "wrong_tax" in kinds(bill(tax=900, total=10900))
    assert kinds(bill(tax=801, total=10801)) == set()  # one minor unit of rounding is allowed


def test_vendor_facts():
    assert "bank_detail_changed" in kinds(bill(bank_account="FICT-9999-0000"))
    assert kinds(bill(bank_account="fict 0101 2201")) == set()  # spacing and case do not matter
    assert "missing_po" in kinds(bill(po=""))
    assert "currency_mismatch" in kinds(bill(currency="EUR"))
    assert "future_date" in kinds(bill(issue_date=AS_OF + timedelta(days=9)))
    assert "wrong_company" in kinds(bill(bill_to="Larkspur Trading Ltd"))
    assert "unknown_vendor" in {f.kind for f in V.validate(bill(), None, [], [], "Birchfield Supply Co", AS_OF)}


def test_history_needs_three_earlier_bills():
    assert "amount_far_above_history" in kinds(bill(subtotal=80000, tax=6400, total=86400, line_totals=[80000]))
    assert "amount_far_above_history" not in kinds(bill(subtotal=80000, tax=6400, total=86400, line_totals=[80000]), hist=(10000, 11000))


def test_duplicate_rules():
    o = bill(id=1)
    assert "duplicate_exact" in kinds(bill(), [o])
    assert "duplicate_near" in kinds(bill(number="ALD-1A"), [o])
    assert "duplicate_exact" in kinds(bill(issue_date=o.issue_date + timedelta(days=1)), [o])  # same number and amount, date a day apart: the same bill again (it was only a warning before)
    assert "duplicate_near" in kinds(bill(number="ALD-1A", issue_date=o.issue_date + timedelta(days=1)), [o])  # a similar number, a day apart
    far = bill(id=1, number="ALD-0", issue_date=AS_OF - timedelta(days=35))
    assert kinds(bill(), [far]) == set()  # same amount, sequential number, a month apart: a normal monthly bill
    assert kinds(bill(), [bill(id=1, vendor_id=2)]) == set()  # another vendor


# ---- version 2 additions: printed tax rate against the vendor's usual rates, tax included lines, the same company written another way
def _vendor(**kw):
    from booklantern.validation import VendorData
    return VendorData(1, "Test Vendor", "USD", 1000, False, "", **kw)


def _bill(**kw):
    from datetime import date
    from booklantern.validation import BillData
    base = dict(id=1, vendor_id=1, number="N1", issue_date=date(2026, 10, 1), currency="USD", po="", bill_to="Birchfield Supply Co", bank_account="", subtotal=10000, tax=1000, total=11000, line_totals=[10000], tax_rate_bp=1000)
    base.update(kw)
    return BillData(**base)


def test_a_printed_rate_that_is_not_one_the_vendor_usually_charges_is_a_warning_not_advice():
    from booklantern.validation import check_math
    kinds = [f.kind for f in check_math(_bill(tax_rate_bp=700, tax=700, total=10700), _vendor())]
    assert kinds == ["tax_rate_differs"]
    assert check_math(_bill(tax_rate_bp=500, tax=500, total=10500), _vendor(tax_rates_bp=(1000, 500))) == []


def test_lines_that_include_tax_add_up_to_the_total_and_are_not_a_mismatch():
    from booklantern.validation import check_math
    assert check_math(_bill(line_totals=[11000]), _vendor()) == []
    assert [f.kind for f in check_math(_bill(line_totals=[9000]), _vendor())] == ["line_sum_mismatch"]


def test_the_same_company_written_another_way_is_not_flagged_but_another_company_is():
    from booklantern.validation import same_company
    for name in ("BIRCHFIELD SUPPLY CO.", "Birchfield Supply Company", "Accounts Payable, Birchfield Supply Co", "Birchfield Supply"):
        assert same_company(name, "Birchfield Supply Co"), name
    assert not same_company("Larkspur Trading Ltd", "Birchfield Supply Co")
