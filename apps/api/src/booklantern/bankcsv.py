"""Bank statement CSV import. CSV only: no bank login is ever used or stored.

Columns are found by header name (Date, Description, Amount, Currency, Reference), in any order. Dates are ISO (2026-03-14).
Duplicates: the same file imported twice adds nothing (each row is keyed by its content plus its position among identical rows).
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
    occurrence: int  # 1 for the first identical row, 2 for the second, and so on
    possible_duplicate: bool


class CsvError(ValueError):
    pass


MAX_ROWS = 50_000
MAX_REF, MAX_DESC = 40, 300  # the widths of the columns they are stored in


def _cell(rec: dict, key: str, line: int, what: str) -> str:
    """One cell of a row. A row with fewer cells than the header has None there: that is a clear message, not a crash."""
    v = rec.get(key)
    if not isinstance(v, str):
        raise CsvError(f"Line {line}: the {what} is missing (the row has fewer columns than the header).")
    return v.strip()


def parse(text: str, default_currency: str = "USD") -> list[Row]:
    try:
        return _parse(text, default_currency)
    except csv.Error as exc:
        raise CsvError(f"The file could not be read as CSV: {exc}") from exc


def _parse(text: str, default_currency: str) -> list[Row]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise CsvError("The file is empty.")
    cols = {h.strip().lower(): h for h in reader.fieldnames}
    for need in ("date", "description", "amount"):
        if need not in cols:
            raise CsvError(f"The file needs a column called {need.capitalize()}. Found: {', '.join(reader.fieldnames)}.")
    out: list[Row] = []
    seen: dict[str, int] = {}
    for n, rec in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            raise CsvError(f"The file has more than {MAX_ROWS} lines. Import it in parts.")
        raw_date = _cell(rec, cols["date"], n, "date")
        try:
            d = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise CsvError(f"Line {n}: the date {raw_date!r} is not in the form 2026-03-14.") from exc
        raw_amount = _cell(rec, cols["amount"], n, "amount")
        pa = parse_amount(raw_amount, (rec.get(cols.get("currency", "")) or default_currency).strip() or default_currency)
        if pa is None or abs(pa[0]) > 10**12:
            raise CsvError(f"Line {n}: {raw_amount!r} is not an amount.")
        desc = " ".join(_cell(rec, cols["description"], n, "description").split())[:MAX_DESC]
        base = hashlib.sha256(f"{d.isoformat()}|{desc}|{pa[0]}|{pa[1]}".encode()).hexdigest()
        seen[base] = seen.get(base, 0) + 1
        k = seen[base]
        ref = ((rec.get(cols.get("reference", "")) or "").strip() or base[:10] + f"-{k}")[:MAX_REF]
        out.append(Row(ref, d, desc, pa[0], pa[1], hashlib.sha256(f"{base}|{k}".encode()).hexdigest(), k, k > 1))
    return out
