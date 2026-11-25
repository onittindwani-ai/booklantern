"""Approve a bill and post a draft to the accounting system. Posting needs approval, MODE live, ACCOUNTING_WRITE true and no kill switch."""

from __future__ import annotations

import httpx
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from booklantern.adapters.base import DraftBill
from booklantern.exceptions import clear_open, raise_exception
from booklantern.models import Bill, ExceptionItem, Vendor
from booklantern.money import format_minor
from sendora_core.adapters import AdapterError
from sendora_core.audit import record_audit
from sendora_core.models import AuditEntry
from sendora_core.safety import SafetyError, guard_write
from sqlalchemy import select


def blocking(session: Session, bill: Bill) -> list[ExceptionItem]:
    return list(session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == bill.id, ExceptionItem.status == "open", ExceptionItem.severity == "block")))


def blocking_ever(session: Session, bill: Bill) -> list[ExceptionItem]:
    """Every blocking finding this bill has on record, open or closed. A closed one still counts: someone looked at a risk on this bill and gave a reason."""
    return list(session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == bill.id, ExceptionItem.severity == "block")))


def editors(session: Session, bill: Bill) -> set[str]:
    """Everyone who changed a field of this bill, from the audit log (the bill itself only remembers the last one, and approving writes a name there too)."""
    return set(session.scalars(select(AuditEntry.actor).where(AuditEntry.target == f"bill:{bill.id}", AuditEntry.action == "bill.edited")))


def self_review(session: Session, bill: Bill, who: str) -> bool:
    """True when this bill ever had a blocking finding and `who` changed it or closed one of its findings."""
    ever = blocking_ever(session, bill)
    return bool(ever) and who in (editors(session, bill) | resolvers(session, ever))


def resolvers(session: Session, findings: list[ExceptionItem]) -> set[str]:
    """Everyone who closed one of these findings, from the audit log (a finding that opened again keeps no name of its own)."""
    targets = [f"exception:{e.id}" for e in findings]
    if not targets:
        return set()
    return set(session.scalars(select(AuditEntry.actor).where(AuditEntry.target.in_(targets), AuditEntry.action == "exception.resolved")))


class NoSuchBill(LookupError):
    pass


def _move(session: Session, bill_id: int, from_states: tuple[str, ...], to_state: str) -> bool:
    """Change a bill's status only if it is still in one of `from_states`, in one conditional UPDATE. Two people (or two clicks) acting at the same moment cannot both
    pass: the database lets one UPDATE through and the other sees the new status and changes nothing. True when this call made the change."""
    res = session.execute(update(Bill).where(Bill.id == bill_id, Bill.status.in_(from_states)).values(status=to_state).execution_options(synchronize_session=False))
    session.flush()
    session.expire_all()
    return res.rowcount == 1


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


def approve(session: Session, bill_id: int, who: str, override_note: str = "", role: str = "owner") -> Bill:
    b = get_bill(session, bill_id)
    if b.status not in ("needs_review", "inbox"):
        raise ValueError("This bill is not waiting for review.")
    missing = missing_fields(b)
    if missing:
        raise ValueError("This bill has no " + ", ".join(missing[:-1]) + (" or " if len(missing) > 1 else "") + missing[-1] + " yet. Fill " + ("them" if len(missing) > 1 else "it") + " in and save before you approve.")
    block = blocking(session, b)
    if block and not override_note.strip():
        raise ValueError("This bill has a blocking finding (" + ", ".join(e.kind for e in block) + "). Resolve it, or approve with a written reason.")
    own_work = self_review(session, b, who)  # worked out before anything below writes a name on the bill
    if own_work:
        # Dual control for a bill that ever carried a blocking finding: the person who changed it, or who closed a finding on it, is not the one who approves it.
        if role != "owner":
            raise ValueError("You changed this bill, or closed a blocking finding on it, yourself. Someone else (or the owner) has to approve it.")
        if not override_note.strip():
            raise ValueError("You changed this bill, or closed a blocking finding on it, yourself. As the owner you can still approve it, with a written reason.")
    if not _move(session, bill_id, ("needs_review", "inbox"), "approved"):
        raise ValueError("This bill is not waiting for review.")
    b = get_bill(session, bill_id)
    b.edited_by = who
    record_audit(session, who, "bill.approved", f"bill:{b.id}", {"override": override_note[:200], "blocking": [e.kind for e in block], "self_review": own_work})
    return b


def reject(session: Session, bill_id: int, who: str, reason: str) -> Bill:
    b = get_bill(session, bill_id)
    if b.status not in ("needs_review", "inbox"):
        raise ValueError("Only a bill that is waiting for review can be rejected.")
    if not _move(session, bill_id, ("needs_review", "inbox"), "rejected"):
        raise ValueError("Only a bill that is waiting for review can be rejected.")
    b = get_bill(session, bill_id)
    record_audit(session, who, "bill.rejected", f"bill:{b.id}", {"reason": reason[:200]})
    return b


def _post_round(session: Session, bill: Bill) -> int:
    """How many drafts of this bill came back with the wrong total so far. It is part of the idempotency key, so once a person has removed a wrong draft a new try makes a new one."""
    return int(session.scalar(select(func.count()).select_from(AuditEntry).where(AuditEntry.target == f"bill:{bill.id}", AuditEntry.action == "bill.post_mismatch")) or 0)


def post_draft(session: Session, ctx, bill_id: int, who: str) -> dict:
    b = get_bill(session, bill_id)
    if b.status != "approved":
        raise ValueError("Only an approved bill can be posted.")
    eff = ctx.effective(session)
    v = session.get(Vendor, b.vendor_id) if b.vendor_id else None
    draft = DraftBill(v.name if v else b.vendor_name_read, b.number, (b.issue_date.isoformat() if b.issue_date else ""), ((b.due_date or b.issue_date).isoformat() if (b.due_date or b.issue_date) else ""), b.currency,
                      [{"description": x.description, "quantity": x.quantity_milli / 1000, "unit_minor": x.unit_minor, "total_minor": x.total_minor} for x in b.lines], b.subtotal_minor, b.tax_minor, b.total_minor, f"Booklantern, document {b.document_id}",
                      idempotency_key=f"booklantern-bill-{b.id}" + (f"-r{_post_round(session, b)}" if _post_round(session, b) else ""))
    try:
        guard_write(eff, "accounting.create_draft_bill")
        if not eff.accounting_write:
            raise AdapterError("ACCOUNTING_WRITE is false. Booklantern reads your books and does not write to them until you switch that on.")
        if not _move(session, bill_id, ("approved",), "posting"):  # claimed: a second request at the same moment finds it no longer approved and stops here
            raise ValueError("Only an approved bill can be posted.")
        try:
            made = ctx.adapters.accounting.create_draft_bill(draft)
        except Exception as exc:
            _move(session, bill_id, ("posting",), "approved")  # nothing was recorded as created: the bill goes back, so it can be posted again
            if isinstance(exc, (httpx.HTTPError, OSError)):  # no reply, a refused connection, a timeout: a safe message and an audit row, never a crash
                raise AdapterError(f"The accounting system could not be reached ({type(exc).__name__}). Nothing was recorded as posted. Try again in a moment: a repeated request returns the same draft, never a second one.") from exc
            raise
    except (SafetyError, AdapterError) as exc:
        record_audit(session, who, "bill.post_skipped", f"bill:{b.id}", {"reason": str(exc)[:200]})
        return {"posted": False, "reason": str(exc), "would_post": {"vendor": draft.vendor_name, "number": draft.number, "total_minor": draft.total_minor}}
    ext = str(made)
    returned = getattr(made, "total_minor", None)
    b = get_bill(session, bill_id)
    if returned is not None and returned != b.total_minor:
        # The accounting system holds a draft that is not the bill that was approved. That is not a success: the bill goes back to review, with the draft's id so a person can remove it.
        b.status, b.posted_external_id = "needs_review", ext
        reason = f"The draft made in the accounting system (id {ext}) has a total of {format_minor(returned, b.currency)}, but the approved bill is {format_minor(b.total_minor, b.currency)}. Remove that draft there, check the bill's lines and tax, and approve it again."
        raise_exception(session, "post_total_mismatch", "block", "bill", b.id, reason)
        record_audit(session, who, "bill.post_mismatch", f"bill:{b.id}", {"external_id": ext, "returned_minor": returned, "approved_minor": b.total_minor})
        return {"posted": False, "needs_review": True, "external_id": ext, "reason": reason}
    b.status, b.posted_external_id = "posted_draft", ext
    clear_open(session, "bill", b.id, {"post_total_mismatch"})  # an earlier wrong draft was dealt with: the finding about it is done
    record_audit(session, who, "bill.posted_draft", f"bill:{b.id}", {"external_id": ext, "total_checked": returned is not None})
    return {"posted": True, "external_id": ext}
