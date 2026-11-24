"""Exchange rates entered by hand, and the one place a number changes currency.

Rules, all tested:
  * A rate is a Decimal written as text (for example 1.0800): units of the company currency for one unit of the other currency.
    A float is refused. Amounts stay integers in minor units; only the rate and the conversion step use Decimal.
  * A rate has a date. For a given day the latest rate dated on or before that day is used. A rate dated later is never used.
  * No rate means no number. `RateBook.convert` raises `NoRateError`; callers leave the item out and say so. Nothing is ever
    converted at 1.0 or at an old guess.
  * Every conversion returns a `Converted` that keeps the original amount, the rate and its date, so a screen or an export can
    show where the number came from. A rate older than `stale_days` is marked stale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from booklantern.money import MoneyError, convert, exponent

_RATE = re.compile(r"^\d{1,6}(\.\d{1,8})?$")


class FxError(ValueError):
    pass


class NoRateError(FxError):
    def __init__(self, currency: str, on: date):
        super().__init__(f"No exchange rate for {currency} on or before {on.isoformat()}.")
        self.currency, self.on = currency, on


def parse_rate(value: str | int | Decimal) -> Decimal:
    """Read a rate typed by a person. Plain digits with an optional decimal point, above zero, at most 8 decimals."""
    if isinstance(value, float):
        raise FxError("Type the rate as text such as 1.0800, not as a float.")
    text = str(value).strip()
    if not _RATE.match(text):
        raise FxError("A rate is digits with an optional decimal point, for example 1.0800 (at most 8 decimals).")
    try:
        d = Decimal(text)
    except InvalidOperation as exc:
        raise FxError("That is not a rate.") from exc
    if d <= 0:
        raise FxError("A rate must be above zero.")
    return d


def check_currency(code: str) -> str:
    code = (code or "").strip().upper()
    try:
        exponent(code)
    except MoneyError as exc:
        raise FxError(str(exc)) from exc
    return code


@dataclass(frozen=True)
class Rate:
    currency: str
    rate_date: date
    rate: Decimal
    note: str = ""
    id: int | None = None


@dataclass(frozen=True)
class Converted:
    """An amount in the company currency with everything needed to show where it came from."""

    original_minor: int
    original_currency: str
    base_minor: int
    base_currency: str
    rate: str  # the Decimal as text
    rate_date: date | None
    converted: bool  # False when the currency already was the company currency
    stale: bool = False

    def to_dict(self) -> dict:
        return {"original_minor": self.original_minor, "original_currency": self.original_currency, "base_minor": self.base_minor, "base_currency": self.base_currency,
                "rate": self.rate, "rate_date": self.rate_date.isoformat() if self.rate_date else None, "converted": self.converted, "stale": self.stale}


@dataclass
class RateBook:
    base: str
    rates: list[Rate] = field(default_factory=list)
    stale_days: int = 45

    def lookup(self, currency: str, on: date) -> Rate:
        best: Rate | None = None
        for r in self.rates:
            if r.currency == currency and r.rate_date <= on and (best is None or r.rate_date > best.rate_date):
                best = r
        if best is None:
            raise NoRateError(currency, on)
        return best

    def convert(self, minor: int, currency: str, on: date) -> Converted:
        if currency == self.base:
            return Converted(minor, currency, minor, self.base, "1", None, False)
        r = self.lookup(currency, on)
        return Converted(minor, currency, convert(minor, currency, self.base, r.rate), self.base, format(r.rate, "f"), r.rate_date, True, (on - r.rate_date).days > self.stale_days)

    def try_convert(self, minor: int, currency: str, on: date) -> Converted | None:
        try:
            return self.convert(minor, currency, on)
        except NoRateError:
            return None

    def back(self, base_minor: int, currency: str, on: date) -> int:
        """An amount in the company currency expressed in `currency` at the rate of that day (used to compare a bank line with an open item)."""
        r = self.lookup(currency, on)
        inverse = (Decimal(1) / r.rate)
        return convert(base_minor, self.base, currency, inverse)


class FxReport:
    """Collects what was converted and what was left out while one number is built, so the screen can say so."""

    def __init__(self, base: str):
        self.base = base
        self.items: list[dict] = []
        self.missing: list[dict] = []

    def add(self, kind: str, ref: int, label: str, c: Converted) -> int:
        if c.converted:
            self.items.append({"kind": kind, "id": ref, "label": label, **c.to_dict()})
        return c.base_minor

    def leave_out(self, kind: str, ref: int, label: str, minor: int, currency: str, on: date) -> None:
        self.missing.append({"kind": kind, "id": ref, "label": label, "original_minor": minor, "original_currency": currency, "reason": "no_rate",
                             "detail": f"No exchange rate for {currency} on or before {on.isoformat()}. Left out of the totals until a rate is entered."})

    def merge(self, other: FxReport) -> FxReport:
        """Add another report's entries, once per item, so a number that appears in two totals is not counted twice."""
        seen = {(i["kind"], i["id"]) for i in self.items}
        self.items += [i for i in other.items if (i["kind"], i["id"]) not in seen]
        seen_m = {(i["kind"], i["id"]) for i in self.missing}
        self.missing += [i for i in other.missing if (i["kind"], i["id"]) not in seen_m]
        return self

    def absorb(self, d: dict) -> FxReport:
        """Add the entries of another report's `to_dict()` output, once per item."""
        other = FxReport(self.base)
        other.items, other.missing = list(d.get("converted", [])), list(d.get("missing", []))
        return self.merge(other)

    def to_dict(self, with_items: bool = True) -> dict:
        used: dict[tuple[str, str], dict] = {}
        for it in self.items:
            used[(it["original_currency"], it["rate_date"])] = {"currency": it["original_currency"], "rate": it["rate"], "rate_date": it["rate_date"], "stale": it["stale"]}
        out = {"base": self.base, "converted_count": len(self.items), "missing_count": len(self.missing), "rates_used": sorted(used.values(), key=lambda r: (r["currency"], r["rate_date"] or ""))}
        if with_items:
            out.update({"converted": self.items, "missing": self.missing})
        return out
