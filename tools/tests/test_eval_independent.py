"""The independent scorer, proven on tiny handmade documents (never on a held out set)."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

import eval_independent as E  # noqa: E402

GOOD = """Quillbrook Test Supply Ltd
INVOICE
Invoice No:    QT-100
Invoice Date:  2026-10-07
Due Date:      2026-11-06
Bill To:       Birchfield Supply Co

Description          Qty     Unit Price     Amount
Test widget            2          10.00      20.00
Test gadget            1          30.00      30.00
Subtotal                                     50.00
Tax (10%)                                     5.00
Total Due                           USD      55.00
"""
BAD_TOTAL = GOOD.replace("55.00", "56.00").replace("QT-100", "QT-101")
SCAN = "  \n"


def key(file, text, **kw):
    base = {"file": file, "doc_id": file, "doc_type": "bill", "language": "en", "layout_family": "t", "tags": ["t"], "needs_person": False, "vendor": "Quillbrook Test Supply Ltd", "vendor_aliases": [],
            "invoice_number": "QT-100", "invoice_date": "2026-10-07", "due_date": "2026-11-06", "due_date_derived_from_terms": None, "currency": "USD", "subtotal_minor": 5000, "subtotal_printed": True,
            "tax_minor": 500, "tax_printed": True, "total_minor": 5500, "line_items": [{"amount_minor": 2000}, {"amount_minor": 3000}], "expected_findings": []}
    base.update(kw)
    return base


def make_set(tmp_path, items):
    (tmp_path / "docs").mkdir()
    keys = []
    for file, text, kw in items:
        (tmp_path / "docs" / file).write_text(text, encoding="utf-8")
        keys.append(key(file, text, **kw))
    (tmp_path / "key.json").write_text(json.dumps(keys), encoding="utf-8")
    ctx = {"client_company": "Birchfield Supply Co", "reference_today": "2026-11-23", "vendor_master": {"Quillbrook Test Supply Ltd": {
        "default_currency": "USD", "requires_po": False, "iban_on_file": "", "typical_total_minor_range": [4000, 9000], "tax_rates_on_file_bps": [1000]}}}
    (tmp_path / "context.json").write_text(json.dumps(ctx), encoding="utf-8")
    return E.load_set(tmp_path)


def test_a_text_file_becomes_rows_of_cells_and_pages_split_on_form_feed():
    pages = E.pages_from_text("Invoice No:    A-1\n\nTotal   9.00\fPage two text here")
    assert len(pages) == 2
    row = pages[0].rows()[0]
    assert [c.text for c in row] == ["Invoice No:", "A-1"]
    assert pages[0].chars == len("Invoice No:    A-1\n\nTotal   9.00") and pages[1].chars > 10


def test_a_clean_bill_scores_every_field_and_raises_nothing(tmp_path):
    r = E.evaluate(make_set(tmp_path, [("doc_001.txt", GOOD, {})]))
    assert r["documents_all_fields_right"] == 1 and r["field_percent"] == 100.0
    assert r["findings_expected"] == 0 and r["false_flags_total"] == 0 and r["failing_documents"] == {}
    assert r["confident_wrong_fields"] == 0 and r["not_extracted"] == ["payment_terms"] and r["doc_type"] == {"correct": 1, "total": 1}


def test_a_wrong_printed_total_is_found_and_a_wrong_key_is_a_failure(tmp_path):
    items = [("doc_001.txt", BAD_TOTAL, {"invoice_number": "QT-101", "total_minor": 5600, "expected_findings": ["total_mismatch"]}),
             ("doc_002.txt", GOOD, {"invoice_number": "SOMETHING-ELSE"})]
    r = E.evaluate(make_set(tmp_path, items))
    assert r["findings"]["total_mismatch"] == {"found": 1, "missed": 0, "false_flags": 0}
    assert r["failing_documents"] == {"doc_002.txt": ["invoice_number"]}
    assert r["documents_all_fields_right"] == 1


def test_a_finding_raised_where_none_is_expected_is_a_false_flag(tmp_path):
    r = E.evaluate(make_set(tmp_path, [("doc_001.txt", BAD_TOTAL, {"invoice_number": "QT-101", "total_minor": 5600})]))
    assert r["findings"]["total_mismatch"]["false_flags"] == 1 and r["false_flags_total"] >= 1


def test_a_hard_document_passes_when_unreadable_and_fails_when_confident(tmp_path):
    hard = {"needs_person": True, "vendor": None, "invoice_number": None, "invoice_date": None, "due_date": None, "currency": None, "subtotal_minor": None, "tax_minor": None, "total_minor": None,
            "line_items": [], "expected_findings": ["no_text_layer"]}
    r = E.evaluate(make_set(tmp_path, [("doc_001.txt", SCAN, hard)]))
    assert r["hard"] == {"passed": 1, "total": 1, "confident_on_hard": 0} and r["findings"]["no_text_layer"]["found"] == 1
    (tmp_path / "x").mkdir()
    r = E.evaluate(make_set(tmp_path / "x", [("doc_001.txt", GOOD, hard)]))
    assert r["hard"]["passed"] == 0 and r["hard"]["confident_on_hard"] == 1


def test_a_byte_identical_copy_counts_as_merged_and_a_unprinted_tax_may_be_empty(tmp_path):
    items = [("doc_001.txt", GOOD, {}), ("doc_002.txt", GOOD, {"duplicate_of": "doc_001.txt", "expected_findings": ["duplicate_exact"]})]
    r = E.evaluate(make_set(tmp_path, items))
    assert r["findings"]["duplicate_exact"] == {"found": 1, "missed": 0, "false_flags": 0}
    assert hashlib.sha256(GOOD.encode()).hexdigest() == E.load_set(tmp_path)[0]["sha"]


def test_the_tool_refuses_to_overwrite_a_saved_first_run(tmp_path, capsys, monkeypatch):
    src = tmp_path / "set"
    src.mkdir()
    make_set(src, [("doc_001.txt", GOOD, {})])
    out = tmp_path / "set_a_first_run.json"
    out.write_text("{}")
    monkeypatch.setattr(sys, "argv", ["x", "--set", "a", "--source", str(src), "--out", str(out)])
    assert E.main() == 1 and out.read_text() == "{}"
