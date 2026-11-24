"""Document intake: store the file once, read it, make a bill for review, and run the checks."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import fxservice, validation as V
from booklantern.exceptions import clear_open, raise_exception
from booklantern.extraction import offline
from booklantern.extraction.cells import page_count
from booklantern.extraction.schema import Extraction
from booklantern.models import Bill, BillLine, Document, ExceptionItem, Vendor
from sendora_core.audit import record_audit
from sendora_core.events import record_event

VALIDATION_KINDS = {"line_sum_mismatch", "wrong_total", "wrong_tax", "duplicate_exact", "duplicate_near", "amount_far_above_history", "unknown_vendor", "bank_detail_changed", "missing_po", "currency_mismatch",
                    "future_date", "wrong_company", "unreadable_document", "low_confidence", "tax_rate_differs"}


LOW_CONFIDENCE = 50  # a field read with less confidence than this is listed for a person


class UnsupportedFile(ValueError):
    pass


def ingest(session: Session, ctx, name: str, data: bytes, source: str = "upload", from_addr: str = "", subject: str = "", ref: str | None = None) -> Document | None:
    """Store a file. The same bytes twice give nothing new (returns None)."""
    if not data[:4] == b"%PDF" and not data[:8] == b"\x89PNG\r\n\x1a\n" and not data[:3] == b"\xff\xd8\xff":
        raise UnsupportedFile("Only PDF, PNG and JPEG files are accepted.")
    sha = hashlib.sha256(data).hexdigest()
    if session.scalars(select(Document).where(Document.sha256 == sha)).first():
        return None
    folder = Path(ctx.settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha[:16]}{'.pdf' if data[:4] == b'%PDF' else '.png' if data[:2] == b'\x89P' else '.jpg'}"
    path.write_bytes(data)
    n = session.query(Document).count() + 1
    doc = Document(ref=ref or f"DOC-{n:04d}", file_name=Path(name).name[:200], sha256=sha, mime="application/pdf" if data[:4] == b"%PDF" else "image/png" if data[:2] == b"\x89P" else "image/jpeg",
                   source=source, from_addr=from_addr, subject=subject, stored_path=str(path), received_at=ctx.now(session))
    session.add(doc)
    session.flush()
    record_event(session, "document.received", "document", doc.id, {"source": source})
    return doc


def _extract(session: Session, ctx, doc: Document, data: bytes) -> Extraction:
    if doc.mime != "application/pdf":
        return Extraction("none", False, notes=["This is a picture, not a PDF. The offline stand in cannot read pictures."])
    try:
        if ctx.settings.extractor == "live":  # the model path, UNVERIFIED live: see extraction/live.py
            from booklantern.extraction.live import extract_live
            return extract_live(ctx, session, data)
        return offline.extract(data)
    except Exception:  # a damaged or hostile file must never stop the queue
        return Extraction("none", False, notes=["The file could not be opened as a PDF. It may be damaged. Key the fields by hand."])


def _vendor_data(v: Vendor) -> V.VendorData:
    return V.VendorData(v.id, v.name, v.currency, v.tax_rate_bp, v.requires_po, v.bank_account)


def bill_data(b: Bill, rate_bp: int | None = None) -> V.BillData:
    return V.BillData(b.id, b.vendor_id, b.number, b.issue_date, b.currency, b.po_number, b.bill_to, b.bank_account, b.subtotal_minor, b.tax_minor, b.total_minor, [x.total_minor for x in b.lines], rate_bp)


def validate_bill(session: Session, ctx, bill: Bill, rate_bp: int | None = None) -> list[V.Finding]:
    vendors = [_vendor_data(v) for v in session.scalars(select(Vendor))]
    vendor = next((v for v in vendors if v.id == bill.vendor_id), None)
    earlier = [bill_data(o) for o in session.scalars(select(Bill).where(Bill.id != bill.id, Bill.status != "rejected").order_by(Bill.id))]  # either order: the copy may be read before the original
    hist = [o.total_minor for o in session.scalars(select(Bill).where(Bill.vendor_id == bill.vendor_id, Bill.status == "paid", Bill.currency == bill.currency))] if bill.vendor_id else []
    found = V.validate(bill_data(bill, rate_bp), vendor, earlier, hist, ctx.settings.company_name, ctx.today(session))
    clear_open(session, "bill", bill.id, VALIDATION_KINDS)
    for f in found:
        raise_exception(session, f.kind, f.severity, "bill", bill.id, f.detail)
    return found


DEFAULT_TERMS_DAYS = 30  # net 30, a decided default


def vm_terms(session: Session, vm) -> int:
    """Payment terms in days for a bill with no due date: the vendor's own terms, otherwise net 30."""
    v = session.get(Vendor, vm.id) if vm else None
    return v.terms_days if v and v.terms_days else DEFAULT_TERMS_DAYS


def process_document(session: Session, ctx, doc: Document, data: bytes | None = None) -> Bill:
    data = data if data is not None else Path(doc.stored_path).read_bytes()
    ex = _extract(session, ctx, doc, data)
    doc.extraction, doc.extractor = ex.to_json(), ex.extractor
    doc.has_text_layer = ex.readable
    doc.page_count = page_count(data) if doc.mime == "application/pdf" else 1
    doc.status = "extracted" if ex.readable else "unreadable"
    vendors = [_vendor_data(v) for v in session.scalars(select(Vendor))]
    name = str(ex.value("vendor") or "")
    vm = V.match_vendor(name, vendors) if name else None
    d = lambda k: date.fromisoformat(ex.value(k)) if ex.value(k) else None  # noqa: E731
    bill = Bill(vendor_id=vm.id if vm else None, document_id=doc.id, vendor_name_read=name, number=str(ex.value("number") or ""), issue_date=d("issue_date"), due_date=d("due_date"), currency=str(ex.value("currency") or ctx.settings.base_currency),
                po_number=str(ex.value("po") or ""), bill_to=str(ex.value("bill_to") or ""), bank_account=str(ex.value("bank_account") or ""), subtotal_minor=int(ex.value("subtotal_minor") or 0), tax_minor=int(ex.value("tax_minor") or 0),
                total_minor=int(ex.value("total_minor") or 0), status="needs_review", created_at=ctx.now(session))
    for i, ln in enumerate(ex.lines):
        bill.lines.append(BillLine(position=i, description=ln.description, quantity_milli=ln.quantity_milli, unit_minor=ln.unit_minor, total_minor=ln.total_minor))
    assumed = ""
    if bill.due_date is None and bill.issue_date is not None:
        days = vm_terms(session, vm)
        bill.due_date = bill.issue_date + timedelta(days=days)
        assumed = f"The bill shows no due date. Assumed the bill date plus {days} days (net {days}). Change the due date if the bill says otherwise."
    session.add(bill)
    session.flush()
    if assumed:
        raise_exception(session, "due_date_assumed", "info", "bill", bill.id, assumed)
    if ex.flags:
        raise_exception(session, "suspicious_text", "block", "bill", bill.id, "This document contains text that tries to give orders (" + "; ".join(ex.flags)[:200] + "). It was read as data and nothing it says was done. Check the bill with the vendor before approving.")
    if ex.value("doc_type") == "credit_note":
        raise_exception(session, "credit_note", "warning", "bill", bill.id, "This looks like a credit note, not a bill to pay. A person decides how to apply it. Do not pay it.")
    if not ex.readable:
        raise_exception(session, "unreadable_document", "info", "bill", bill.id, ex.notes[0] if ex.notes else "Could not read this document.")
    else:
        validate_bill(session, ctx, bill, ex.value("tax_rate_bp"))
        low = [k for k, f in ex.fields.items() if f.confidence < LOW_CONFIDENCE]
        if low:
            raise_exception(session, "low_confidence", "info", "bill", bill.id, f"Low confidence: {', '.join(low)}.")
    doc.status = "linked" if ex.readable else "unreadable"
    record_audit(session, "system", "bill.created", f"bill:{bill.id}", {"document": doc.ref})
    return bill


def run_intake(session: Session, ctx) -> dict:
    """Fetch new mail attachments, then read every document that has no bill yet, in the order received (so originals come before their copies)."""
    fetched = 0
    for d in ctx.adapters.inbox.fetch_documents():
        try:
            if ingest(session, ctx, d.file_name, d.data, "inbox", d.from_addr, d.subject, ref=d.external_id[:20] if len(d.external_id) <= 20 and d.external_id.startswith("D") else None):
                fetched += 1
        except UnsupportedFile:
            continue
    done = 0
    for doc in session.scalars(select(Document).where(Document.status == "new").order_by(Document.id)):
        process_document(session, ctx, doc)
        done += 1
    fxservice.flag_missing(session, ctx)
    return {"fetched": fetched, "processed": done}


def open_exceptions(session: Session) -> int:
    return session.query(ExceptionItem).filter(ExceptionItem.status == "open").count()
