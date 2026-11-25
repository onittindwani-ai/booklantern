"""Exceptions: things a person must look at. One row per kind per item, so a rerun never piles up copies."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern.models import ExceptionItem


def raise_exception(session: Session, kind: str, severity: str, ref_type: str, ref_id: int, detail: str) -> ExceptionItem:
    row = session.scalars(select(ExceptionItem).where(ExceptionItem.kind == kind, ExceptionItem.ref_type == ref_type, ExceptionItem.ref_id == ref_id)).first()
    if row is None:
        row = ExceptionItem(kind=kind, severity=severity, ref_type=ref_type, ref_id=ref_id, detail=detail[:400])
        session.add(row)
        session.flush()
    elif row.status == "resolved" and severity == "block":
        # The check fired again after someone closed it. A reason given for the bill as it was is not a reason for the bill as it is now, so a blocking
        # finding opens again. (Who closed it earlier stays in the audit log.) A closed warning stays closed: a person accepted it.
        row.status, row.severity, row.resolved_by, row.detail = "open", severity, "", detail[:400]
        session.flush()
    return row


def clear_open(session: Session, ref_type: str, ref_id: int, kinds: set[str]) -> None:
    for row in session.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == ref_type, ExceptionItem.ref_id == ref_id, ExceptionItem.status == "open", ExceptionItem.kind.in_(kinds))):
        session.delete(row)
    session.flush()


def resolve(session: Session, exc_id: int, who: str) -> ExceptionItem:
    row = session.get(ExceptionItem, exc_id)
    if row is None:
        raise ValueError("No such exception.")
    row.status, row.resolved_by = "resolved", who
    return row
