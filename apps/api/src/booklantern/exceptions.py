"""Exceptions: things a person must look at. One row per kind per item, so a rerun never piles up copies."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern.models import Bill, ExceptionItem


def _remember_block(session: Session, ref_type: str, ref_id: int) -> None:
    """A bill that has ever carried a blocking finding keeps `had_block`, whatever happens to the finding later. Editing the bill so the check passes closes the finding,
    but it must not switch off the rule that the person who made that edit cannot also approve it."""
    if ref_type == "bill":
        bill = session.get(Bill, ref_id)
        if bill is not None and not bill.had_block:
            bill.had_block = True
            session.flush()


def raise_exception(session: Session, kind: str, severity: str, ref_type: str, ref_id: int, detail: str, *, reopen_if_new: bool = False) -> ExceptionItem:
    """`reopen_if_new`: a closed finding opens again when this call carries different text. A message from a customer is a new event each time, so a second "stop" must be seen
    even though the first was closed; the same message found again (the text is the same) stays closed."""
    if severity == "block":
        _remember_block(session, ref_type, ref_id)
    row = session.scalars(select(ExceptionItem).where(ExceptionItem.kind == kind, ExceptionItem.ref_type == ref_type, ExceptionItem.ref_id == ref_id)).first()
    if row is None:
        row = ExceptionItem(kind=kind, severity=severity, ref_type=ref_type, ref_id=ref_id, detail=detail[:400])
        session.add(row)
        session.flush()
    elif row.status == "resolved" and reopen_if_new and row.detail != detail[:400]:
        row.status, row.severity, row.resolved_by, row.detail = "open", severity, "", detail[:400]
        session.flush()
    elif row.status == "resolved" and severity == "block":
        # The check fired again after someone closed it. A reason given for the bill as it was is not a reason for the bill as it is now, so a blocking
        # finding opens again. (Who closed it earlier stays in the audit log.) A closed warning stays closed: a person accepted it.
        row.status, row.severity, row.resolved_by, row.detail = "open", severity, "", detail[:400]
        session.flush()
    return row


def clear_open(session: Session, ref_type: str, ref_id: int, kinds: set[str]) -> None:
    rows = list(session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == ref_type, ExceptionItem.ref_id == ref_id, ExceptionItem.status == "open", ExceptionItem.kind.in_(kinds))))
    for row in rows:
        if row.severity == "block":
            _remember_block(session, ref_type, ref_id)  # a blocking row is about to be removed: the bill still remembers it had one
        session.delete(row)
    session.flush()


def resolve(session: Session, exc_id: int, who: str) -> ExceptionItem:
    row = session.get(ExceptionItem, exc_id)
    if row is None:
        raise ValueError("No such exception.")
    row.status, row.resolved_by = "resolved", who
    return row
