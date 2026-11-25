"""Read only routes: numbers and lists for the pages."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import bankservice, collections, posting, forecastservice, fx as FX, fxservice, model_tasks, report_pdf, reminders as R
from booklantern.api.deps import db, get_ctx, user
from sendora_core.auth import WRITE_ROLES
from booklantern.api.serializers import bill_row, customer_row, invoice_row, iso, reminder_row
from booklantern.context import Ctx
from booklantern.money import format_minor
from booklantern.models import BankTransaction, Bill, Customer, Document, ExceptionItem, Invoice, Match, PromiseToPay, Reminder, Vendor
from sendora_core.models import Approval

router = APIRouter(prefix="/api", tags=["read"])
MAX_RENDER_PIXELS = 4_000_000  # about 2000 x 2000: far more than the review screen shows


@router.get("/overview", summary="Numbers for the cash cockpit header")
def overview(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    sm = report_pdf.summary(s, ctx)
    res = forecastservice.compute(s, ctx)
    today = ctx.today(s)
    ag = collections.aging_report(s, today, ctx.rates(s))
    pay = FX.FxReport(ctx.settings.base_currency)
    payable = fxservice.payables(s, ctx, today, pay)
    rep = FX.FxReport(ctx.settings.base_currency)
    for part in (sm["fx"], res["fx"], ag["fx"], pay.to_dict()):
        rep.absorb(part)
    sm.update({"fx": rep.to_dict(with_items=False), "low_point_minor": res["low_point_minor"], "low_point_week": res["low_point_week"], "runs_out_in_week": res["runs_out_in_week"], "pending_approvals": s.query(Approval).filter_by(status="pending").count(),
               "overdue_minor": sum(v for k, v in ag["buckets_minor"].items() if k != "current"),
               "payable_minor": payable, "demo_mode": ctx.settings.demo_shortcuts})
    return sm


@router.get("/forecast", summary="The 13 week forecast, with an optional scenario. Computed by code, deterministic.")
def forecast(collect_delay_days: int = Query(0, ge=0, le=90), pay_delay_days: int = Query(0, ge=0, le=90), hire_monthly_minor: int = Query(0, ge=0, le=100_000_000), hire_week: int = Query(1, ge=1, le=13),
             s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    sc = {"collect_delay_days": collect_delay_days, "pay_delay_days": pay_delay_days, "hires": [[hire_monthly_minor, hire_week]] if hire_monthly_minor else []}
    res = forecastservice.compute(s, ctx, sc)
    base = forecastservice.compute(s, ctx) if any(sc.values()) else res
    res["base_closing"] = [w["closing_minor"] for w in base["weeks"]]
    return res


@router.get("/forecast/explain", summary="A short written explanation of the forecast. The model only words numbers the code computed.")
def forecast_explain(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(user)):
    live = u["role"] in WRITE_ROLES  # a read only visitor gets the offline wording: opening a page must never cost money
    return {"text": forecastservice.explain(s, ctx, forecastservice.compute(s, ctx), live), "writer": "language model (UNVERIFIED)" if ctx.settings.effective_llm_backend.value == "anthropic" else "offline stand in (not a language model)"}


@router.get("/overview/explain", summary="Two plain sentences about the month end counts. The model only words counts the code computed.")
def overview_explain(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(user)):
    sm = report_pdf.summary(s, ctx)
    facts = {"open_invoices": sm["open_invoices"], "receivable": format_minor(sm["receivable_minor"], sm["currency"]), "bills_to_review": sm["bills_to_review"], "unmatched": sm["unmatched_lines"], "exceptions": sm["open_exceptions"]}
    return {"text": model_tasks.summarise_month(ctx.llm(s, u["role"] in WRITE_ROLES), facts), "writer": "language model (UNVERIFIED)" if ctx.settings.effective_llm_backend.value == "anthropic" else "offline stand in (not a language model)"}


@router.get("/documents", summary="Documents received")
def documents(s: Session = Depends(db)):
    bills = {b.document_id: b.id for b in s.scalars(select(Bill)) if b.document_id}
    return [{"id": d.id, "ref": d.ref, "file_name": d.file_name, "source": d.source, "status": d.status, "pages": d.page_count, "readable": d.has_text_layer, "received_at": iso(d.received_at), "bill_id": bills.get(d.id), "extractor": d.extractor}
            for d in s.scalars(select(Document).order_by(Document.id.desc()))]


@router.get("/documents/{doc_id}/extraction", summary="Fields, confidence and page boxes for one document")
def extraction(doc_id: int, s: Session = Depends(db)):
    d = s.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "No such document.")
    return {"id": d.id, "ref": d.ref, "status": d.status, "extractor": d.extractor, "extraction": d.extraction}


@router.get("/documents/{doc_id}/page/{n}.png", summary="One page of a document as a picture, for the review screen")
def page_image(doc_id: int, n: int, s: Session = Depends(db)):
    d = s.get(Document, doc_id)
    if d is None or n < 1 or n > max(d.page_count, 1):
        raise HTTPException(404, "No such page.")
    p = Path(d.stored_path)
    if not p.exists():
        raise HTTPException(404, "No picture for this file.")
    if d.mime in ("image/png", "image/jpeg"):  # a photo or scan is already a picture: show it as it came
        return Response(p.read_bytes(), media_type=d.mime, headers={"cache-control": "private, no-store"})
    if d.mime != "application/pdf":
        raise HTTPException(404, "No picture for this file.")
    try:
        page = pdfium.PdfDocument(p.read_bytes())[n - 1]
        w, h = page.get_size()
        # A page that claims to be enormous must not ask for a huge picture: the scale is lowered until the picture is at most MAX_RENDER_PIXELS.
        scale = min(1.6, (MAX_RENDER_PIXELS / max(w * h, 1.0)) ** 0.5)
        img = page.render(scale=scale).to_pil()
    except Exception as exc:
        raise HTTPException(404, "This file could not be drawn.") from exc
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"cache-control": "private, no-store"})


@router.get("/bills", summary="Bills, newest first")
def bills(status: str | None = None, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    q = select(Bill).order_by(Bill.id.desc())
    if status:
        q = q.where(Bill.status.in_(status.split(",")))
    vend = {v.id: v for v in s.scalars(select(Vendor))}
    book, today = ctx.rates(s), ctx.today(s)
    fl: dict[int, list[dict]] = {}
    for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.status == "open")):
        fl.setdefault(e.ref_id, []).append({"kind": e.kind, "severity": e.severity})
    return [bill_row(b, vend.get(b.vendor_id), fl.get(b.id), fxservice.describe(book, b.total_minor, b.currency, today)) for b in s.scalars(q.limit(500))]


@router.get("/bills/{bill_id}", summary="One bill with its lines, findings and document")
def bill_detail(bill_id: int, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(user)):
    b = s.get(Bill, bill_id)
    if b is None:
        raise HTTPException(404, "No such bill.")
    v = s.get(Vendor, b.vendor_id) if b.vendor_id else None
    ex = [{"id": e.id, "kind": e.kind, "severity": e.severity, "detail": e.detail, "status": e.status} for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == b.id))]
    d = s.get(Document, b.document_id) if b.document_id else None
    out = bill_row(b, v, [{"kind": e["kind"], "severity": e["severity"]} for e in ex if e["status"] == "open"], fxservice.describe(ctx.rates(s), b.total_minor, b.currency, ctx.today(s)))
    out.update({"lines": [{"id": x.id, "description": x.description, "quantity_milli": x.quantity_milli, "unit_minor": x.unit_minor, "total_minor": x.total_minor} for x in b.lines], "exceptions": ex,
                "vendor_record": {"name": v.name, "bank_account": v.bank_account, "currency": v.currency, "tax_rate_bp": v.tax_rate_bp, "requires_po": v.requires_po} if v else None,
                "document": {"id": d.id, "ref": d.ref, "pages": d.page_count, "readable": d.has_text_layer, "extraction": d.extraction} if d else None,
                "self_review": "" if not posting.self_review(s, b, u["user"]) else ("owner" if u["role"] == "owner" else "blocked")})  # "owner": needs a written reason, "blocked": someone else has to approve
    return out


@router.get("/vendors", summary="Vendors")
def vendors(s: Session = Depends(db)):
    return [{"id": v.id, "name": v.name, "currency": v.currency, "tax_rate_bp": v.tax_rate_bp, "requires_po": v.requires_po, "bank_account": v.bank_account, "terms_days": v.terms_days} for v in s.scalars(select(Vendor).order_by(Vendor.name))]


@router.get("/customers", summary="Customers")
def customers(s: Session = Depends(db)):
    return [customer_row(c) for c in s.scalars(select(Customer).order_by(Customer.name))]


@router.get("/invoices", summary="Sales invoices")
def invoices(status: str | None = None, customer_id: int | None = None, bucket: str | None = None, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    from booklantern.aging import bucket_for, days_late
    q = select(Invoice).order_by(Invoice.due_date)
    if status:
        q = q.where(Invoice.status == status)
    if customer_id:
        q = q.where(Invoice.customer_id == customer_id)
    today, book = ctx.today(s), ctx.rates(s)
    out = []
    for i in s.scalars(q):
        row = invoice_row(i, fxservice.describe(book, i.total_minor - i.paid_minor, i.currency, today))
        row["days_late"] = days_late(i.due_date, today) if i.status == "open" else 0
        row["bucket"] = bucket_for(row["days_late"]) if i.status == "open" else ""
        if bucket and row["bucket"] != bucket:
            continue
        out.append(row)
    return out


@router.get("/aging", summary="Receivables aging by bucket and customer")
def aging(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    return collections.aging_report(s, ctx.today(s), ctx.rates(s))


@router.get("/collections", summary="Reminders, promises and what the ladder would do for each open invoice right now")
def collections_view(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    from booklantern.aging import bucket_for, days_late

    eff, now = ctx.effective(s), ctx.now(s)
    today, book = ctx.today(s), ctx.rates(s)
    plan = []
    for i in s.scalars(select(Invoice).where(Invoice.status == "open").order_by(Invoice.due_date)):
        d = R.decide(collections.state_for(s, i), now, collections.cfg(eff), eff.mode.value, eff.kill_switch)
        sent = [{"step": r.step, "tone": r.tone, "at": iso(r.sent_at)} for r in s.scalars(select(Reminder).where(Reminder.invoice_id == i.id, Reminder.status == "sent").order_by(Reminder.step))]
        late = days_late(i.due_date, today)
        plan.append({**invoice_row(i, fxservice.describe(book, i.total_minor - i.paid_minor, i.currency, today)), "days_late": late, "bucket": bucket_for(late), "decision": d.action, "reason": d.reason, "next_step": d.step, "next_tone": d.tone, "sent": sent})
    return {"plan": plan, "reminders": [reminder_row(r) for r in s.scalars(select(Reminder).where(Reminder.status.in_(("drafted", "approved", "cancelled"))).order_by(Reminder.id.desc()).limit(100))],
            "promises": [{"id": p.id, "invoice": p.invoice.number, "invoice_id": p.invoice_id, "customer": p.invoice.customer.name, "promised_on": iso(p.promised_on), "amount_minor": p.amount_minor, "currency": p.invoice.currency, "status": p.status, "note": p.note} for p in s.scalars(select(PromiseToPay).order_by(PromiseToPay.promised_on))],
            "ladder": [{"step": a, "days_after_due": b, "tone": c} for a, b, c in R.LADDER]}


@router.get("/bank/transactions", summary="Bank lines")
def bank_transactions(status: str | None = None, limit: int = Query(300, ge=1, le=6000), offset: int = Query(0, ge=0), s: Session = Depends(db)):
    q = select(BankTransaction).order_by(BankTransaction.posted_on.desc(), BankTransaction.id.desc())
    if status:
        q = q.where(BankTransaction.status.in_(status.split(",")))
    rows = list(s.scalars(q.limit(limit).offset(offset)))
    ms: dict[int, list[Match]] = {}
    for m in s.scalars(select(Match).where(Match.bank_txn_id.in_([t.id for t in rows]))):
        ms.setdefault(m.bank_txn_id, []).append(m)
    inv = {i.id: i.number for i in s.scalars(select(Invoice))}
    bl = {b.id: b.number for b in s.scalars(select(Bill))}
    return {"total": s.query(BankTransaction).count(), "balance_minor": bankservice.balance(s), "rows": [
        {"id": t.id, "ref": t.ref, "posted_on": iso(t.posted_on), "description": t.description, "amount_minor": t.amount_minor, "currency": t.currency, "status": t.status,
         "matches": [{"id": m.id, "type": m.target_type, "number": inv.get(m.invoice_id) or bl.get(m.bill_id) or "repeating item", "allocated_minor": m.allocated_minor, "score": m.score, "status": m.status, "reason": m.reason} for m in ms.get(t.id, [])]} for t in rows]}


@router.get("/bank/candidates", summary="Open invoices and bills a person could link a bank line to")
def candidates(txn_id: int, s: Session = Depends(db)):
    t = s.get(BankTransaction, txn_id)
    if t is None:
        raise HTTPException(404, "No such bank line.")
    inv_used: dict[int, int] = {}
    bill_used: dict[int, int] = {}
    for m in s.scalars(select(Match)):
        if m.invoice_id:
            inv_used[m.invoice_id] = inv_used.get(m.invoice_id, 0) + m.allocated_minor
        if m.bill_id:
            bill_used[m.bill_id] = bill_used.get(m.bill_id, 0) + m.allocated_minor
    out: list[dict] = []
    if t.amount_minor > 0:
        for i in s.scalars(select(Invoice).where(Invoice.status == "open").order_by(Invoice.due_date)):
            left = i.total_minor - max(i.paid_minor, inv_used.get(i.id, 0))
            if left > 0:
                out.append({"kind": "invoice", "id": i.id, "number": i.number, "party": i.customer.name, "open_minor": left, "due_date": iso(i.due_date)})
        return out
    vend = {v.id: v.name for v in s.scalars(select(Vendor))}
    for b in s.scalars(select(Bill).where(Bill.status.in_(("approved", "posted_draft", "needs_review")))):
        left = b.total_minor - max(b.paid_minor, bill_used.get(b.id, 0))
        if left > 0:
            out.append({"kind": "bill", "id": b.id, "number": b.number, "party": vend.get(b.vendor_id, b.vendor_name_read), "open_minor": left, "due_date": iso(b.due_date)})
    return out


@router.get("/exceptions", summary="Exceptions that need a person")
def exceptions(status: str = "open", s: Session = Depends(db)):
    return [{"id": e.id, "kind": e.kind, "severity": e.severity, "ref_type": e.ref_type, "ref_id": e.ref_id, "detail": e.detail, "status": e.status, "created_at": iso(e.created_at)}
            for e in s.scalars(select(ExceptionItem).where(ExceptionItem.status == status).order_by(ExceptionItem.severity.desc(), ExceptionItem.id.desc()).limit(500))]


@router.get("/reports/summary", summary="Month end numbers")
def report_summary(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    return report_pdf.summary(s, ctx)


@router.get("/reports/month-end.pdf", summary="The month end pack as a PDF")
def report_pdf_route(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    return Response(report_pdf.build(s, ctx), media_type="application/pdf", headers={"content-disposition": 'attachment; filename="month-end-pack.pdf"'})
