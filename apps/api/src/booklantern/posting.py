"""Approve a bill and post a draft to the accounting system. Posting needs approval, MODE live, ACCOUNTING_WRITE true and no kill switch."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import httpx
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from booklantern.adapters.base import DraftBill, OutcomeUnknown
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
    """Every blocking finding row this bill still has on record, open or closed. A closed one still counts: someone looked at a risk on this bill and gave a reason."""
    return list(session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == bill.id, ExceptionItem.severity == "block")))


def had_block(session: Session, bill: Bill) -> bool:
    """True when this bill has ever carried a blocking finding. The flag on the bill is set the first time one fires and never cleared, so editing the finding away (the row
    is then removed, not closed) does not make the bill look clean again. The rows are looked at too, for a database made before the flag existed."""
    return bool(bill.had_block) or bool(blocking_ever(session, bill))


MIN_REASON_CHARS, MIN_REASON_WORDS, MIN_REASON_DISTINCT = 12, 2, 5


def real_reason(note: str) -> bool:
    """A written reason that says something: at least 12 characters, at least 2 words and at least 5 different letters or digits. One character, a row of the same
    letter or `ok ok ok` is not a reason. It cannot judge whether the reason is true: a person does that, and the audit log keeps the words."""
    text = " ".join((note or "").split())
    return len(text) >= MIN_REASON_CHARS and len(text.split()) >= MIN_REASON_WORDS and len({c for c in text.casefold() if c.isalnum()}) >= MIN_REASON_DISTINCT


REASON_HELP = f"Write a real reason: at least {MIN_REASON_CHARS} characters in at least {MIN_REASON_WORDS} words, saying what you checked."


class StaleBill(ValueError):
    """The bill changed after the page that is acting on it was loaded."""


def bill_etag(session: Session, b: Bill) -> str:
    """A short fingerprint of everything an approver looks at: the fields, the lines, the open findings and the vendor's account on file. The review page sends the one it
    loaded, and an approval with another one is refused, so a bill that changed (or whose vendor changed) after it was opened is never approved unseen."""
    v = session.get(Vendor, b.vendor_id) if b.vendor_id else None
    opens = sorted((e.id, e.kind, e.severity) for e in session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == b.id, ExceptionItem.status == "open")))
    payload = [b.status, b.vendor_id, b.vendor_name_read, b.number, str(b.issue_date), str(b.due_date), b.currency, b.po_number, b.bill_to, b.bank_account, b.subtotal_minor, b.tax_minor, b.total_minor,
               [(x.description, x.quantity_milli, x.unit_minor, x.total_minor) for x in b.lines], opens, [v.bank_account, v.currency, v.tax_rate_bp, v.requires_po] if v else None]
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()[:20]


def editors(session: Session, bill: Bill) -> set[str]:
    """Everyone who changed a field of this bill, from the audit log (the bill itself only remembers the last one, and approving writes a name there too)."""
    return set(session.scalars(select(AuditEntry.actor).where(AuditEntry.target == f"bill:{bill.id}", AuditEntry.action == "bill.edited")))


def self_review(session: Session, bill: Bill, who: str) -> bool:
    """True when this bill ever had a blocking finding and `who` changed it or closed one of its findings."""
    return had_block(session, bill) and who in (editors(session, bill) | resolvers(session, blocking_ever(session, bill)))


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


def approve(session: Session, bill_id: int, who: str, override_note: str = "", role: str = "owner", etag: str | None = None) -> Bill:
    """`etag` is the fingerprint the review page loaded (bill_etag). When it is sent and the bill is different now, nothing is approved."""
    b = get_bill(session, bill_id)
    if b.status not in ("needs_review", "inbox"):
        raise ValueError("This bill is not waiting for review.")
    if etag is not None and etag != bill_etag(session, b):
        raise StaleBill("This bill changed after you opened it (someone edited it, or its vendor or its findings changed). Reload the page, look at it again and approve it then.")
    missing = missing_fields(b)
    if missing:
        raise ValueError("This bill has no " + ", ".join(missing[:-1]) + (" or " if len(missing) > 1 else "") + missing[-1] + " yet. Fill " + ("them" if len(missing) > 1 else "it") + " in and save before you approve.")
    block = blocking(session, b)
    if block and not real_reason(override_note):
        raise ValueError("This bill has a blocking finding (" + ", ".join(e.kind for e in block) + "). Resolve it, or approve with a written reason. " + REASON_HELP)
    own_work = self_review(session, b, who)  # worked out before anything below writes a name on the bill
    if own_work:
        # Dual control for a bill that ever carried a blocking finding: the person who changed it, or who closed a finding on it, is not the one who approves it.
        if role != "owner":
            raise ValueError("You changed this bill, or closed a blocking finding on it, yourself. Someone else (or the owner) has to approve it.")
        if not real_reason(override_note):
            raise ValueError("You changed this bill, or closed a blocking finding on it, yourself. As the owner you can still approve it, with a written reason. " + REASON_HELP)
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


UNKNOWN_POST = "post_outcome_unknown"


def _carries_key(ctx) -> bool:
    """True for an accounting adapter that sends the idempotency key to a system that honours it (QuickBooks and Xero), so a repeated request returns the first draft."""
    return bool(getattr(ctx.adapters.accounting, "carries_idempotency_key", False))


def _outcome_unclear(exc: Exception) -> bool:
    """True when the request may have reached the accounting system and made its draft before the answer was lost: a timeout or a dropped connection after the request left, or an
    adapter that says so. A refused connection never sent anything, so that is not unclear."""
    if isinstance(exc, OutcomeUnknown):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, ConnectionRefusedError)):
        return False
    return isinstance(exc, (httpx.HTTPError, OSError))


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
        record_audit(session, who, "bill.post_claimed", f"bill:{b.id}", {"claimed_at": ctx.now(session).isoformat()})  # when the claim was made, so a bill left in "posting" is found later
        session.commit()  # the claim is saved BEFORE the accounting system is asked: if the process dies or the later save fails, the bill still says "posting", never "approved" with a draft already made
        try:
            made = ctx.adapters.accounting.create_draft_bill(draft)
        except Exception as exc:
            unclear, keyed = _outcome_unclear(exc), _carries_key(ctx)
            if unclear and not keyed:
                # This accounting system has no way to recognise a repeated request, so trying again could make a second draft. The bill stays in "posting" and a person looks in the
                # accounting system and says what happened (resolve_unknown_post). Nothing is posted again by itself.
                raise_exception(session, UNKNOWN_POST, "block", "bill", bill_id, "The accounting system did not answer clearly while this bill was being posted, so nobody knows whether it made the draft. Look for it there, then say what you found on this bill.")
                record_audit(session, who, "bill.post_unknown", f"bill:{b.id}", {"error": type(exc).__name__})
                raise AdapterError(f"The accounting system did not answer clearly ({type(exc).__name__}), and it cannot tell a repeated request from a new one. Booklantern does not know whether the draft was made, so it will not post this bill again by itself. "
                                   "Look for the draft in the accounting system, then say on this bill whether it was made.") from exc
            _move(session, bill_id, ("posting",), "approved")  # nothing was recorded as created: the bill goes back, so it can be posted again
            if isinstance(exc, (httpx.HTTPError, OSError)):  # no reply, a refused connection, a timeout: a safe message and an audit row, never a crash
                tail = "Try again in a moment: a repeated request returns the same draft, never a second one." if keyed else "Nothing was sent. Try again in a moment."
                raise AdapterError(f"The accounting system could not be reached ({type(exc).__name__}). Nothing was recorded as posted. {tail}") from exc
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


STALE_POST_MINUTES = 15  # a post that is still "posting" this long after it was claimed did not finish: the process died, or the finding about it was closed the wrong way


def sweep_stale_posts(session: Session, ctx) -> int:
    """Find every bill that has been in "posting" longer than STALE_POST_MINUTES with no open `post_outcome_unknown` finding, and raise it, so a person can say what happened
    (resolve_unknown_post). Without this a bill whose process died after the claim was saved sat in "posting" for good, out of the payables and the forecast. A bill with no record of
    its claim (made before the claim was recorded) counts as old. Returns how many were raised."""
    now, raised = ctx.now(session), 0
    for bill in list(session.scalars(select(Bill).where(Bill.status == "posting"))):
        if session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == bill.id, ExceptionItem.kind == UNKNOWN_POST, ExceptionItem.status == "open")).first():
            continue
        last = session.scalars(select(AuditEntry).where(AuditEntry.target == f"bill:{bill.id}", AuditEntry.action == "bill.post_claimed").order_by(AuditEntry.id.desc()).limit(1)).first()
        try:
            at = datetime.fromisoformat(str((last.detail or {}).get("claimed_at"))) if last else None
        except ValueError:
            at = None
        if at is not None and now - at < timedelta(minutes=STALE_POST_MINUTES):
            continue
        raise_exception(session, UNKNOWN_POST, "block", "bill", bill.id, "This bill was claimed for posting a while ago and never finished (the program stopped, or the answer was lost), so nobody knows whether the accounting system made the draft. Look for it there, then say what you found on this bill.")
        record_audit(session, "system", "bill.post_stale", f"bill:{bill.id}", {})
        raised += 1
    return raised


def resolve_unknown_post(session: Session, bill_id: int, who: str, posted: bool, external_id: str = "", note: str = "") -> Bill:
    """A person looked in the accounting system after an unclear post. `posted` True means the draft is there (its id is kept), False means it is not (the bill goes back to approved).
    A written reason is needed: it says what was looked at."""
    b = get_bill(session, bill_id)
    open_unknown = session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == b.id, ExceptionItem.kind == UNKNOWN_POST, ExceptionItem.status == "open")).first()
    if b.status != "posting" or open_unknown is None:
        raise ValueError("This bill has no unclear posting to settle.")
    if not real_reason(note):
        raise ValueError("Say what you looked at in the accounting system. " + REASON_HELP)
    ext = external_id.strip()[:80]
    if posted and not ext:
        raise ValueError("Type the id the accounting system gave the draft, so it can be found again.")
    if not _move(session, bill_id, ("posting",), "posted_draft" if posted else "approved"):
        raise ValueError("This bill has no unclear posting to settle.")
    b = get_bill(session, bill_id)
    if posted:
        b.posted_external_id = ext
    clear_open(session, "bill", b.id, {UNKNOWN_POST})
    record_audit(session, who, "bill.post_unknown_resolved", f"bill:{b.id}", {"posted": posted, "external_id": ext, "note": note[:200]})
    return b
