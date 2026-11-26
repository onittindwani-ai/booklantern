"""Manual exchange rates: the maths, the lookup, and the rule that no number changes currency without saying so."""

import random
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from booklantern import collections, forecastservice, fx as FX, fxservice, money as M, report_pdf
from booklantern.models import Bill, Customer, ExceptionItem, FxRate, Invoice
from booklantern.reconcile import Target, Txn, match_all

from .test_api import approver, client, viewer  # noqa: F401

D = Decimal


# ---- the conversion maths -------------------------------------------------------------------------------------

def test_conversion_applies_the_difference_in_minor_units():
    assert M.convert(10_000, "JPY", "USD", D("0.0067")) == 6_700  # 10,000 yen is 67.00 dollars: no fractional yen, two dollar decimals
    assert M.convert(6_700, "USD", "JPY", D("149.25")) == 10_000  # 67.00 dollars at 149.25 is 10,000 yen (9,999.75 rounded)
    assert M.convert(120_000, "EUR", "USD", D("1.0800")) == 129_600
    assert M.convert(500, "USD", "USD", D("1")) == 500


def test_rounding_is_half_away_from_zero_once():
    assert M.convert(50, "USD", "JPY", D("1")) == 1  # 0.50 yen
    assert M.convert(-50, "USD", "JPY", D("1")) == -1
    assert M.convert(49, "USD", "JPY", D("1")) == 0
    assert M.convert(1, "EUR", "USD", D("1.5")) == 2  # 1.5 cents
    assert M.convert(-1, "EUR", "USD", D("1.5")) == -2


def test_a_float_or_a_bad_rate_is_refused():
    for bad in (1.08, "1.08", 1, D("0"), D("-1"), D("NaN"), D("Infinity")):
        with pytest.raises(M.MoneyError):
            M.convert(100, "EUR", "USD", bad)


def test_conversion_is_symmetric_monotonic_and_close_to_exact():
    rng = random.Random(20261123)
    for _ in range(2000):
        m = rng.randint(-10**12, 10**12)
        r = D(rng.randint(1, 5_000_000)) / D(10_000)  # 0.0001 to 500
        assert M.convert(-m, "EUR", "USD", r) == -M.convert(m, "EUR", "USD", r)
        assert M.convert(m, "EUR", "USD", r) <= M.convert(m + 1, "EUR", "USD", r)
        assert abs(D(M.convert(m, "EUR", "USD", r)) - D(m) * r) <= D("0.5")
        assert M.convert(m, "EUR", "EUR", r) == m


def test_going_there_and_back_loses_at_most_the_rounding():
    rng = random.Random(7)
    for _ in range(2000):
        m = rng.randint(0, 10**10)
        r = D(rng.randint(100, 1_000_000)) / D(10_000)  # 0.01 to 100
        there = M.convert(m, "EUR", "USD", r)
        back = M.convert(there, "USD", "EUR", D(1) / r)
        assert abs(back - m) <= D("0.5") / r + 1


# ---- reading a rate and looking it up ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["1.0800", "0.0067", "149", "1", "0.00000001"])
def test_a_plain_rate_is_accepted(text):
    assert FX.parse_rate(text) == D(text)


@pytest.mark.parametrize("bad", ["1,08", "-1", "0", "0.0", "abc", "", "1e5", "1.123456789", " ", "1.0.0", "$1.08", 1.08])
def test_a_badly_typed_rate_is_refused(bad):
    with pytest.raises(FX.FxError):
        FX.parse_rate(bad)


def book(*rows, stale=45):
    return FX.RateBook("USD", [FX.Rate("EUR", date.fromisoformat(d), D(r)) for d, r in rows], stale)


def test_the_latest_rate_on_or_before_the_day_is_used_and_a_later_one_never():
    b = book(("2026-01-01", "1.10"), ("2026-06-01", "1.20"), ("2026-12-15", "1.50"))
    assert b.convert(100, "EUR", date(2026, 5, 31)).rate == "1.10"
    assert b.convert(100, "EUR", date(2026, 6, 1)).rate == "1.20"
    assert b.convert(100, "EUR", date(2026, 12, 1)).rate_date == date(2026, 6, 1)
    with pytest.raises(FX.NoRateError):
        b.convert(100, "EUR", date(2025, 12, 31))  # before the first rate: nothing is guessed
    with pytest.raises(FX.NoRateError):
        b.convert(100, "GBP", date(2026, 6, 1))


def test_a_conversion_keeps_the_original_and_says_how_it_was_made():
    c = book(("2026-01-01", "1.0800")).convert(120_000, "EUR", date(2026, 2, 1))
    assert (c.original_minor, c.original_currency, c.base_minor, c.rate, c.rate_date, c.converted) == (120_000, "EUR", 129_600, "1.0800", date(2026, 1, 1), True)
    assert c.to_dict()["rate_date"] == "2026-01-01" and c.stale is False
    same = book().convert(5, "USD", date(2026, 3, 1))
    assert same.converted is False and same.base_minor == 5


def test_an_old_rate_is_marked_stale():
    assert book(("2026-01-01", "1.1"), stale=45).convert(1, "EUR", date(2026, 3, 1)).stale is True
    assert book(("2026-01-01", "1.1"), stale=45).convert(1, "EUR", date(2026, 1, 20)).stale is False


# ---- the reconciliation never compares across currencies without a rate -----------------------------------------------

def _eur_bill():
    return Target("bill", 7, "GM-1", "Gablemere Print Studio", 100_000, date(2026, 1, 5), date(2026, 2, 4), "EUR")


def test_a_dollar_payment_is_not_matched_to_a_euro_bill_with_no_rate():
    t = Txn(1, date(2026, 2, 1), "Gablemere Print Studio GM-1", -100_000, "USD")
    assert match_all([t], [_eur_bill()], [], book())[0].outcome == "unmatched"
    assert match_all([t], [_eur_bill()], [], None)[0].outcome == "unmatched"


def test_a_dollar_payment_matches_a_euro_bill_at_the_manual_rate_and_says_so():
    t = Txn(1, date(2026, 2, 1), "Gablemere Print Studio GM-1", -108_000, "USD")
    r = match_all([t], [_eur_bill()], [], book(("2026-01-01", "1.0800")))[0]
    assert r.outcome in ("matched", "suggested") and "manual rate 1.0800 dated 2026-01-01" in r.links[0].reason


# ---- the database layer and the screens ---------------------------------------------------------------------------------

def _foreign_invoice(s, ctx, cents=250_000, currency="EUR", number="X-EUR-1", late_days=40):
    cust = s.scalars(select(Customer)).first()
    inv = Invoice(customer_id=cust.id, number=number, issue_date=ctx.today(s) - timedelta(days=late_days + 30), due_date=ctx.today(s) - timedelta(days=late_days), currency=currency, total_minor=cents, paid_minor=0)
    s.add(inv)
    s.commit()
    return inv.id


def test_the_demo_seed_carries_one_dated_sample_rate(seeded):
    with seeded.factory() as s:
        rows = list(s.scalars(select(FxRate)))
        assert [(r.currency, r.rate, r.note) for r in rows] == [("EUR", "1.0800", "Demo rate, sample")]


def test_aging_in_the_company_currency_keeps_the_original_amount(seeded):
    with seeded.factory() as s:
        before = collections.aging_report(s, ctx_today(seeded, s), seeded.rates(s))
        iid = _foreign_invoice(s, seeded)
        after = collections.aging_report(s, ctx_today(seeded, s), seeded.rates(s))
        assert after["total_minor"] == before["total_minor"] + 270_000  # 2,500.00 EUR at 1.0800 is 2,700.00 USD
        assert after["buckets_minor"]["31-60"] == before["buckets_minor"]["31-60"] + 270_000
        item = [i for i in after["fx"]["converted"] if i["id"] == iid][0]
        assert (item["original_minor"], item["original_currency"], item["base_minor"], item["rate"], item["rate_date"], item["converted"]) == (250_000, "EUR", 270_000, "1.0800", "2025-12-01", True)
        assert after["fx"]["rates_used"][0]["currency"] == "EUR" and before["fx"]["converted_count"] == 0


def test_an_invoice_with_no_rate_is_left_out_listed_and_never_added_raw(seeded):
    with seeded.factory() as s:
        before = collections.aging_report(s, ctx_today(seeded, s), seeded.rates(s))
        iid = _foreign_invoice(s, seeded, currency="GBP", number="X-GBP-1")
        after = collections.aging_report(s, ctx_today(seeded, s), seeded.rates(s))
        assert after["total_minor"] == before["total_minor"]  # not 250,000 more
        assert [m["id"] for m in after["fx"]["missing"]] == [iid] and after["fx"]["missing"][0]["reason"] == "no_rate"
        assert fxservice.flag_missing(s, seeded) >= 1
        ex = s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "missing_fx_rate", ExceptionItem.ref_id == iid)).first()
        assert ex is not None and "GBP" in ex.detail
        fxservice.set_rate(s, seeded, "GBP", date(2025, 12, 1), "1.2700", "test", "owner@example.test")
        assert s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "missing_fx_rate", ExceptionItem.ref_id == iid, ExceptionItem.status == "open")).first() is None
        assert collections.aging_report(s, ctx_today(seeded, s), seeded.rates(s))["total_minor"] == before["total_minor"] + 317_500


def ctx_today(ctx, s):
    return ctx.today(s)


def test_the_forecast_converts_euro_bills_and_lists_them(seeded):
    with seeded.factory() as s:
        res = forecastservice.compute(s, seeded)
        bills = [i for i in res["fx"]["converted"] if i["kind"] == "bill"]
        eur = [b for b in s.scalars(select(Bill).where(Bill.currency == "EUR", Bill.status.in_(("approved", "posted_draft", "needs_review", "inbox"))))]
        assert res["currency"] == "USD" and {b["id"] for b in bills} <= {b.id for b in eur}
        for b in bills:
            assert b["original_currency"] == "EUR" and b["rate"] == "1.0800" and b["base_minor"] == M.convert(b["original_minor"], "EUR", "USD", D("1.0800"))


def test_removing_the_rate_removes_the_euro_bills_from_the_forecast_and_says_so(seeded):
    with seeded.factory() as s:
        eur = list(s.scalars(select(Bill).where(Bill.currency == "EUR", Bill.status.in_(("approved", "posted_draft", "needs_review", "inbox")), Bill.due_date.is_not(None))))
        if not eur:
            b = s.scalars(select(Bill)).first()
            s.add(Bill(vendor_id=b.vendor_id, vendor_name_read=b.vendor_name_read, number="EUR-TEST", issue_date=b.issue_date, due_date=ctx_today(seeded, s) + timedelta(days=10), currency="EUR", total_minor=100_000, status="approved"))
            s.commit()
        with_rate = forecastservice.compute(s, seeded)
        for r in s.scalars(select(FxRate)):
            s.delete(r)
        s.commit()
        without = forecastservice.compute(s, seeded)
        assert without["fx"]["converted_count"] == 0 and without["fx"]["missing_count"] >= 1
        assert all(m["reason"] == "no_rate" for m in without["fx"]["missing"])
        assert abs(sum(w["bills_minor"] for w in without["weeks"])) < abs(sum(w["bills_minor"] for w in with_rate["weeks"]))  # bills are outflows


def test_every_page_that_totals_money_says_which_numbers_were_converted(client, seeded):
    with seeded.factory() as s:
        _foreign_invoice(s, seeded)
    for path in ("/api/overview", "/api/aging", "/api/forecast", "/api/reports/summary"):
        body = client.get(path).json()
        assert body["fx"]["converted_count"] >= 1 and body["fx"]["base"] == "USD", path
    inv = [i for i in client.get("/api/invoices").json() if i["number"] == "X-EUR-1"][0]
    assert inv["currency"] == "EUR" and inv["outstanding_minor"] == 250_000 and inv["fx"]["base_minor"] == 270_000 and inv["fx"]["rate"] == "1.0800"
    usd = [i for i in client.get("/api/invoices").json() if i["currency"] == "USD"][0]
    assert usd["fx"] is None
    bills = [b for b in client.get("/api/bills").json() if b["currency"] == "EUR"]
    assert bills and all(b["fx"]["converted"] is True and b["fx"]["original_minor"] == b["total_minor"] for b in bills)


def test_the_month_end_pdf_lists_the_rates_and_the_converted_items(seeded):
    with seeded.factory() as s:
        _foreign_invoice(s, seeded)
        pdf = report_pdf.build(s, seeded)
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    text = " ".join(doc[i].get_textpage().get_text_range() for i in range(len(doc))).replace("\r\n", " ").replace("\n", " ")
    assert "Exchange rates" in text and "converted into USD at manual rates" in text and "EUR at 1.0800 dated 2025-12-01" in text
    assert "X-EUR-1" in text


def test_rates_are_set_through_the_api_with_checks_and_an_audit_entry(client, seeded):
    ok = client.post("/api/fx-rates", json={"currency": "gbp", "rate_date": "2026-11-30", "rate": "1.2700", "note": "bank page"})
    assert ok.status_code == 200 and ok.json()["rate"] == "1.2700" and ok.json()["warning"] == ""
    again = client.post("/api/fx-rates", json={"currency": "GBP", "rate_date": "2026-11-30", "rate": "1.2800"})  # same day: a correction
    assert again.status_code == 200
    rows = [r for r in client.get("/api/fx-rates").json()["rates"] if r["currency"] == "GBP"]
    assert len(rows) == 1 and rows[0]["rate"] == "1.2800"
    jump = client.post("/api/fx-rates", json={"currency": "GBP", "rate_date": "2026-12-01", "rate": "9.0000"}).json()
    assert "25 percent" in jump["warning"]
    for body, why in (({"currency": "USD", "rate_date": "2026-11-30", "rate": "1"}, "company currency"), ({"currency": "ZZZ", "rate_date": "2026-11-30", "rate": "1"}, "Unknown"),
                      ({"currency": "GBP", "rate_date": "2027-01-01", "rate": "1.2"}, "future"), ({"currency": "GBP", "rate_date": "2026-11-30", "rate": "1,2"}, "digits"),
                      ({"currency": "GBP", "rate_date": "2026-11-30", "rate": "0"}, "above zero")):
        r = client.post("/api/fx-rates", json=body)
        assert r.status_code == 422 and why in r.text, body
    audit = client.get("/api/audit").json()
    assert any(a["action"] == "fx_rate.set" for a in (audit if isinstance(audit, list) else audit.get("entries", audit.get("rows", []))))


def test_a_viewer_can_read_rates_but_not_change_them(client):
    h = viewer(client)
    assert client.get("/api/fx-rates", headers=h).status_code == 200
    assert client.post("/api/fx-rates", json={"currency": "GBP", "rate_date": "2026-11-30", "rate": "1.27"}, headers=h).status_code == 403
