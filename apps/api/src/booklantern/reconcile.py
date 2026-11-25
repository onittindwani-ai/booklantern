"""Bank reconciliation: scored matching of bank lines to invoices, bills and recurring items. Pure code, no model.

Score (0 to 100, every part is named so the page can show why):
  amount equals what is still open: 50     name of the customer or vendor found in the description (fuzzy): up to 30
  invoice or bill number found in the description: 25 (digits only also count)     date in a believable window: 10
A deposit marked as a part payment scores at least 55, and 5 more when it is exactly a half, a third or a quarter of what is open. A split (one deposit paying several invoices of one customer) is found by trying subsets of two to four of that customer's open
invoices whose open amounts add up to the deposit exactly. Score 90.
Auto confirm at 85 and above, but only when the name of the customer or vendor was also found in the description: an amount, a number and a date can all be copied
by whoever writes the payment reference, so without a name a person confirms. Suggest from 60, otherwise leave the line unmatched for a person.
A line that is identical to an earlier line of the same file is a possible duplicate and is never matched twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from itertools import combinations

from booklantern.fx import RateBook

CONFIRM_AT, SUGGEST_AT = 85, 60
MAX_SPLIT_CANDIDATES = 25  # open invoices of one customer tried in a split: 25 choose 4 is 12,650 sums, a few hundred thousand is where it would stall


@dataclass
class Txn:
    id: int
    posted_on: date
    description: str
    amount_minor: int
    currency: str = "USD"
    possible_duplicate: bool = False


@dataclass
class Target:
    kind: str  # invoice, bill
    id: int
    number: str
    party: str
    open_minor: int  # in the target's own currency
    issue: date | None
    due: date | None
    currency: str = "USD"
    settled: bool = False  # already marked paid in the books: a bank line may still be linked to it (a statement that covers old payments), but an open document always comes first


@dataclass
class RecurringT:
    id: int
    name: str
    match_text: str
    amount_minor: int  # signed


@dataclass
class Link:
    kind: str
    id: int
    allocated_minor: int
    score: int
    reason: str


@dataclass
class Result:
    txn_id: int
    outcome: str  # matched, suggested, unmatched, duplicate, recurring
    links: list[Link] = field(default_factory=list)
    note: str = ""


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", s.casefold()) if t not in {"and", "co", "ltd", "the"}]


def name_score(desc: str, name: str) -> int:
    dt, nt = _tokens(desc), _tokens(name)
    if not nt:
        return 0
    hit = sum(1 for n in nt if any(SequenceMatcher(None, n, d).ratio() >= 0.8 for d in dt))
    first = any(SequenceMatcher(None, nt[0], d).ratio() >= 0.8 for d in dt)
    return round(30 * hit / len(nt)) if hit and first else (10 if hit else 0)


def number_in(desc: str, number: str) -> bool:
    digits = re.sub(r"\D", "", number)
    d = desc.casefold()
    return number.casefold() in d or (len(digits) >= 4 and re.search(rf"(?<!\d){digits}(?!\d)", d) is not None)


def _in_target_ccy(amount: int, cur: str, c: Target, on: date, rates: RateBook | None) -> tuple[int | None, str]:
    """The bank amount expressed in the target's currency, and a note saying which manual rate was used.

    Same currency: the amount as it is. A bank line in the company currency against a target in another one: if the target's open
    amount converted at the manual rate of that day equals the bank amount, the open amount is returned exactly, otherwise the bank
    amount is converted back at the same rate. With no rate, or any other currency pair, there is no honest comparison: None.
    """
    if cur == c.currency:
        return amount, ""
    if rates is None or cur != rates.base:
        return None, ""
    conv = rates.try_convert(c.open_minor, c.currency, on)
    if conv is None:
        return None, ""
    note = f"converted at the manual rate {conv.rate} dated {conv.rate_date}"
    return (c.open_minor if conv.base_minor == amount else rates.back(amount, c.currency, on)), note


def _score(t: Txn, c: Target, amount_in_target_ccy: int) -> tuple[int, str]:
    parts, s = [], 0
    if amount_in_target_ccy == c.open_minor:
        s += 50; parts.append("amount equals the open amount")
    n = name_score(t.description, c.party)
    if n:
        s += n; parts.append(f"name looks like {c.party}")
    if number_in(t.description, c.number):
        s += 25; parts.append(f"number {c.number} in the description")
    if c.issue and c.issue <= t.posted_on <= (c.due or t.posted_on) + timedelta(days=60):
        s += 10; parts.append("date is in a believable window")
    return min(s, 100), "; ".join(parts)


def match_all(txns: list[Txn], targets: list[Target], recurring: list[RecurringT], rates: RateBook | None = None) -> list[Result]:
    left = {(c.kind, c.id): c.open_minor for c in targets}
    by_key = {(c.kind, c.id): c for c in targets}
    out: list[Result] = []

    for t in sorted(txns, key=lambda x: (x.posted_on, x.id)):
        if t.possible_duplicate:
            out.append(Result(t.id, "duplicate", note="Identical to an earlier line in the same file."))
            continue
        rec = next((r for r in recurring if r.match_text.casefold() in t.description.casefold() and r.amount_minor == t.amount_minor), None)
        if rec:
            out.append(Result(t.id, "recurring", [Link("recurring", rec.id, t.amount_minor, 95, f"matches the repeating item {rec.name}")]))
            continue
        want_kind = "invoice" if t.amount_minor > 0 else "bill"
        pool = [c for c in targets if c.kind == want_kind and left[(c.kind, c.id)] > 0]
        amt = abs(t.amount_minor)
        best_open: tuple[int, str, Target, int] | None = None
        best_settled: tuple[int, str, Target, int] | None = None
        for c in pool:
            a, note = _in_target_ccy(amt, t.currency, c, t.posted_on, rates)
            if a is None:
                continue
            sc, why = _score(t, c, a)
            if note:
                why = (why + "; " if why else "") + note
            partial = a < left[(c.kind, c.id)] and name_score(t.description, c.party) and ("part" in t.description.casefold())
            if partial:
                sc, why = max(sc, 55), why + "; marked as a part payment"
                if left[(c.kind, c.id)] % a == 0:  # exactly a half, a third, a quarter of what is open: of two invoices of one customer, the one it divides is the likelier
                    sc, why = sc + 5, why + f"; exactly 1/{left[(c.kind, c.id)] // a} of the open amount"
            if c.settled:
                why += "; already marked paid in the books"
            cand = (sc, why, c, a)
            if c.settled:
                if best_settled is None or (sc, -(c.due or date.max).toordinal()) > (best_settled[0], -(best_settled[2].due or date.max).toordinal()):
                    best_settled = cand
            elif best_open is None or (sc, -(c.due or date.max).toordinal()) > (best_open[0], -(best_open[2].due or date.max).toordinal()):
                best_open = cand
        # An open invoice or bill that fits always wins over one that is already marked paid: a later deposit of the same amount from the same customer pays the one that is still open.
        best = next((b for b in (best_open, best_settled) if b and b[0] >= SUGGEST_AT - 5 and (b[0] >= SUGGEST_AT or "part payment" in b[1])), None)
        if best:
            sc, why, c, a = best
            alloc = min(a, left[(c.kind, c.id)])
            left[(c.kind, c.id)] -= alloc
            named = name_score(t.description, c.party) > 0
            # A line that fits a document already marked paid is confirmed by itself only when it also names that document's number (a statement that covers old payments does).
            # A repeat deposit of the same amount with no number is not: a person looks, because the real open invoice may be the one it pays.
            unproven = c.settled and f"number {c.number} in the description" not in why
            if unproven:
                why += "; no document number on the line, so a person confirms"
            out.append(Result(t.id, "matched" if sc >= CONFIRM_AT and named and not unproven else "suggested", [Link(c.kind, c.id, alloc, sc, why if named or sc < CONFIRM_AT or unproven else why + "; no name found, so a person confirms")]))
            continue
        split = _split(t, pool, left)
        if split:
            for lk in split:
                left[(lk.kind, lk.id)] -= lk.allocated_minor
            out.append(Result(t.id, "matched", split, note="One payment for several invoices."))
            continue
        out.append(Result(t.id, "unmatched", note="No invoice, bill or repeating item fits this line."))
    return out


def _split(t: Txn, pool: list[Target], left: dict) -> list[Link] | None:
    if t.amount_minor <= 0:
        return None
    named = [c for c in pool if name_score(t.description, c.party) >= 10 and c.currency == t.currency]
    by_party: dict[str, list[Target]] = {}
    for c in named:
        by_party.setdefault(c.party, []).append(c)
    for party, items in by_party.items():
        items = sorted(items, key=lambda c: (c.due or date.max, c.id))[:MAX_SPLIT_CANDIDATES]
        for n in (2, 3, 4):
            for combo in combinations(items, n):
                if sum(left[(c.kind, c.id)] for c in combo) == t.amount_minor:
                    return [Link(c.kind, c.id, left[(c.kind, c.id)], 90, f"part of one payment from {party}") for c in combo]
    return None
