"""Everything a real (not demo) install has to enter before it can do its job: vendors, customers, open invoices, a bank account, a chart of accounts and repeating items.

The demo gets these from the seed. A real install gets them here, from the API (`/api/vendors`, `/api/customers/import`, ...) or from the command line
(`python tools/load_data.py`), through the same functions. A CSV import is all or nothing: every line is checked first, and one bad line (named by its number)
stops the whole file, so a half loaded list never happens.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from booklantern import limits
from booklantern.models import Account, BankAccount, Customer, Invoice, RecurringItem, Vendor
from booklantern.money import CURRENCY_EXPONENT, parse_amount
from booklantern.util import is_valid_email, zone
from sendora_core.audit import record_audit

MAX_ROWS = 20_000
ACCOUNT_KINDS = ("asset", "liability", "income", "expense")
CADENCES = ("monthly", "twice_monthly", "weekly")


class SetupError(ValueError):
    """Something in what was entered cannot be used. The message says what and where, in plain words."""


@dataclass
class ImportReport:
    added: int = 0
    skipped: list[str] = field(default_factory=list)  # already there, left as they were

    def to_dict(self) -> dict:
        return {"added": self.added, "skipped": self.skipped}


def _next_key(session: Session, model, prefix: str) -> str:
    n = (session.scalar(select(func.max(model.id))) or 0) + 1
    while session.scalar(select(model.id).where(model.key == f"{prefix}{n:03d}")) is not None:
        n += 1
    return f"{prefix}{n:03d}"


def _currency(value: str, fallback: str, where: str) -> str:
    code = (value or "").strip().upper() or fallback
    if code not in CURRENCY_EXPONENT:
        raise SetupError(f"{where}: {code} is not a currency this system knows. Use a three letter code such as USD, EUR or GBP.")
    return code


def _rows(text: str, need: tuple[str, ...]) -> list[tuple[int, dict[str, str]]]:
    """The lines of a CSV as (line number, cells by lower case header). Needs the columns named in `need`."""
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        if not reader.fieldnames:
            raise SetupError("The file is empty.")
        heads = {h.strip().lower(): h for h in reader.fieldnames if h}
        for col in need:
            if col not in heads:
                raise SetupError(f"The file needs a column called {col}. Found: {', '.join(reader.fieldnames)}.")
        out = []
        for n, rec in enumerate(reader, start=2):
            if n - 1 > MAX_ROWS:
                raise SetupError(f"The file has more than {MAX_ROWS} lines. Import it in parts.")
            row = {k: (rec.get(h) or "").strip() for k, h in heads.items()}
            if any(row.values()):
                out.append((n, row))
        return out
    except csv.Error as exc:
        raise SetupError(f"The file could not be read as CSV: {exc}") from exc


def _int(value: str, default: int, where: str, what: str, lo: int = 0, hi: int = 3650) -> int:
    if not value:
        return default
    try:
        n = int(value)
    except ValueError:
        raise SetupError(f"{where}: {what} must be a whole number, not {value!r}.") from None
    if not lo <= n <= hi:
        raise SetupError(f"{where}: {what} must be between {lo} and {hi}.")
    return n


def _yes(value: str) -> bool:
    return value.strip().lower() in {"yes", "y", "true", "1", "x"}


def _rate_bp(value: str, where: str) -> int:
    if not value:
        return 0
    try:
        pct = float(value.replace("%", "").replace(",", "."))
    except ValueError:
        raise SetupError(f"{where}: the tax rate must be a number in percent, such as 7.5, not {value!r}.") from None
    if not 0 <= pct <= 100:
        raise SetupError(f"{where}: the tax rate must be between 0 and 100 percent.")
    return round(pct * 100)


# ----- vendors -----

def create_vendor(session: Session, settings, who: str, *, name: str, currency: str = "", tax_rate_bp: int = 0, requires_po: bool = False, bank_account: str = "", terms_days: int = 30, address: str = "") -> Vendor:
    name = limits.text(name, 160)
    if not name:
        raise SetupError("A vendor needs a name.")
    if session.scalar(select(Vendor.id).where(func.lower(Vendor.name) == name.lower())) is not None:
        raise SetupError(f"There is already a vendor called {name}.")
    v = Vendor(key=_next_key(session, Vendor, "V"), name=name, address=limits.text(address, 240), currency=_currency(currency, settings.base_currency, "Vendor"), tax_rate_bp=tax_rate_bp,
               requires_po=requires_po, bank_account=limits.text(bank_account, 80), terms_days=terms_days)
    session.add(v)
    session.flush()
    record_audit(session, who, "vendor.created", f"vendor:{v.id}", {"bank_account_on_file": bool(v.bank_account)})
    return v


def import_vendors(session: Session, settings, who: str, text: str) -> ImportReport:
    """Columns: name (needed), currency, tax_rate (percent), requires_po (yes or no), bank_account, terms_days, address. A vendor already on the list is left as it is."""
    rep, seen = ImportReport(), {n.lower() for n in session.scalars(select(Vendor.name))}
    todo = []
    for n, r in _rows(text, ("name",)):
        where = f"Line {n}"
        if not r["name"]:
            raise SetupError(f"{where}: the name is empty.")
        if r["name"].lower() in seen:
            rep.skipped.append(r["name"])
            continue
        seen.add(r["name"].lower())
        todo.append(dict(name=r["name"], currency=_currency(r.get("currency", ""), settings.base_currency, where), tax_rate_bp=_rate_bp(r.get("tax_rate", ""), where), requires_po=_yes(r.get("requires_po", "")),
                         bank_account=r.get("bank_account", ""), terms_days=_int(r.get("terms_days", ""), 30, where, "terms_days"), address=r.get("address", "")))
    for kw in todo:
        create_vendor(session, settings, who, **kw)
        rep.added += 1
    return rep


# ----- customers -----

def create_customer(session: Session, settings, who: str, *, name: str, email: str = "", timezone: str = "", terms_days: int = 30) -> Customer:
    name = limits.text(name, 160)
    if not name:
        raise SetupError("A customer needs a name.")
    if email and not is_valid_email(email):
        raise SetupError(f"{email!r} is not an email address.")
    if timezone and zone(timezone) is None:
        raise SetupError(f"{timezone!r} is not a time zone name (for example America/New_York).")
    if session.scalar(select(Customer.id).where(func.lower(Customer.name) == name.lower())) is not None:
        raise SetupError(f"There is already a customer called {name}.")
    c = Customer(key=_next_key(session, Customer, "C"), name=name, email=email.strip().lower(), timezone=timezone or settings.default_timezone, terms_days=terms_days)
    session.add(c)
    session.flush()
    record_audit(session, who, "customer.created", f"customer:{c.id}", {})
    return c


def import_customers(session: Session, settings, who: str, text: str) -> ImportReport:
    """Columns: name (needed), email, timezone (reminders go out in the customer's own hours), terms_days. A customer already on the list is left as it is."""
    rep, seen = ImportReport(), {n.lower() for n in session.scalars(select(Customer.name))}
    todo = []
    for n, r in _rows(text, ("name",)):
        where = f"Line {n}"
        if not r["name"]:
            raise SetupError(f"{where}: the name is empty.")
        if r["name"].lower() in seen:
            rep.skipped.append(r["name"])
            continue
        seen.add(r["name"].lower())
        if r.get("email") and not is_valid_email(r["email"]):
            raise SetupError(f"{where}: {r['email']!r} is not an email address.")
        if r.get("timezone") and zone(r["timezone"]) is None:
            raise SetupError(f"{where}: {r['timezone']!r} is not a time zone name (for example America/New_York).")
        todo.append(dict(name=r["name"], email=r.get("email", ""), timezone=r.get("timezone", ""), terms_days=_int(r.get("terms_days", ""), 30, where, "terms_days")))
    for kw in todo:
        create_customer(session, settings, who, **kw)
        rep.added += 1
    return rep


# ----- open invoices -----

def import_invoices(session: Session, settings, who: str, text: str) -> ImportReport:
    """Columns: number, customer (the name as on the customer list), issue_date, due_date (both 2026-03-14), total, currency (default the company currency), paid (default 0), paid_on (the day
    the last payment came, 2026-03-14, optional). Totals are written as on the invoice (1,250.00). An invoice number already in the system is left as it is.
    A fully paid invoice with no paid_on keeps no payment date, so it does not distort how late this customer usually pays."""
    rep = ImportReport()
    customers = {c.name.lower(): c for c in session.scalars(select(Customer))}
    have = set(session.scalars(select(Invoice.number)))
    todo = []
    for n, r in _rows(text, ("number", "customer", "issue_date", "due_date", "total")):
        where = f"Line {n}"
        number = limits.text(r["number"], 40)
        if not number:
            raise SetupError(f"{where}: the invoice number is empty.")
        if number in have:
            rep.skipped.append(number)
            continue
        have.add(number)
        cust = customers.get(r["customer"].lower())
        if cust is None:
            raise SetupError(f"{where}: there is no customer called {r['customer']!r}. Import the customers first, with the same spelling.")
        try:
            issue, due = date.fromisoformat(r["issue_date"]), date.fromisoformat(r["due_date"])
        except ValueError:
            raise SetupError(f"{where}: dates must look like 2026-03-14.") from None
        if due < issue:
            raise SetupError(f"{where}: the due date is before the invoice date.")
        cur = _currency(r.get("currency", ""), settings.base_currency, where)
        total = parse_amount(r["total"], cur)
        if total is not None and total[1] != cur:
            # The amount is written with its own currency (EUR 1,250.00). With a currency column that says otherwise there is no telling which is right, so the line is refused; with
            # no currency column the amount's own currency is the invoice's.
            if r.get("currency", "").strip():
                raise SetupError(f"{where}: the total is written in {total[1]} but the currency column says {cur}. Make them the same.")
            cur = total[1]
        paid = parse_amount(r["paid"], cur) if r.get("paid") else (0, cur)
        if paid is not None and paid[1] != cur:
            raise SetupError(f"{where}: what is paid is written in {paid[1]} but the invoice is in {cur}. Make them the same.")
        if total is None or paid is None or not 0 < total[0] <= limits.MAX_MINOR or not 0 <= paid[0] <= total[0]:
            raise SetupError(f"{where}: the total must be an amount above zero, and what is paid cannot be more than the total.")
        paid_on = None
        if r.get("paid_on"):
            try:
                paid_on = date.fromisoformat(r["paid_on"])
            except ValueError:
                raise SetupError(f"{where}: paid_on must look like 2026-03-14.") from None
            if paid_on < issue:
                raise SetupError(f"{where}: paid_on is before the invoice date.")
        todo.append(Invoice(customer_id=cust.id, number=number, issue_date=issue, due_date=due, currency=cur, total_minor=total[0], paid_minor=paid[0], status="paid" if paid[0] >= total[0] else "open",
                            paid_on=paid_on if paid[0] >= total[0] else None))
    session.add_all(todo)
    session.flush()
    rep.added = len(todo)
    if todo:
        record_audit(session, who, "invoices.imported", None, {"added": len(todo)})
    return rep


# ----- bank accounts, chart of accounts, repeating items -----

def create_bank_account(session: Session, settings, who: str, *, name: str, currency: str = "", opening_minor: int = 0, opening_date: date | None = None) -> BankAccount:
    name = limits.text(name, 120)
    if not name:
        raise SetupError("A bank account needs a name.")
    if not limits.in_range(opening_minor):
        raise SetupError("The opening balance is not a believable amount.")
    a = BankAccount(name=name, currency=_currency(currency, settings.base_currency, "Bank account"), opening_minor=opening_minor, opening_date=opening_date or date.today())
    session.add(a)
    session.flush()
    record_audit(session, who, "bank_account.created", f"bank_account:{a.id}", {"currency": a.currency})
    return a


def create_account(session: Session, who: str, *, code: str, name: str, kind: str) -> Account:
    code, name = limits.text(code, 12), limits.text(name, 120)
    if not code or not name:
        raise SetupError("An account needs a code and a name.")
    if kind not in ACCOUNT_KINDS:
        raise SetupError(f"The kind must be one of {', '.join(ACCOUNT_KINDS)}.")
    if session.scalar(select(Account.id).where(Account.code == code)) is not None:
        raise SetupError(f"There is already an account with the code {code}.")
    a = Account(code=code, name=name, kind=kind)
    session.add(a)
    session.flush()
    record_audit(session, who, "account.created", f"account:{a.id}", {"code": code})
    return a


def create_recurring(session: Session, who: str, *, name: str, direction: str, amount_minor: int, cadence: str, day: int = 1, match_text: str = "") -> RecurringItem:
    if direction not in ("in", "out"):
        raise SetupError("The direction must be in (money coming in) or out (money going out).")
    if cadence not in CADENCES:
        raise SetupError(f"The cadence must be one of {', '.join(CADENCES)}.")
    if not 0 < amount_minor <= limits.MAX_MINOR:
        raise SetupError("The amount must be above zero.")
    if not 1 <= day <= 31:
        raise SetupError("The day must be between 1 and 31.")
    r = RecurringItem(name=limits.text(name, 120), direction=direction, amount_minor=amount_minor, cadence=cadence, day=day, match_text=limits.text(match_text, 120))
    if not r.name:
        raise SetupError("A repeating item needs a name.")
    session.add(r)
    session.flush()
    record_audit(session, who, "recurring.created", f"recurring:{r.id}", {})
    return r
