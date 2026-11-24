"""The 13 week cash forecast. One pure, deterministic function. Money is integers; probabilities are basis points.

Method (also in docs/ARCHITECTURE.md):
  Receivables: each open invoice gets an expected date and a probability. The expected cash is mul_bp(outstanding, probability), rounded once
  per invoice (not on the total). Expected date: the promised date if there is an open promise, otherwise due date plus the customer's usual
  days late (never earlier than tomorrow; an invoice already late is expected `catch_up_days` after today). Probability: 95 percent when a promise
  is open and not broken, otherwise by aging bucket today. Disputed and bankruptcy invoices count for nothing until that changes.
  Payables: each unpaid bill is paid on its due date (a bill already due is paid in week 1), in full.
  Recurring items: expanded into dated amounts. Week i covers as_of + 7i to as_of + 7i + 6. Cash past week 13 is reported, not counted.
Decided defaults: the probabilities (95, 90, 75, 50 and 20 percent by aging group), catch up days and promise probability. The implementer can change them with COLLECTION_PROB_BP.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from booklantern.aging import bucket_for, days_late
from booklantern.money import allocate, mul_bp

WEEKS = 13
DEFAULT_PROB_BP = {"current": 9500, "1-30": 9000, "31-60": 7500, "61-90": 5000, "90+": 2000}
PROMISE_PROB_BP = 9500
CATCH_UP_DAYS = {"current": 0, "1-30": 7, "31-60": 14, "61-90": 21, "90+": 30}


@dataclass(frozen=True)
class ArItem:
    id: int
    customer_id: int
    due: date
    outstanding_minor: int
    promise_date: date | None = None
    excluded: str = ""  # dispute or bankruptcy


@dataclass(frozen=True)
class ApItem:
    id: int
    due: date
    outstanding_minor: int  # in the base currency


@dataclass(frozen=True)
class Recurring:
    name: str
    direction: str  # in or out
    amount_minor: int  # positive
    cadence: str  # monthly, twice_monthly, weekly
    day: int = 1


@dataclass(frozen=True)
class Scenario:
    collect_delay_days: int = 0
    pay_delay_days: int = 0
    hires: tuple[tuple[int, int], ...] = ()  # (monthly cost minor, start week 1 to 13)
    one_offs: tuple[tuple[int, int], ...] = ()  # (week 1 to 13, signed amount)


@dataclass
class Inputs:
    as_of: date
    opening_cash_minor: int
    ar: list[ArItem] = field(default_factory=list)
    ap: list[ApItem] = field(default_factory=list)
    recurring: list[Recurring] = field(default_factory=list)
    customer_habit_days: dict[int, int] = field(default_factory=dict)
    prob_bp: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_PROB_BP))
    new_sales_weekly_minor: int = 0  # average invoiced per week over the last 13 weeks, collected `new_sales_lag_weeks` later
    new_sales_lag_weeks: int = 6


def _month_add(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


def occurrences(r: Recurring, start: date, end: date) -> list[date]:
    out: list[date] = []
    if r.cadence == "weekly":
        d = start
        while d <= end:
            out.append(d)
            d += timedelta(days=7)
        return out
    days = [r.day] if r.cadence == "monthly" else [r.day, min(r.day + 13, 28)]
    first = date(start.year, start.month, 1)
    for m in range(0, 5):
        base = _month_add(first, m)
        last = calendar.monthrange(base.year, base.month)[1]
        for dd in days:
            d = date(base.year, base.month, min(dd, last))
            if start <= d <= end:
                out.append(d)
    return sorted(out)


def week_of(d: date, as_of: date) -> int | None:
    i = (d - as_of).days // 7
    return i if 0 <= i < WEEKS else None


def expected_receipt(it: ArItem, inp: Inputs, sc: Scenario) -> tuple[date, int] | None:
    if it.excluded or it.outstanding_minor <= 0:
        return None
    bucket = bucket_for(days_late(it.due, inp.as_of))
    if it.promise_date is not None and it.promise_date >= inp.as_of:
        when, p = it.promise_date, PROMISE_PROB_BP
    else:
        when = it.due + timedelta(days=inp.customer_habit_days.get(it.customer_id, 0))
        p = inp.prob_bp[bucket]
        if when <= inp.as_of:
            when = inp.as_of + timedelta(days=max(1, CATCH_UP_DAYS[bucket]))
    when += timedelta(days=sc.collect_delay_days)
    return when, mul_bp(it.outstanding_minor, p)


def run(inp: Inputs, sc: Scenario = Scenario()) -> dict:
    weeks = [{"index": i + 1, "start": (inp.as_of + timedelta(days=7 * i)).isoformat(), "receipts_minor": 0, "bills_minor": 0, "recurring_in_minor": 0, "recurring_out_minor": 0, "other_minor": 0, "new_sales_minor": 0} for i in range(WEEKS)]
    end = inp.as_of + timedelta(days=7 * WEEKS - 1)
    beyond = 0
    for it in inp.ar:
        got = expected_receipt(it, inp, sc)
        if not got:
            continue
        when, cash = got
        w = week_of(when, inp.as_of)
        if w is None:
            beyond += cash
        else:
            weeks[w]["receipts_minor"] += cash
    if inp.new_sales_weekly_minor > 0:
        for wk in range(inp.new_sales_lag_weeks, WEEKS):
            weeks[wk]["new_sales_minor"] += mul_bp(inp.new_sales_weekly_minor, inp.prob_bp["current"]) if sc.collect_delay_days < 7 * (wk - inp.new_sales_lag_weeks + 1) else 0
    for b in inp.ap:
        when = max(b.due, inp.as_of) + timedelta(days=sc.pay_delay_days)
        w = week_of(when, inp.as_of)
        if w is not None:
            weeks[w]["bills_minor"] -= b.outstanding_minor
    for r in inp.recurring:
        for d in occurrences(r, inp.as_of, end):
            w = week_of(d, inp.as_of)
            if w is not None:
                weeks[w]["recurring_in_minor" if r.direction == "in" else "recurring_out_minor"] += r.amount_minor if r.direction == "in" else -r.amount_minor
    for monthly, start_week in sc.hires:
        for wk in range(start_week - 1, WEEKS, 4):
            weeks[wk]["other_minor"] -= monthly
    for wk, amt in sc.one_offs:
        weeks[max(0, min(WEEKS - 1, wk - 1))]["other_minor"] += amt
    cash = inp.opening_cash_minor
    low = None
    for w in weeks:
        w["net_minor"] = w["receipts_minor"] + w["new_sales_minor"] + w["bills_minor"] + w["recurring_in_minor"] + w["recurring_out_minor"] + w["other_minor"]
        w["opening_minor"] = cash
        cash += w["net_minor"]
        w["closing_minor"] = cash
        if low is None or cash < low[0]:
            low = (cash, w["index"])
    return {"as_of": inp.as_of.isoformat(), "opening_minor": inp.opening_cash_minor, "weeks": weeks, "closing_minor": cash, "low_point_minor": low[0], "low_point_week": low[1],
            "total_receipts_minor": sum(w["receipts_minor"] + w["new_sales_minor"] for w in weeks), "beyond_horizon_minor": beyond,
            "runs_out_in_week": next((w["index"] for w in weeks if w["closing_minor"] < 0), None)}


def split_evenly(total_minor: int, parts: int) -> list[int]:
    return allocate(total_minor, [1] * parts)
