"""Approve a bill and post a draft to the accounting system. Posting needs approval, MODE live, ACCOUNTING_WRITE true and no kill switch."""

from __future__ import annotations

from sqlalchemy.orm import Session

from booklantern.adapters.base import DraftBill
from booklantern.exceptions import raise_exception
from booklantern.models import Bill, ExceptionItem, Vendor
from sendora_core.adapters import AdapterError
from sendora_core.audit import record_audit
from sendora_core.safety import SafetyError, guard_write
from sqlalchemy import select


def blocking(session: Session, bill: Bill) -> list[ExceptionItem]:
    return list(session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == bill.id, ExceptionItem.status == "open", ExceptionItem.severity == "block")))


class NoSuchBill(LookupError):
    pass


def get_bill(session: Session, bill_id: int) -> Bill:
    b = session.get(Bill, bill_id)
    if b is None:
        raise NoSuchBill("No such bill.")
    return b


def missing_fields(b: Bill) -> list[str]:
    """What a bill must have before anyone can approve it: a vendor, a bill date and an amount above zero. A blank scan has none of them."""
    out = []
    if b.vendor_id is None and not (b.vendor_name_read or "").strip():
        out.append("vendor")
    if b.issue_date is None:
        out.append("bill date")
    if b.total_minor <= 0:
        out.append("total")
    return out


def approve(session: Session, bill_id: int, who: str, override_note: str = "") -> Bill:
    b = get_bill(session, bill_id)
    if b.status not in ("needs_review", "inbox"):
        raise ValueError("This bill is not waiting for review.")
    missing = missing_fields(b)
    if missing:
        raise ValueError("This bill has no " + ", ".join(missing[:-1]) + (" or " if len(missing) > 1 else "") + missing[-1] + " yet. Fill " + ("them" if len(missing) > 1 else "it") + " in and save before you approve.")
    block = blocking(session, b)
    if block and not override_note.strip():
        raise ValueError("This bill has a blocking finding (" + ", ".join(e.kind for e in block) + "). Resolve it, or approve with a written reason.")
    b.status, b.edited_by = "approved", who
    record_audit(session, who, "bill.approved", f"bill:{b.id}", {"override": override_note[:200], "blocking": [e.kind for e in block]})
    return b


def reject(session: Session, bill_id: int, who: str, reason: str) -> Bill:
    b = get_bill(session, bill_id)
    if b.status not in ("needs_review", "inbox"):
        raise ValueError("Only a bill that is waiting for review can be rejected.")
    b.status = "rejected"
    record_audit(session, who, "bill.rejected", f"bill:{b.id}", {"reason": reason[:200]})
    return b


def post_draft(session: Session, ctx, bill_id: int, who: str) -> dict:
    b = get_bill(session, bill_id)
    if b.status != "approved":
        raise ValueError("Only an approved bill can be posted.")
    eff = ctx.effective(session)
    v = session.get(Vendor, b.vendor_id) if b.vendor_id else None
    draft = DraftBill(v.name if v else b.vendor_name_read, b.number, (b.issue_date.isoformat() if b.issue_date else ""), ((b.due_date or b.issue_date).isoformat() if (b.due_date or b.issue_date) else ""), b.currency,
                      [{"description": x.description, "quantity": x.quantity_milli / 1000, "unit_minor": x.unit_minor, "total_minor": x.total_minor} for x in b.lines], b.subtotal_minor, b.tax_minor, b.total_minor, f"Booklantern, document {b.document_id}")
    try:
        guard_write(eff, "accounting.create_draft_bill")
        if not eff.accounting_write:
            raise AdapterError("ACCOUNTING_WRITE is false. Booklantern reads your books and does not write to them until you switch that on.")
        ext = ctx.adapters.accounting.create_draft_bill(draft)
    except (SafetyError, AdapterError) as exc:
        record_audit(session, who, "bill.post_skipped", f"bill:{b.id}", {"reason": str(exc)[:200]})
        return {"posted": False, "reason": str(exc), "would_post": {"vendor": draft.vendor_name, "number": draft.number, "total_minor": draft.total_minor}}
    b.status, b.posted_external_id = "posted_draft", ext
    record_audit(session, who, "bill.posted_draft", f"bill:{b.id}", {"external_id": ext})
    return {"posted": True, "external_id": ext}
