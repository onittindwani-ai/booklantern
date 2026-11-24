"""The description of one synthetic bill. Everything in it is fictional."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from booklantern.money import format_minor

COMPANY = "Birchfield Supply Co"
OTHER_COMPANY = "Larkspur Trading Ltd"
FOOTER = "Synthetic sample document. Fictional company, not a real invoice."


@dataclass
class Line:
    desc: str
    qty_milli: int
    unit_minor: int
    total_minor: int


@dataclass
class DocSpec:
    doc_id: str
    layout: str
    vendor: str
    vendor_addr: str
    account: str
    number: str
    issue: date
    due: date
    currency: str
    po: str | None
    bill_to: str
    lines: list[Line]
    tax_rate_bp: int
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    problems: list[str] = field(default_factory=list)
    duplicate_of: str | None = None

    def truth(self) -> dict:
        """What a careful reader should read off the page (the printed values, even when they are wrong)."""
        return {"vendor": self.vendor, "number": self.number, "issue_date": self.issue.isoformat(), "due_date": self.due.isoformat(), "currency": self.currency,
                "po": self.po or "", "bill_to": self.bill_to, "subtotal_minor": self.subtotal_minor, "tax_minor": self.tax_minor, "total_minor": self.total_minor,
                "bank_account": self.account, "tax_rate_bp": self.tax_rate_bp, "line_totals_minor": [x.total_minor for x in self.lines]}


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def money_us(minor: int, cur: str, sym: bool = False) -> str:
    return format_minor(minor, cur, symbol=sym)


def money_eu(minor: int, cur: str) -> str:
    s = format_minor(minor, cur, symbol=False).replace(f" {cur}", "")
    return s.replace(",", "#").replace(".", ",").replace("#", ".") + " " + {"EUR": "€", "USD": "$", "GBP": "£"}.get(cur, cur)


def qty_text(q_milli: int) -> str:
    return str(q_milli // 1000) if q_milli % 1000 == 0 else f"{q_milli / 1000:g}"
