"""Validation by code. Every check is plain arithmetic or comparison on integers and strings. No model is involved."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

from booklantern.money import format_minor, tax_for

TAX_TOLERANCE_MINOR = 1  # printed tax may differ from rate times subtotal by one minor unit (rounding at line level)
ANOMALY_MULTIPLE = 4  # a total above 4 times the vendor's median earlier total is flagged (decided default, the implementer can change it)
MIN_HISTORY = 3
FUTURE_DAYS = 1
NAME_MATCH = 0.8
NEAR_DAYS = 3  # a near duplicate has the same amount, a similar number and a date within 3 days. Monthly bills of the same amount a month apart are not duplicates.


@dataclass
class Finding:
    kind: str
    severity: str  # info, warning, block
    detail: str
    refs: list[int] = field(default_factory=list)


@dataclass
class BillData:
    id: int
    vendor_id: int | None
    number: str
    issue_date: date | None
    currency: str
    po: str
    bill_to: str
    bank_account: str
    subtotal: int
    tax: int
    total: int
    line_totals: list[int]
    tax_rate_bp: int | None = None
    vendor_name: str = ""  # the name as read from the document: it stands in for the vendor when the vendor list has no match


@dataclass
class VendorData:
    id: int
    name: str
    currency: str
    tax_rate_bp: int
    requires_po: bool
    bank_account: str
    tax_rates_bp: tuple[int, ...] = ()  # every rate usually seen on this vendor's bills; empty means only `tax_rate_bp`


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.casefold().strip(), b.casefold().strip()).ratio()


_SUFFIX = re.compile(r"\b(?:co|company|corp|corporation|inc|incorporated|ltd|limited|llc|llp|plc|gmbh|ag|sa|sarl|srl|bv|nv|pty|pvt|oy|ab|as)\b\.?", re.I)


def _name_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _SUFFIX.sub(" ", s.casefold())).strip()


def same_company(bill_to: str, company: str) -> bool:
    """The same company written another way (upper case, punctuation, Co or Company, an attention line in front) is not another company."""
    a, b = _name_key(bill_to), _name_key(company)
    if b and a and (b in a or a in b):
        return True
    return similar(bill_to, company) >= NAME_MATCH


def match_vendor(name: str, vendors: list[VendorData]) -> VendorData | None:
    best = max(vendors, key=lambda v: similar(name, v.name), default=None)
    return best if best and similar(name, best.name) >= 0.85 else None


def norm_account(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def check_math(b: BillData, vendor: VendorData | None) -> list[Finding]:
    out: list[Finding] = []
    gross_lines = b.tax > 0 and sum(b.line_totals) == b.total  # prices that include tax: the lines add up to the total, not the subtotal
    if b.line_totals and sum(b.line_totals) != b.subtotal and not gross_lines:
        out.append(Finding("line_sum_mismatch", "warning", f"The lines add up to {format_minor(sum(b.line_totals), b.currency)} but the subtotal says {format_minor(b.subtotal, b.currency)}."))
    if b.subtotal + b.tax != b.total:
        out.append(Finding("wrong_total", "block", f"Subtotal plus tax is {format_minor(b.subtotal + b.tax, b.currency)} but the total says {format_minor(b.total, b.currency)}."))
    rate = b.tax_rate_bp if b.tax_rate_bp is not None else (vendor.tax_rate_bp if vendor else None)
    if rate is not None and abs(tax_for(b.subtotal, rate) - b.tax) > TAX_TOLERANCE_MINOR:
        src = "printed" if b.tax_rate_bp is not None else "the vendor's usual"
        out.append(Finding("wrong_tax", "warning", f"At {src} rate {rate / 100:g} percent the subtotal gives {format_minor(tax_for(b.subtotal, rate), b.currency)} but the bill shows {format_minor(b.tax, b.currency)}. This is a comparison only, not tax advice: ask the vendor or your accountant."))
    usual = (vendor.tax_rates_bp or (vendor.tax_rate_bp,)) if vendor and vendor.tax_rate_bp else ()
    if b.tax_rate_bp is not None and usual and b.tax_rate_bp not in usual:
        out.append(Finding("tax_rate_differs", "warning", f"The bill prints a tax rate of {b.tax_rate_bp / 100:g} percent. This vendor's bills usually carry {' or '.join(f'{r / 100:g}' for r in usual)} percent. Comparison only, not tax advice."))
    return out


def norm_number(s: str) -> str:
    """A bill number with the punctuation, the case and the zero padding taken out, so INV-0042, inv 42 and Inv.42 are one number. Digits of different groups stay apart (1-42 is not 142)."""
    parts = re.findall(r"[a-z]+|\d+", s.casefold())
    return "".join(re.sub(r"^0+(?=\d)", "", p) if p.isdigit() else p for p in parts)


def same_vendor(a: BillData, b: BillData) -> bool:
    """The same vendor: the same vendor record, or (when neither bill matched a vendor on the list) the same or a very close name as read.
    Without this a bill from a vendor nobody entered would never be compared with its own copy."""
    if a.vendor_id is not None or b.vendor_id is not None:
        return a.vendor_id == b.vendor_id
    return bool(a.vendor_name.strip() and b.vendor_name.strip()) and similar(a.vendor_name, b.vendor_name) >= 0.85


def check_duplicates(b: BillData, others: list[BillData]) -> list[Finding]:
    """Compare against bills seen earlier. `others` must hold only bills received before this one, in order."""
    out: list[Finding] = []
    for o in others:
        if o.id == b.id or not same_vendor(o, b):
            continue
        number = norm_number(b.number)
        # The same number and amount is the same bill on any date. Two bills with no readable number only count as one when their dates are the same as well (as before).
        if norm_number(o.number) == number and o.total == b.total and o.currency == b.currency and (number or o.issue_date == b.issue_date):
            if o.issue_date == b.issue_date:
                out.append(Finding("duplicate_exact", "block", f"Same vendor, number, date and amount as bill {o.id}.", [o.id]))
            else:  # the same bill sent again with another date, or with no date, is still the same bill
                out.append(Finding("duplicate_exact", "block", f"Same vendor, number and amount as bill {o.id}, but a different bill date ({o.issue_date or 'none'} and {b.issue_date or 'none'}). The same bill sent again?", [o.id]))
            continue
        close_in_time = o.issue_date is not None and b.issue_date is not None and abs((o.issue_date - b.issue_date).days) <= NEAR_DAYS
        if o.total == b.total and o.currency == b.currency and similar(o.number, b.number) >= 0.85 and close_in_time:
            out.append(Finding("duplicate_near", "warning", f"Same vendor and amount as bill {o.id}, a very similar number ({o.number} and {b.number}) and a date within {NEAR_DAYS} days.", [o.id]))
    return out


def check_history(b: BillData, history_totals: list[int]) -> list[Finding]:
    if len(history_totals) < MIN_HISTORY:
        return []
    med = int(statistics.median(history_totals))
    if med > 0 and b.total > med * ANOMALY_MULTIPLE:
        return [Finding("amount_far_above_history", "warning", f"The total is {b.total / med:.1f} times this vendor's usual bill ({format_minor(int(med), b.currency)}).")]
    return []


def check_vendor_facts(b: BillData, vendor: VendorData | None, company: str, as_of: date) -> list[Finding]:
    out: list[Finding] = []
    if vendor is None:
        out.append(Finding("unknown_vendor", "warning", "The vendor name does not match anyone on the vendor list."))
    else:
        if vendor.bank_account and b.bank_account and norm_account(vendor.bank_account) != norm_account(b.bank_account):
            out.append(Finding("bank_detail_changed", "block", "The bank account on this bill is different from the one on file. Phone the vendor on a number you already have before paying."))
        elif vendor.bank_account and not b.bank_account:
            out.append(Finding("bank_details_not_read", "block", "This vendor has a bank account on file, but none could be read from this bill. The bill may show its details in a form the reader does not know, so a changed account would go unseen. Compare the page with the account on file before paying."))
        if vendor.requires_po and not b.po:
            out.append(Finding("missing_po", "warning", "This vendor's bills need a purchase order number and none was found."))
        if b.currency != vendor.currency:
            out.append(Finding("currency_mismatch", "warning", f"The bill is in {b.currency} but the vendor is usually paid in {vendor.currency}."))
    if b.issue_date and b.issue_date > as_of + timedelta(days=FUTURE_DAYS):
        out.append(Finding("future_date", "warning", f"The bill date {b.issue_date} is after today ({as_of})."))
    if b.bill_to and not same_company(b.bill_to, company):
        out.append(Finding("wrong_company", "block", f"The bill is addressed to {b.bill_to}, not {company}."))
    return out


def validate(b: BillData, vendor: VendorData | None, others: list[BillData], history_totals: list[int], company: str, as_of: date) -> list[Finding]:
    return check_math(b, vendor) + check_duplicates(b, others) + check_history(b, history_totals) + check_vendor_facts(b, vendor, company, as_of)
