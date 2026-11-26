"""Exchange rates in the database, and the helpers every total uses so a conversion is never silent."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import fx as FX
from booklantern.exceptions import clear_open, raise_exception
from booklantern.models import Bill, FxRate, Invoice
from sendora_core.audit import record_audit

MISSING = "missing_fx_rate"
STALE_DAYS = 45
JUMP_WARN = Decimal("0.25")  # a new rate more than 25 percent away from the one before it earns a warning, not a refusal


def rate_book(session: Session, ctx) -> FX.RateBook:
    rows = session.scalars(select(FxRate).order_by(FxRate.currency, FxRate.rate_date))
    rates = [FX.Rate(r.currency, r.rate_date, Decimal(r.rate), r.note, r.id) for r in rows]
    return FX.RateBook(ctx.settings.base_currency, rates, STALE_DAYS)


def list_rates(session: Session) -> list[dict]:
    rows = session.scalars(select(FxRate).order_by(FxRate.currency, FxRate.rate_date.desc()))
    return [{"id": r.id, "currency": r.currency, "rate_date": r.rate_date.isoformat(), "rate": r.rate, "note": r.note, "entered_by": r.entered_by} for r in rows]


def set_rate(session: Session, ctx, currency: str, rate_date: date, rate_text: str, note: str, actor: str) -> dict:
    """Add a rate, or correct the one for the same currency and date. Both are written to the audit log. Returns the row and any warning."""
    cur = FX.check_currency(currency)
    if cur == ctx.settings.base_currency:
        raise FX.FxError(f"{cur} is the company currency, it needs no rate.")
    rate = FX.parse_rate(rate_text)
    if rate_date > ctx.today(session):
        raise FX.FxError("A rate cannot be dated in the future.")
    prev = session.scalars(select(FxRate).where(FxRate.currency == cur, FxRate.rate_date < rate_date).order_by(FxRate.rate_date.desc())).first()
    warning = ""
    if prev is not None and abs(rate - Decimal(prev.rate)) / Decimal(prev.rate) > JUMP_WARN:
        warning = f"This is more than 25 percent away from the rate of {prev.rate_date.isoformat()} ({prev.rate}). Check you typed it the right way round: the rate is {ctx.settings.base_currency} for one {cur}."
    row = session.scalars(select(FxRate).where(FxRate.currency == cur, FxRate.rate_date == rate_date)).first()
    before = row.rate if row else None
    if row is None:
        row = FxRate(currency=cur, rate_date=rate_date, rate=format(rate, "f"), note=note[:160], entered_by=actor, created_at=ctx.now(session))
        session.add(row)
    else:
        row.rate, row.note, row.entered_by = format(rate, "f"), note[:160], actor
    session.flush()
    record_audit(session, actor, "fx_rate.set", f"fx_rate:{row.id}", {"currency": cur, "rate_date": rate_date.isoformat(), "rate": row.rate, "before": before})
    flag_missing(session, ctx)
    return {"id": row.id, "currency": cur, "rate_date": rate_date.isoformat(), "rate": row.rate, "warning": warning}


def flag_missing(session: Session, ctx) -> int:
    """One exception per open item in another currency that has no rate yet. Cleared as soon as a rate covers it."""
    book, today, n = rate_book(session, ctx), ctx.today(session), 0
    for kind, rows in (("invoice", session.scalars(select(Invoice).where(Invoice.status == "open", Invoice.currency != ctx.settings.base_currency))),
                       ("bill", session.scalars(select(Bill).where(Bill.status.in_(("needs_review", "inbox", "approved", "posted_draft")), Bill.currency != ctx.settings.base_currency)))):
        for r in rows:
            if book.try_convert(r.total_minor, r.currency, today) is None:
                raise_exception(session, MISSING, "warning", kind, r.id, f"No exchange rate for {r.currency} on or before {today.isoformat()}. This {kind} is left out of totals, aging and the forecast until a rate is entered.")
                n += 1
            else:
                clear_open(session, kind, r.id, {MISSING})
    return n


def load_seed_rates(session: Session, seed: dict, now) -> int:
    """The demo seed ships one sample rate per currency, dated at the start of the data so every seeded line can be converted."""
    start = date.fromisoformat(seed["bank_account"]["opening_date"])
    n = 0
    for cur, bp in seed.get("fx_rates_bp", {}).items():
        session.add(FxRate(currency=cur, rate_date=start, rate=format((Decimal(bp) / Decimal(10_000)).quantize(Decimal("0.0001")), "f"), note="Demo rate, sample", entered_by="seed", created_at=now))
        n += 1
    session.flush()
    return n


def describe(book: FX.RateBook, minor: int, currency: str, on: date) -> dict | None:
    """What a row shows next to an amount in another currency: the converted amount with its rate and date, or a plain no-rate flag. None for the company currency."""
    if currency == book.base:
        return None
    c = book.try_convert(minor, currency, on)
    if c is None:
        return {"converted": False, "missing": True, "original_minor": minor, "original_currency": currency, "base_currency": book.base}
    return {**c.to_dict(), "missing": False}


PAYABLE_STATES = ("needs_review", "inbox", "approved", "posted_draft")


def payables(session: Session, ctx, as_of: date, report: FX.FxReport | None = None) -> int:
    """What is owed on unpaid bills, in the company currency. Bills with no rate are left out and listed in `report`."""
    book = rate_book(session, ctx)
    report = report if report is not None else FX.FxReport(book.base)
    total = 0
    for b in session.scalars(select(Bill).where(Bill.status.in_(PAYABLE_STATES))):
        left = b.total_minor - b.paid_minor
        c = book.try_convert(left, b.currency, as_of)
        if c is None:
            report.leave_out("bill", b.id, b.number, left, b.currency, as_of)
            continue
        total += report.add("bill", b.id, b.number, c)
    return total
