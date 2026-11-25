"""Document intake: store the file once, read it, make a bill for review, and run the checks."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from booklantern import fxservice, limits, validation as V
from booklantern.exceptions import clear_open, raise_exception
from booklantern.extraction import offline
from booklantern.extraction.cells import page_count
from booklantern.extraction.schema import Extraction
from booklantern.models import Bill, BillLine, Customer, Document, ExceptionItem, Vendor
from sendora_core.audit import record_audit
from sendora_core.events import record_event

log = logging.getLogger("booklantern.intake")

VALIDATION_KINDS = {"line_sum_mismatch", "wrong_total", "wrong_tax", "duplicate_exact", "duplicate_near", "amount_far_above_history", "unknown_vendor", "bank_detail_changed", "bank_details_not_read", "missing_po", "currency_mismatch",
                    "future_date", "wrong_company", "unreadable_document", "low_confidence", "tax_rate_differs"}


STOP_WORDS = re.compile(r"\b(stop|unsubscribe|opt[- ]?out|remove me|no more (?:emails?|reminders?|messages?)|do not (?:contact|email|write)|don'?t (?:contact|email|write))\b", re.I)
MAX_READ_ATTEMPTS = 3  # a document whose reading was started this many times and never finished (the reader was killed, for example by memory) is given up on and goes to a person
LOW_CONFIDENCE = 50  # a field read with less confidence than this is listed for a person


class UnsupportedFile(ValueError):
    pass


def ingest(session: Session, ctx, name: str, data: bytes, source: str = "upload", from_addr: str = "", subject: str = "", ref: str | None = None) -> Document | None:
    """Store a file. The same bytes twice give nothing new (returns None). The stored name is the full SHA 256, so two files never share a name; the reference
    is a number the system counts (never text a sender wrote), unless a fixed one is passed by the offline demo."""
    if not data[:4] == b"%PDF" and not data[:8] == b"\x89PNG\r\n\x1a\n" and not data[:3] == b"\xff\xd8\xff":
        raise UnsupportedFile("Only PDF, PNG and JPEG files are accepted.")
    sha = hashlib.sha256(data).hexdigest()
    if session.scalars(select(Document).where(Document.sha256 == sha)).first():
        return None
    folder = Path(ctx.settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}{'.pdf' if data[:4] == b'%PDF' else '.png' if data[:2] == b'\x89P' else '.jpg'}"
    if not path.exists():
        path.write_bytes(data)  # the name is the content's own hash, so an existing file is these same bytes
    mime = "application/pdf" if data[:4] == b"%PDF" else "image/png" if data[:2] == b"\x89P" else "image/jpeg"
    nxt = (session.scalar(select(func.max(Document.id))) or 0) + 1
    for attempt in range(20):  # two uploads at the same moment may pick the same number: the loser takes the next one
        doc = Document(ref=ref or f"DOC-{nxt + attempt:04d}", file_name=limits.text(Path(name).name, 200), sha256=sha, mime=mime, source=source, from_addr=limits.text(from_addr, 200),
                       subject=limits.text(subject, 240), stored_path=str(path), received_at=ctx.now(session))
        try:
            with session.begin_nested():
                session.add(doc)
                session.flush()
            break
        except IntegrityError:
            if ref or attempt == 19:
                raise
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
    return V.BillData(b.id, b.vendor_id, b.number, b.issue_date, b.currency, b.po_number, b.bill_to, b.bank_account, b.subtotal_minor, b.tax_minor, b.total_minor, [x.total_minor for x in b.lines], rate_bp, b.vendor_name_read or "")


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


def revalidate_vendor_bills(session: Session, ctx, vendor_id: int, who: str) -> list[int]:
    """The vendor's record changed (its account on file, its purchase order rule or its usual tax rate), so every bill of that vendor that is still in review or approved is checked
    again against the new record. An approved bill that now has a blocking finding goes back to review: it was approved against facts that are no longer the facts.
    Returns the ids of the bills that went back."""
    sent_back: list[int] = []
    for b in list(session.scalars(select(Bill).where(Bill.vendor_id == vendor_id, Bill.status.in_(("needs_review", "inbox", "approved"))).order_by(Bill.id))):
        doc = session.get(Document, b.document_id) if b.document_id else None
        rate = ((doc.extraction or {}).get("fields", {}).get("tax_rate_bp") or {}).get("value") if doc else None
        found = validate_bill(session, ctx, b, rate)
        if b.status == "approved" and any(f.severity == "block" for f in found):
            moved = session.execute(update(Bill).where(Bill.id == b.id, Bill.status == "approved").values(status="needs_review").execution_options(synchronize_session=False))
            session.expire(b)
            if moved.rowcount == 1:
                sent_back.append(b.id)
                record_audit(session, who, "bill.sent_back_for_review", f"bill:{b.id}", {"why": "the vendor's record changed", "findings": [f.kind for f in found if f.severity == "block"]})
    return sent_back


DEFAULT_TERMS_DAYS = 30  # net 30, a decided default


def vm_terms(session: Session, vm) -> int:
    """Payment terms in days for a bill with no due date: the vendor's own terms, otherwise net 30."""
    v = session.get(Vendor, vm.id) if vm else None
    return v.terms_days if v and v.terms_days else DEFAULT_TERMS_DAYS


def _amount(ex: Extraction, key: str, out_of_range: list[str]) -> int:
    """An amount read from the document, as a whole number of minor units. A value beyond any real bill (or not a number) is left out and noted for a person."""
    try:
        n = int(ex.value(key) or 0)
    except (TypeError, ValueError):
        n = 0
    if not limits.in_range(n):
        out_of_range.append(key)
        return 0
    return n


def _date(ex: Extraction, key: str) -> date | None:
    try:
        return date.fromisoformat(str(ex.value(key))) if ex.value(key) else None
    except ValueError:
        return None  # a model can return anything: a date that is not a date is not a date


def process_document(session: Session, ctx, doc: Document, data: bytes | None = None) -> Bill:
    data = data if data is not None else Path(doc.stored_path).read_bytes()
    ex = _extract(session, ctx, doc, data)
    doc.extraction, doc.extractor = ex.to_json(), limits.text(ex.extractor, 60)
    doc.has_text_layer = ex.readable
    doc.page_count = page_count(data) if doc.mime == "application/pdf" else 1
    doc.status = "extracted" if ex.readable else "unreadable"
    vendors = [_vendor_data(v) for v in session.scalars(select(Vendor))]
    name = limits.text(ex.value("vendor"), 200)
    vm = V.match_vendor(name, vendors) if name else None
    too_big: list[str] = []
    bill = Bill(vendor_id=vm.id if vm else None, document_id=doc.id, vendor_name_read=name, number=limits.text(ex.value("number"), 80), issue_date=_date(ex, "issue_date"), due_date=_date(ex, "due_date"),
                currency=limits.currency(ex.value("currency"), ctx.settings.base_currency), po_number=limits.text(ex.value("po"), 60), bill_to=limits.text(ex.value("bill_to"), 200),
                bank_account=limits.text(ex.value("bank_account"), 80), subtotal_minor=_amount(ex, "subtotal_minor", too_big), tax_minor=_amount(ex, "tax_minor", too_big),
                total_minor=_amount(ex, "total_minor", too_big), status="needs_review", created_at=ctx.now(session))
    for i, ln in enumerate(ex.lines[: limits.MAX_LINES]):
        qty, unit, tot = ln.quantity_milli, ln.unit_minor, ln.total_minor
        if not (limits.in_range(unit) and limits.in_range(tot) and 0 <= qty <= limits.MAX_QUANTITY_MILLI):
            too_big.append("a line")
            qty, unit, tot = 1000, 0, 0
        bill.lines.append(BillLine(position=i, description=limits.text(ln.description, 240), quantity_milli=qty, unit_minor=unit, total_minor=tot))
    assumed = ""
    if bill.due_date is None and bill.issue_date is not None:
        days = vm_terms(session, vm)
        bill.due_date = bill.issue_date + timedelta(days=days)
        assumed = f"The bill shows no due date. Assumed the bill date plus {days} days (net {days}). Change the due date if the bill says otherwise."
    session.add(bill)
    session.flush()
    if assumed:
        raise_exception(session, "due_date_assumed", "info", "bill", bill.id, assumed)
    if doc.source == "inbox" and not ctx.settings.sender_allowed(doc.from_addr):
        raise_exception(session, "sender_not_allowed", "block", "bill", bill.id, f"This bill came by email from {limits.text(doc.from_addr, 120) or 'an unknown sender'}, which is not on INTAKE_ALLOWED_SENDERS. Check with the vendor that they sent it, then approve with a reason.")
    if ex.flags:
        raise_exception(session, "suspicious_text", "block", "bill", bill.id, "This document contains text that tries to give orders (" + "; ".join(ex.flags)[:200] + "). It was read as data and nothing it says was done. Check the bill with the vendor before approving.")
    if ex.value("negative_amount"):
        raise_exception(session, "negative_amount", "block", "bill", bill.id, "An amount on this document is negative (a credit or a reversal). It is not a bill to pay. A person decides how to apply it, and it must not be paid as it stands.")
    if too_big:
        raise_exception(session, "implausible_amount", "block", "bill", bill.id, f"A printed amount ({', '.join(sorted(set(too_big)))}) is far larger than any real bill, so it was not read. Key the amounts by hand from the page.")
    if ex.value("doc_type") == "credit_note":
        raise_exception(session, "credit_note", "warning", "bill", bill.id, "This looks like a credit note, not a bill to pay. A person decides how to apply it. Do not pay it.")
    if not ex.readable:
        raise_exception(session, "unreadable_document", "info", "bill", bill.id, ex.notes[0] if ex.notes else "Could not read this document.")
    else:
        validate_bill(session, ctx, bill, ex.value("tax_rate_bp"))
        low = [k for k, f in ex.fields.items() if f.confidence < LOW_CONFIDENCE]
        if low:
            # A model's own answer about who is paid, to which account and how much is blocking when it is unsure: a person confirms it against the page first.
            key_fields = ctx.settings.extractor == "live" and any(k in low for k in ("vendor", "bank_account", "total_minor"))
            raise_exception(session, "low_confidence", "block" if key_fields else "info", "bill", bill.id, f"Low confidence: {', '.join(low)}.")
    doc.status = "linked" if ex.readable else "unreadable"
    record_audit(session, "system", "bill.created", f"bill:{bill.id}", {"document": doc.ref})
    return bill


def _store_unreadable(session: Session, ctx, d) -> bool:
    """A document that could not be turned into a bill is still kept, as an unreadable document with an exception for a person. True when it was stored."""
    try:
        doc = ingest(session, ctx, d.file_name, d.data, "inbox", d.from_addr, d.subject)
        if doc is not None:
            doc.status, doc.has_text_layer = "unreadable", False
            raise_exception(session, "unreadable_document", "warning", "document", doc.id, "This file could not be turned into a bill (it may be damaged or hold values no real bill holds). Open the file and key the bill by hand.")
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False


def run_intake(session: Session, ctx) -> dict:
    """Fetch new mail attachments, then read every document that has no bill yet, in the order received (so originals come before their copies).

    Every document is its own unit: it is committed before the next one starts, and one that fails is rolled back alone, stored as an unreadable document and
    logged without its text. The mailbox is told a message is read only after everything from it is safely stored, so one hostile attachment can never
    take the other bills of the same poll with it.
    """
    session.commit()  # start clean: whatever the caller had pending is saved, so a rollback below can only undo one document
    fetched = failed = 0
    kept_back: set[str] = set()  # messages that must be looked at again (their document could not even be stored)
    acks: set[str] = set()
    for d in ctx.adapters.inbox.fetch_documents():
        try:
            if ingest(session, ctx, d.file_name, d.data, "inbox", d.from_addr, d.subject, ref=d.ref or None):
                fetched += 1
            session.commit()
        except UnsupportedFile:
            session.rollback()
        except Exception as exc:
            session.rollback()
            failed += 1
            log.warning("a document from the mailbox could not be stored (%s, id %s)", type(exc).__name__, hashlib.sha256(d.external_id.encode()).hexdigest()[:10])
            if not _store_unreadable(session, ctx, d):
                kept_back.add(d.ack)
        if d.ack:
            acks.add(d.ack)
    acknowledge = getattr(ctx.adapters.inbox, "acknowledge", None)
    done = 0
    for doc_id in list(session.scalars(select(Document.id).where(Document.status == "new").order_by(Document.id))):
        doc = session.get(Document, doc_id)
        if doc.read_attempts >= MAX_READ_ATTEMPTS:  # earlier tries never finished: the reader died on this file, so it must not block the queue again
            doc.status, doc.has_text_layer = "unreadable", False
            raise_exception(session, "unreadable_document", "warning", "document", doc_id, "Reading this file failed more than once (it may be damaged or built to exhaust the reader). Open the file and key the bill by hand.")
            session.commit()
            failed += 1
            continue
        doc.read_attempts += 1
        session.commit()  # counted BEFORE the file is read: if the process is killed while reading, the next pass still knows this try happened
        try:
            process_document(session, ctx, doc)
            session.commit()
            done += 1
        except Exception as exc:
            session.rollback()
            failed += 1
            log.warning("document %s could not be read into a bill (%s)", doc_id, type(exc).__name__)  # the class only: never the text of a bill
            doc = session.get(Document, doc_id)
            doc.status, doc.has_text_layer = "unreadable", False
            raise_exception(session, "unreadable_document", "warning", "document", doc_id, "This file could not be turned into a bill (it may be damaged or hold values no real bill holds). Open the file and key the bill by hand.")
            session.commit()
    if acknowledge is not None:
        acknowledge(sorted(acks - kept_back))  # only now are the messages marked read
    record_replies(session, ctx)
    session.commit()
    fxservice.flag_missing(session, ctx)
    return {"fetched": fetched, "processed": done, "failed": failed}


def _clean_note(text: str, n: int) -> str:
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", text or "").split())[:n]


def record_replies(session: Session, ctx) -> int:
    """Mail that came to the intake mailbox with no bill in it stays unread there. Here it is shown to a person when it comes from a customer, or asks to stop: a "stop" reply
    must never sit unseen. Nothing is switched off by it: a person looks, and opts the customer out on the Collections page if that is what was asked."""
    take = getattr(ctx.adapters.inbox, "take_notes", None)
    if take is None:
        return 0
    customers = {c.email.strip().casefold(): c for c in session.scalars(select(Customer)) if c.email}
    shown = 0
    for note in take():
        cust = customers.get((note.from_addr or "").strip().casefold())
        stop = bool(STOP_WORDS.search(f"{note.subject} {note.snippet}"))
        if cust is None and not stop:
            continue
        who = f"{cust.name} ({_clean_note(note.from_addr, 80)})" if cust else _clean_note(note.from_addr, 80) or "an unknown sender"
        what = "asks to stop the reminders" if stop else "answered"
        detail = f"{who} {what}. Subject: {_clean_note(note.subject, 80)}. Starts: {_clean_note(note.snippet, 140)}. The message is still unread in the mailbox."
        if stop:
            detail += " If they want no more reminders, switch them off for this customer on the Collections page."
        if cust:
            raise_exception(session, "stop_reply" if stop else "customer_reply", "warning", "customer", cust.id, detail)
        else:
            raise_exception(session, "stop_reply", "warning", "mail", int(note.uid) if str(note.uid).isdigit() else 0, detail)
        shown += 1
    return shown


def open_exceptions(session: Session) -> int:
    return session.query(ExceptionItem).filter(ExceptionItem.status == "open").count()
