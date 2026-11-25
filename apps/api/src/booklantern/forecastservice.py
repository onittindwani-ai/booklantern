"""Build the forecast inputs from the database, run the pure forecast, and word it."""

from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import bankservice, forecast as F, fx as FX, model_tasks
from booklantern.models import Bill, Customer, ExceptionItem, Forecast, Invoice, PromiseToPay, RecurringItem
from booklantern.money import format_minor


def customer_habits(session: Session) -> dict[int, int]:
    """Usual days late per customer, from their paid invoices. Integer average, rounded half up."""
    out: dict[int, list[int]] = {}
    for i in session.scalars(select(Invoice).where(Invoice.status == "paid", Invoice.paid_on.is_not(None))):
        out.setdefault(i.customer_id, []).append((i.paid_on - i.due_date).days)
    return {c: (sum(v) * 2 + len(v)) // (2 * len(v)) if sum(v) >= 0 else -((-sum(v) * 2 + len(v)) // (2 * len(v))) for c, v in out.items() if v}


def build_inputs(session: Session, ctx, as_of: date, report: FX.FxReport | None = None) -> F.Inputs:
    """Everything the forecast needs, in the company currency. Items in another currency are converted at the manual rate of `as_of`
    and listed in `report`; an item with no rate is left out and listed there as well. Nothing is ever added in the wrong currency."""
    report = report if report is not None else FX.FxReport(ctx.settings.base_currency)
    book = ctx.rates(session)
    excluded_bills = {e.ref_id for e in session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.kind == "duplicate_exact", ExceptionItem.status == "open"))}
    promises: dict[int, date] = {}
    for p in session.scalars(select(PromiseToPay).where(PromiseToPay.status == "open")):
        promises[p.invoice_id] = max(promises.get(p.invoice_id, p.promised_on), p.promised_on)
    cust = {c.id: c for c in session.scalars(select(Customer))}
    ar = []
    for i in session.scalars(select(Invoice).where(Invoice.status == "open")):
        why = "dispute" if i.disputed else "bankruptcy" if cust[i.customer_id].bankruptcy_flag else ""
        left = i.total_minor - i.paid_minor
        c = book.try_convert(left, i.currency, as_of)
        if c is None:
            report.leave_out("invoice", i.id, i.number, left, i.currency, as_of)
            continue
        ar.append(F.ArItem(i.id, i.customer_id, i.due_date, report.add("invoice", i.id, i.number, c), promises.get(i.id), why))
    ap = []
    for b in session.scalars(select(Bill).where(Bill.status.in_(("approved", "posted_draft", "needs_review", "inbox")), Bill.due_date.is_not(None))):
        if b.id in excluded_bills:
            continue
        amt = b.total_minor - b.paid_minor
        c = book.try_convert(amt, b.currency, as_of)
        if c is None:
            report.leave_out("bill", b.id, b.number, amt, b.currency, as_of)
            continue
        ap.append(F.ApItem(b.id, b.due_date, report.add("bill", b.id, b.number, c)))
    rec = [F.Recurring(r.name, r.direction, r.amount_minor, r.cadence, r.day) for r in session.scalars(select(RecurringItem).where(RecurringItem.active.is_(True)))]
    recent = 0
    for i in session.scalars(select(Invoice).where(Invoice.issue_date > as_of - timedelta(days=91), Invoice.issue_date <= as_of)):
        c = book.try_convert(i.total_minor, i.currency, i.issue_date)
        if c is not None:
            recent += c.base_minor
    return F.Inputs(as_of, bankservice.balance(session), ar, ap, rec, customer_habits(session), {**F.DEFAULT_PROB_BP, **ctx.settings.probs()}, recent // 13)


def scenario_from(d: dict) -> F.Scenario:
    return F.Scenario(int(d.get("collect_delay_days", 0)), int(d.get("pay_delay_days", 0)), tuple((int(a), int(b)) for a, b in d.get("hires", [])), tuple((int(a), int(b)) for a, b in d.get("one_offs", [])))


def compute(session: Session, ctx, scenario: dict | None = None) -> dict:
    report = FX.FxReport(ctx.settings.base_currency)
    inp = build_inputs(session, ctx, ctx.today(session), report)
    res = F.run(inp, scenario_from(scenario or {}))
    res["currency"] = ctx.settings.base_currency
    res["fx"] = report.to_dict()
    res["scenario"] = scenario or {}
    res["excluded_receivables"] = [{"invoice_id": a.id, "reason": a.excluded, "minor": a.outstanding_minor} for a in inp.ar if a.excluded]
    return res


def explain(session: Session, ctx, res: dict, live: bool = True) -> str:
    """The model (or the offline stand in) only words numbers the code already computed."""
    f = lambda m: format_minor(m, ctx.settings.base_currency)  # noqa: E731
    facts = {"opening": f(res["opening_minor"]), "closing": f(res["closing_minor"]), "low": f(res["low_point_minor"]), "low_week": res["low_point_week"], "receipts": f(res["total_receipts_minor"]),
             "runs_out": res["runs_out_in_week"], "beyond": f(res["beyond_horizon_minor"]) if res["beyond_horizon_minor"] else "", "weeks": F.WEEKS}
    return model_tasks.explain_forecast(ctx.llm(session, live), facts)


def save(session: Session, ctx, res: dict) -> Forecast:
    row = Forecast(as_of=date.fromisoformat(res["as_of"]), weeks=res["weeks"], assumptions={"prob_bp": ctx.settings.probs(), "scenario": res.get("scenario", {})}, explanation=explain(session, ctx, res), created_at=ctx.now(session))
    session.add(row)
    session.flush()
    return row
