"""The month end pack as a PDF, built by code. Every number comes from the database through the same functions the screens use."""

from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import bankservice, collections, forecastservice, fx as FX, labels
from booklantern.models import BankTransaction, Bill, ExceptionItem, Invoice
from booklantern.money import format_minor


def summary(session: Session, ctx) -> dict:
    cur = ctx.settings.base_currency
    today = ctx.today(session)
    ag = collections.aging_report(session, today, ctx.rates(session))
    return {"as_of": today.isoformat(), "currency": cur, "cash_minor": bankservice.balance(session), "receivable_minor": ag["total_minor"], "fx": FX.FxReport(cur).absorb(ag["fx"]).absorb(forecastservice.compute(session, ctx)["fx"]).to_dict(with_items=False),
            "bills_to_review": session.query(Bill).filter(Bill.status.in_(("needs_review", "inbox"))).count(), "open_invoices": session.query(Invoice).filter_by(status="open").count(),
            "unmatched_lines": session.query(BankTransaction).filter(BankTransaction.status.in_(("unmatched", "exception"))).count(),
            "open_exceptions": session.query(ExceptionItem).filter_by(status="open").count()}


def _table(rows: list[list[str]], widths: list[float] | None = None) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7dfd2")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b9ab96")), ("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
    return t


def fx_note(r: FX.FxReport, cur: str) -> str:
    d = r.to_dict(with_items=False)
    if not d["converted_count"] and not d["missing_count"]:
        return f"Every amount in this pack is in {cur}. Nothing was converted."
    rates = ", ".join(f"{x['currency']} at {x['rate']} dated {x['rate_date']}" + (" (old)" if x["stale"] else "") for x in d["rates_used"])
    left = f" {d['missing_count']} item(s) have no exchange rate and are left out of the totals above." if d["missing_count"] else ""
    return f"Amounts in other currencies are converted into {cur} at manual rates ({rates or 'none used'}): {d['converted_count']} item(s) converted.{left} The original amounts are listed below. Rates are typed in by a person, not fetched from a market feed."


def fx_lines(r: FX.FxReport) -> list[str]:
    seen, out = set(), []
    for it in r.items:
        key = (it["kind"], it["id"])
        if key in seen or len(out) >= 40:
            continue
        seen.add(key)
        out.append(f"{it['kind'].title()} {it['label']}: {format_minor(it['original_minor'], it['original_currency'])} converted to {format_minor(it['base_minor'], it['base_currency'])} at {it['rate']} dated {it['rate_date']}.")
    for it in r.missing:
        out.append(f"{it['kind'].title()} {it['label']}: {format_minor(it['original_minor'], it['original_currency'])} left out, no exchange rate.")
    return out


def build(session: Session, ctx) -> bytes:
    st = getSampleStyleSheet()
    cur = ctx.settings.base_currency
    f = lambda m: format_minor(m, cur)  # noqa: E731
    sm = summary(session, ctx)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Month end pack", author="Booklantern")
    out = [Paragraph(f"Month end pack, as of {sm['as_of']}", st["Title"]), Paragraph("Prepared by code from the data in this system. This is a working pack, not accounting or tax advice. Sample data in the demo is fictional.", st["Normal"]), Spacer(1, 12)]
    out += [_table([["Measure", "Value"], ["Cash on the bank statements", f(sm["cash_minor"])], ["Receivables outstanding", f(sm["receivable_minor"])], ["Open invoices", str(sm["open_invoices"])],
                    ["Bills waiting for review", str(sm["bills_to_review"])], ["Bank lines not matched", str(sm["unmatched_lines"])], ["Open exceptions", str(sm["open_exceptions"])]], [260, 140]), Spacer(1, 14)]
    ag = collections.aging_report(session, ctx.today(session), ctx.rates(session))
    out += [Paragraph("Receivables aging", st["Heading2"]), _table([["Bucket", "Amount"]] + [[labels.BUCKET.get(k, k), f(v)] for k, v in ag["buckets_minor"].items()] + [["Total", f(ag["total_minor"])]], [260, 140]), Spacer(1, 14)]
    ex = list(session.scalars(select(ExceptionItem).where(ExceptionItem.status == "open").order_by(ExceptionItem.severity.desc(), ExceptionItem.id)))
    more = max(0, len(ex) - 40)
    ex = ex[:40]
    out += [Paragraph("Open exceptions", st["Heading2"]), _table([["Kind", "Where", "Detail"]] + [[Paragraph(labels.finding(e.kind), st["BodyText"]), labels.where(e.ref_type, e.ref_id), Paragraph(e.detail, st["BodyText"])] for e in ex] if ex else [["None", "", ""]], [110, 80, 300]), Spacer(1, 14)]
    if more:
        out.append(Paragraph(f"And {more} more open exceptions. They are all on the Exceptions page.", st["BodyText"]))
    res = forecastservice.compute(session, ctx)
    out += [Paragraph("13 week cash forecast", st["Heading2"]), _table([["Week", "Starts", "Receipts", "Bills", "Recurring", "Closing"]] +
                                                                  [[str(w["index"]), w["start"], f(w["receipts_minor"] + w["new_sales_minor"]), f(w["bills_minor"]), f(w["recurring_out_minor"] + w["recurring_in_minor"]), f(w["closing_minor"])] for w in res["weeks"]]),
            Spacer(1, 8), Paragraph(f"Lowest point {f(res['low_point_minor'])} in week {res['low_point_week']}. Collection probabilities and the new sales assumption are defaults that the owner sets.", st["Normal"])]
    fxr = FX.FxReport(cur)
    for part in (ag["fx"], res["fx"]):
        fxr.absorb(part)
    out += [Spacer(1, 14), Paragraph("Exchange rates", st["Heading2"]), Paragraph(fx_note(fxr, cur), st["Normal"])]
    for line in fx_lines(fxr):
        out.append(Paragraph(line, st["BodyText"]))
    doc.build(out)
    return buf.getvalue()
