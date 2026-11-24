"""Routes that change things. Each one needs the owner or an approver, and writes an audit entry."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import bankservice, collections, intake, posting
from booklantern.api.deps import db, get_ctx, writer
from booklantern.context import Ctx
from booklantern.exceptions import resolve
from booklantern.models import ExceptionItem, BankTransaction, Bill, BillLine, Customer, Document, Invoice, Match, Reminder
from sendora_core.audit import record_audit

router = APIRouter(prefix="/api", tags=["write"])


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(409, str(exc))


def _found(obj, what: str):
    """A page left open after a demo reset may ask for a row that is gone. That is a 404, never a crash."""
    if obj is None:
        raise HTTPException(404, f"No such {what}.")
    return obj


@router.post("/documents/upload", summary="Upload a PDF or image as the raw request body. Send the file name in the x-filename header.")
async def upload(request: Request, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    data = await request.body()
    if not data or len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "The file is empty or larger than 15 MB.")
    try:
        doc = intake.ingest(s, ctx, request.headers.get("x-filename", "upload.pdf"), data, "upload")
    except intake.UnsupportedFile as exc:
        raise HTTPException(415, str(exc)) from exc
    if doc is None:
        return {"duplicate": True}
    bill = intake.process_document(s, ctx, doc, data)
    record_audit(s, u["user"], "document.uploaded", f"document:{doc.id}", {})
    return {"duplicate": False, "document_id": doc.id, "bill_id": bill.id}


class LineIn(BaseModel):
    description: str = Field(max_length=240)
    quantity_milli: int = Field(ge=0, le=10**9)
    unit_minor: int
    total_minor: int


class BillPatch(BaseModel):
    vendor: str | None = Field(default=None, max_length=200)
    number: str | None = Field(default=None, max_length=80)
    issue_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    po_number: str | None = Field(default=None, max_length=60)
    bill_to: str | None = Field(default=None, max_length=200)
    bank_account: str | None = Field(default=None, max_length=80)
    vendor_id: int | None = None
    subtotal_minor: int | None = Field(default=None, ge=0, le=10**12)
    tax_minor: int | None = Field(default=None, ge=0, le=10**12)
    total_minor: int | None = Field(default=None, ge=0, le=10**12)
    lines: list[LineIn] | None = None


@router.patch("/bills/{bill_id}", summary="Correct fields on a bill. The checks run again.")
def patch_bill(bill_id: int, body: BillPatch, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    b = _found(s.get(Bill, bill_id), "bill")
    if b.status not in ("needs_review", "inbox"):
        raise HTTPException(409, "Only a bill that is waiting for review can be edited.")
    changed = body.model_dump(exclude_unset=True)
    lines = changed.pop("lines", None)
    for k in ("vendor", "number", "currency", "po_number", "bill_to", "bank_account", "subtotal_minor", "tax_minor", "total_minor"):
        if k in changed and changed[k] is None:
            raise HTTPException(422, f"{k.replace('_minor', '').replace('_', ' ').capitalize()} cannot be empty. Leave the field as it was, or type a value.")
    if "currency" in changed:
        changed["currency"] = changed["currency"].upper()
    issue, due = changed.get("issue_date", b.issue_date), changed.get("due_date", b.due_date)
    if issue and due and due < issue:
        raise HTTPException(422, "The due date is before the bill date. Check both dates.")
    name = changed.pop("vendor", None)
    if name is not None:
        _set_vendor(s, b, name.strip())
    for k, v in changed.items():
        setattr(b, k, v)
    if lines is not None:
        b.lines.clear()
        for i, ln in enumerate(lines):
            b.lines.append(BillLine(position=i, **ln))
    b.edited_by = u["user"]
    s.flush()
    doc = s.get(Document, b.document_id) if b.document_id else None
    rate_f = (doc.extraction or {}).get("fields", {}).get("tax_rate_bp") if doc else None
    found = intake.validate_bill(s, ctx, b, rate_f["value"] if rate_f and "tax_minor" not in changed and "subtotal_minor" not in changed else None)
    record_audit(s, u["user"], "bill.edited", f"bill:{b.id}", {"fields": sorted(changed) + (["vendor"] if name is not None else []) + (["lines"] if lines is not None else [])})
    return {"ok": True, "findings": [f.kind for f in found]}


def _set_vendor(s: Session, b: Bill, name: str) -> None:
    """A vendor typed by hand: the vendor list is searched for a close match (same rule as when a bill is read); otherwise the name is kept as read and the bill is flagged as an unknown vendor."""
    from booklantern import validation as V
    from booklantern.models import Vendor
    vm = V.match_vendor(name, [intake._vendor_data(v) for v in s.scalars(select(Vendor))]) if name else None
    b.vendor_id, b.vendor_name_read = (vm.id if vm else None), (vm.name if vm else name)


class ApproveIn(BaseModel):
    note: str = Field(default="", max_length=300)


@router.post("/bills/{bill_id}/approve", summary="Approve a bill. A blocking finding needs a written reason.")
def approve_bill(bill_id: int, body: ApproveIn, s: Session = Depends(db), u: dict = Depends(writer)):
    try:
        b = posting.approve(s, bill_id, u["user"], body.note)
    except posting.NoSuchBill as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"status": b.status}


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


@router.post("/bills/{bill_id}/reject", summary="Reject a bill")
def reject_bill(bill_id: int, body: RejectIn, s: Session = Depends(db), u: dict = Depends(writer)):
    try:
        return {"status": posting.reject(s, bill_id, u["user"], body.reason).status}
    except posting.NoSuchBill as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/bills/{bill_id}/post", summary="Post an approved bill to the accounting system as a draft. Does nothing in draft mode or with ACCOUNTING_WRITE off.")
def post_bill(bill_id: int, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    try:
        return posting.post_draft(s, ctx, bill_id, u["user"])
    except posting.NoSuchBill as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/reminders/{reminder_id}/approve", summary="Approve a drafted reminder")
def approve_reminder(reminder_id: int, s: Session = Depends(db), u: dict = Depends(writer)):
    try:
        r = collections.approve_reminder(s, reminder_id, u["user"])
        collections.close_approval(s, reminder_id, True, u["user"], u["role"])
        return {"status": r.status}
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/reminders/{reminder_id}/cancel", summary="Cancel a reminder that has not been sent")
def cancel_reminder(reminder_id: int, s: Session = Depends(db), u: dict = Depends(writer)):
    r = s.get(Reminder, reminder_id)
    if r is None or r.status not in ("drafted", "approved"):
        raise HTTPException(409, "This reminder cannot be cancelled.")
    r.status, r.cancel_reason = "cancelled", "cancelled by a person"
    record_audit(s, u["user"], "reminder.cancelled", f"reminder:{r.id}", {})
    collections.close_approval(s, reminder_id, False, u["user"], u["role"])
    return {"status": r.status}


class PromiseIn(BaseModel):
    promised_on: date
    amount_minor: int = Field(gt=0, le=10**12)
    note: str = Field(default="", max_length=240)


@router.post("/invoices/{invoice_id}/promise", summary="Record a promise to pay")
def promise(invoice_id: int, body: PromiseIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    inv = _found(s.get(Invoice, invoice_id), "invoice")
    if inv.status != "open":
        raise HTTPException(409, "This invoice is already paid, so there is nothing to promise.")
    if body.promised_on < ctx.today(s):
        raise HTTPException(422, "The promised date is in the past. Pick today or a later day.")
    if body.amount_minor > inv.total_minor - inv.paid_minor:
        raise HTTPException(422, "The promised amount is more than the invoice still owes.")
    p = collections.record_promise(s, invoice_id, body.promised_on, body.amount_minor, body.note, u["user"])
    return {"id": p.id}


class DisputeIn(BaseModel):
    disputed: bool
    note: str = Field(default="", max_length=240)


@router.post("/invoices/{invoice_id}/dispute", summary="Mark or clear a dispute. A dispute stops reminders.")
def dispute(invoice_id: int, body: DisputeIn, s: Session = Depends(db), u: dict = Depends(writer)):
    _found(s.get(Invoice, invoice_id), "invoice")
    return {"disputed": collections.set_dispute(s, invoice_id, body.disputed, body.note, u["user"]).disputed}


class OptOutIn(BaseModel):
    opted_out: bool


@router.post("/customers/{customer_id}/opt-out", summary="Record that a customer asked to get no reminders")
def opt_out(customer_id: int, body: OptOutIn, s: Session = Depends(db), u: dict = Depends(writer)):
    _found(s.get(Customer, customer_id), "customer")
    return {"opted_out": collections.set_opt_out(s, customer_id, body.opted_out, u["user"]).opted_out}


@router.post("/invoices/{invoice_id}/payment-link", summary="Make a payment link for an invoice. In draft mode this makes a placeholder and nothing at the payment provider.")
def payment_link(invoice_id: int, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    inv = _found(s.get(Invoice, invoice_id), "invoice")
    if inv.status != "open":
        raise HTTPException(409, "This invoice is already paid, so it needs no payment link.")
    return collections.create_payment_link(s, ctx, invoice_id, u["user"])


class ImportIn(BaseModel):
    text: str = Field(min_length=1, max_length=8_000_000)
    name: str = Field(default="upload.csv", max_length=80)


@router.post("/bank/import", summary="Import a bank statement CSV (text in the body). CSV only, no bank login.")
def bank_import(body: ImportIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    from booklantern.bankcsv import CsvError
    try:
        r = bankservice.import_csv(s, body.text, body.name)
    except CsvError as exc:
        raise HTTPException(422, str(exc)) from exc
    r["matching"] = bankservice.run_matching(s, ctx)
    bankservice.record_payments(s)
    record_audit(s, u["user"], "bank.imported", None, r["matching"] | {"added": r["added"]})
    return r


@router.post("/bank/match/run", summary="Run the matcher on lines that are not matched yet")
def match_run(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    r = bankservice.run_matching(s, ctx)
    bankservice.record_payments(s)
    return r


class LinkIn(BaseModel):
    txn_id: int
    kind: str = Field(pattern="^(invoice|bill)$")
    target_id: int
    amount_minor: int = Field(gt=0, le=10**12)


@router.post("/bank/links", summary="Link a bank line to an invoice or bill by hand")
def link(body: LinkIn, s: Session = Depends(db), u: dict = Depends(writer)):
    t = _found(s.get(BankTransaction, body.txn_id), "bank line")
    _found(s.get(Invoice if body.kind == "invoice" else Bill, body.target_id), body.kind)
    if (t.amount_minor > 0) != (body.kind == "invoice"):
        raise HTTPException(409, "Money that came in belongs to an invoice, and money that went out belongs to a bill.")
    try:
        m = bankservice.link_manually(s, body.txn_id, body.kind, body.target_id, body.amount_minor, u["user"])
    except ValueError as exc:
        raise _bad(exc) from exc
    bankservice.record_payments(s)
    return {"match_id": m.id}


@router.post("/bank/matches/{match_id}/confirm", summary="Confirm a suggested match")
def confirm(match_id: int, s: Session = Depends(db), u: dict = Depends(writer)):
    _found(s.get(Match, match_id), "match")
    bankservice.confirm_match(s, match_id, u["user"])
    bankservice.record_payments(s)
    return {"ok": True}


@router.delete("/bank/matches/{match_id}", summary="Remove a match")
def unlink(match_id: int, s: Session = Depends(db), u: dict = Depends(writer)):
    _found(s.get(Match, match_id), "match")
    bankservice.unlink(s, match_id, u["user"])
    return {"ok": True}


class ResolveIn(BaseModel):
    note: str = Field(default="", max_length=300)


@router.post("/exceptions/{exc_id}/resolve", summary="Mark an exception as dealt with. A blocking one needs a written reason.")
def resolve_exception(exc_id: int, body: ResolveIn | None = None, s: Session = Depends(db), u: dict = Depends(writer)):
    note = (body.note if body else "").strip()
    row = _found(s.get(ExceptionItem, exc_id), "exception")
    if row.severity == "block" and not note:
        raise HTTPException(409, "This finding blocks approval. Write down why it is safe to close it.")
    try:
        e = resolve(s, exc_id, u["user"])
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    record_audit(s, u["user"], "exception.resolved", f"exception:{e.id}", {"kind": e.kind, "note": note[:200]})
    return {"status": e.status}
