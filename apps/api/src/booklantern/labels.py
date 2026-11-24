"""Plain words for the names the code uses inside. The web app has the same list for its screens; the month end PDF uses this one."""

from __future__ import annotations

FINDING = {
    "wrong_total": "Total does not add up", "wrong_tax": "Tax differs from the rate", "tax_rate_differs": "Tax rate differs from the usual", "due_date_assumed": "Due date assumed",
    "missing_fx_rate": "No exchange rate", "line_sum_mismatch": "Lines do not add up", "duplicate_exact": "Exact duplicate", "duplicate_near": "Possible duplicate", "amount_far_above_history": "Far above usual",
    "bank_detail_changed": "Bank details changed", "missing_po": "No purchase order", "currency_mismatch": "Unexpected currency", "future_date": "Date in the future", "wrong_company": "Addressed to someone else",
    "unknown_vendor": "Unknown vendor", "unreadable_document": "Could not read it", "low_confidence": "Low confidence", "possible_duplicate_line": "Duplicate bank line", "unmatched_line": "Bank line not matched",
    "suspicious_text": "Text that gives orders", "credit_note": "Credit note",
}
BUCKET = {"current": "Not due yet", "1-30": "1 to 30 days late", "31-60": "31 to 60 days late", "61-90": "61 to 90 days late", "90+": "Over 90 days late"}
REF = {"bill": "Bill", "bank_txn": "Bank line", "bank": "Bank line", "invoice": "Invoice"}


def finding(kind: str) -> str:
    return FINDING.get(kind, kind.replace("_", " ").capitalize())


def where(ref_type: str, ref_id: int) -> str:
    return f"{REF.get(ref_type, ref_type.replace('_', ' ').capitalize())} {ref_id}"
