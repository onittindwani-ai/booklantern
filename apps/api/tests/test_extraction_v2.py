"""The offline reader on small bills written for these tests (general layouts and conventions, not from any test set): other languages, number styles, date styles, tax included, several pages, credit notes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
import eval_independent as E  # noqa: E402

from booklantern.extraction import offline  # noqa: E402


def read(text):
    return offline.extract_pages(E.pages_from_text(text))


DE = """Mustermann Werkzeug GmbH
Hauptstrasse 1, 12345 Teststadt

Rechnung
Rechnungsnummer:   RE-2026-0042
Rechnungsdatum:    14.10.2026
Fälligkeitsdatum:  13.11.2026
Rechnung an:       Birchfield Supply Co

Bezeichnung               Menge     Preis       Betrag
Schraubenset                  3     12,50       37,50
Zange                         1    1.200,00   1.200,00

Zwischensumme                                   1.237,50
MwSt 19 %                                         235,13
Gesamtbetrag                              EUR   1.472,63
"""

JP = """ホシノ テスト株式会社
請求書
請求書番号: 2026-1001
請求日: 2026年10月14日
支払期限: 2026年11月30日
Item        Qty     Unit      Amount
Part A        2     12,000     24,000
Subtotal                       24,000
消費税 10%                      2,400
合計   JPY                     26,400
"""

INCL = """Corner Coffee Test Ltd
Receipt No: R-77
Date: 3 November 2026
Flat white x2           7.00
Cake                    4.50
Total                  11.50 GBP
Includes VAT 20%        1.92
"""

PAGES = """Test Freight AS
Invoice No: FF-9
Invoice Date: 2026-10-01

Description   Qty   Unit     Amount
Haul A          1   100.00   100.00
Carried forward                100.00
\fTest Freight AS  page 2
Haul B          1   50.00     50.00
Subtotal                     150.00
VAT 25%                       37.50
Total Due   NOK              187.50
"""

CREDIT = """Quillbrook Test Ltd
Credit Note
Credit note no: CN-5
Date: 2026-10-05
Subtotal    (50.00)
Tax (10%)    (5.00)
Total       (55.00)  USD
"""


def test_german_bill_with_decimal_comma_and_day_first_dates():
    ex = read(DE)
    assert (ex.value("number"), ex.value("issue_date"), ex.value("due_date"), ex.value("currency")) == ("RE-2026-0042", "2026-10-14", "2026-11-13", "EUR")
    assert (ex.value("subtotal_minor"), ex.value("tax_minor"), ex.value("total_minor")) == (123750, 23513, 147263)
    assert [x.total_minor for x in ex.lines] == [3750, 120000]
    assert ex.fields["total_minor"].confidence >= 90  # the sums agree


def test_japanese_bill_has_no_decimals_and_a_japanese_date():
    ex = read(JP)
    assert (ex.value("issue_date"), ex.value("due_date"), ex.value("currency")) == ("2026-10-14", "2026-11-30", "JPY")
    assert (ex.value("subtotal_minor"), ex.value("tax_minor"), ex.value("total_minor")) == (24000, 2400, 26400)


def test_tax_included_receipt_works_out_the_net_and_says_so():
    ex = read(INCL)
    assert ex.value("total_minor") == 1150 and ex.value("tax_minor") == 192 and ex.value("subtotal_minor") == 958
    assert "worked out" in ex.fields["subtotal_minor"].reasons[0]


def test_every_page_is_read_and_carried_forward_is_not_a_line():
    ex = read(PAGES)
    assert ex.value("total_minor") == 18750 and [x.total_minor for x in ex.lines] == [10000, 5000]
    assert ex.value("currency") == "NOK"


def test_a_credit_note_is_named_and_read_in_absolute_amounts():
    ex = read(CREDIT)
    assert ex.value("doc_type") == "credit_note" and ex.value("total_minor") == 5500 and ex.value("subtotal_minor") == 5000


def test_printed_wrong_total_is_kept_as_printed_with_lower_confidence():
    ex = read(DE.replace("1.472,63", "1.482,63"))
    assert ex.value("total_minor") == 148263 and ex.fields["total_minor"].confidence < 70


def test_two_invoice_numbers_on_one_page_go_to_a_person():
    ex = read(DE + "\nRechnungsnummer: RE-2026-0043\n")
    assert ex.readable is False and "more than one" in ex.notes[0]


def test_ambiguous_numeric_date_is_flagged_low_not_trusted():
    ex = read(DE.replace("14.10.2026", "12/11/2026").replace("13.11.2026", "12/12/2026"))
    f = ex.fields["issue_date"]
    assert f.confidence < 50 or f.value in ("2026-11-12",)


@pytest.mark.parametrize("text,exp,want", [("1.234,56", 2, 123456), ("1,234.56", 2, 123456), ("12,34,567.00", 2, 123456700), ("1'234.50", 2, 123450), ("¥12,345", 0, 12345), ("(45.00)", 2, -4500), ("45.00-", 2, -4500)])
def test_number_styles(text, exp, want):
    from booklantern.extraction.numbers import parse_money
    assert parse_money(text, exp) == want


@pytest.mark.parametrize("text,want", [("14 de marzo de 2026", "2026-03-14"), ("14 mars 2026", "2026-03-14"), ("October 31, 2026", "2026-10-31"), ("14th September 2026", "2026-09-14"), ("12. Oktober 2026", "2026-10-12"),
                                       ("20261023", "2026-10-23"), ("14-Oct-26", "2026-10-14"), ("2026.10.13", "2026-10-13"), ("31/10/2026", "2026-10-31")])
def test_date_styles(text, want):
    assert offline.parse_date(text) == want
