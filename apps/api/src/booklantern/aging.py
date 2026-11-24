"""Receivables aging by code. Days late are counted from the due date; not yet due is `current`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")


@dataclass(frozen=True)
class OpenItem:
    id: int
    customer_id: int
    due: date
    outstanding_minor: int


def days_late(due: date, as_of: date) -> int:
    return (as_of - due).days


def bucket_for(late: int) -> str:
    if late <= 0:
        return "current"
    if late <= 30:
        return "1-30"
    if late <= 60:
        return "31-60"
    if late <= 90:
        return "61-90"
    return "90+"


def age(items: list[OpenItem], as_of: date) -> dict:
    buckets = {b: 0 for b in BUCKETS}
    by_customer: dict[int, dict[str, int]] = {}
    for it in items:
        if it.outstanding_minor <= 0:
            continue
        b = bucket_for(days_late(it.due, as_of))
        buckets[b] += it.outstanding_minor
        by_customer.setdefault(it.customer_id, {k: 0 for k in BUCKETS})[b] += it.outstanding_minor
    return {"buckets_minor": buckets, "total_minor": sum(buckets.values()), "by_customer": by_customer}
