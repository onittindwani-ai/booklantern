"""Bank statement CSV import. CSV only: no bank login is ever used or stored.

Columns are found by header name (Date, Description, Amount, Currency, Reference), in any order. Dates are ISO (2026-03-14). An amount is read strictly (see money.parse_amount): a line that
cannot be read for certain stops the whole import, and every such line is listed, so a statement is never imported with a sign guessed.
Duplicates: the same file imported twice into the same account adds nothing (each row is keyed by its account, its content and its position among identical rows). The same line in
another account is another line.
Identical rows inside one file are KEPT, because two real fees on one day look the same, and the later ones are marked as possible duplicates.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date

from booklantern.money import parse_amount


@dataclass
class Row:
    ref: str
    posted_on: date
    description: str
    amount_minor: int
    currency: str
    row_hash: str
    legacy_hash: str  # the key earlier versions stored (no account number in it); lines saved under it are recognised and re-keyed
    occurrence: int  # 1 for the first identical row, 2 for the second, and so on
    possible_duplicate: bool


class CsvError(ValueError):
    def __init__(self, message: str, lines: list[str] | None = None):
        super().__init__(message)
        self.lines = lines or []  # the lines that could not be read, one sentence each (empty for an error about the whole file)


MAX_ROWS = 50_000
MAX_LISTED = 15  # how many unreadable lines the message spells out
MAX_REF, MAX_DESC = 40, 300  # the widths of the columns they are stored in


def _cell(rec: dict, key: str, line: int, what: str) -> str:
    """One cell of a row. A row with fewer cells than the header has None there: that is a clear message, not a crash."""
    v = rec.get(key)
    if not isinstance(v, str):
        raise CsvError(f"Line {line}: the {what} is missing (the row has fewer columns than the header).")
    return v.strip()


def parse(text: str, default_currency: str = "USD", account_id: int | None = None) -> list[Row]:
    """The rows of a statement. `account_id` goes into each row's key, so the same line in two accounts is two lines (without it the key is the older, account free one)."""
    try:
        return _parse(text, default_currency, account_id)
    except csv.Error as exc:
        raise CsvError(f"The file could not be read as CSV: {exc}") from exc


def _parse(text: str, default_currency: str, account_id: int | None) -> list[Row]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise CsvError("The file is empty.")
    cols = {h.strip().lower(): h for h in reader.fieldnames}
    for need in ("date", "description", "amount"):
        if need not in cols:
            raise CsvError(f"The file needs a column called {need.capitalize()}. Found: {', '.join(reader.fieldnames)}.")
    out: list[Row] = []
    bad: list[str] = []
    seen: dict[str, int] = {}
    for n, rec in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            raise CsvError(f"The file has more than {MAX_ROWS} lines. Import it in parts.")
        raw_date = _cell(rec, cols["date"], n, "date")
        try:
            d = date.fromisoformat(raw_date)
        except ValueError:
            bad.append(f"Line {n}: the date {raw_date!r} is not in the form 2026-03-14.")
            continue
        raw_amount = _cell(rec, cols["amount"], n, "amount")
        # One strict reader for money everywhere: a minus sign in any form, brackets and a trailing minus are read, DR means money out and CR money in, and any character it does
        # not know makes the line unreadable. A line is never imported with its sign guessed.
        pa = parse_amount(raw_amount, (rec.get(cols.get("currency", "")) or default_currency).strip().upper() or default_currency, debit_credit=True)
        if pa is None or abs(pa[0]) > 10**12:
            bad.append(f"Line {n}: {raw_amount!r} is not an amount this system can read for certain (use digits with a minus sign, brackets, DR or CR).")
            continue
        desc = " ".join(_cell(rec, cols["description"], n, "description").split())[:MAX_DESC]
        base = hashlib.sha256(f"{d.isoformat()}|{desc}|{pa[0]}|{pa[1]}".encode()).hexdigest()
        keyed = base if account_id is None else hashlib.sha256(f"{account_id}|{d.isoformat()}|{desc}|{pa[0]}|{pa[1]}".encode()).hexdigest()
        seen[base] = seen.get(base, 0) + 1
        k = seen[base]
        ref = ((rec.get(cols.get("reference", "")) or "").strip() or base[:10] + f"-{k}")[:MAX_REF]
        legacy = hashlib.sha256(f"{base}|{k}".encode()).hexdigest()
        out.append(Row(ref, d, desc, pa[0], pa[1], hashlib.sha256(f"{keyed}|{k}".encode()).hexdigest(), legacy, k, k > 1))
    if bad:
        more = f" ({len(bad) - MAX_LISTED} more not shown)" if len(bad) > MAX_LISTED else ""
        raise CsvError(f"Nothing was imported: {len(bad)} line{'s' if len(bad) != 1 else ''} could not be read. " + " ".join(bad[:MAX_LISTED]) + more + " Fix them in the file and import it again. Lines already imported are never added twice.", bad)
    return out
