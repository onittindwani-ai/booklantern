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


def parse(text: str, default_currency: str = "USD") -> list[Row]:
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
        try:
            d = date.fromisoformat(rec[cols["date"]].strip())
        except ValueError as exc:
            raise CsvError(f"Line {n}: the date {rec[cols['date']]!r} is not in the form 2026-03-14.") from exc
        pa = parse_amount(rec[cols["amount"]], rec.get(cols.get("currency", ""), "") or default_currency)
        if pa is None:
            raise CsvError(f"Line {n}: {rec[cols['amount']]!r} is not an amount.")
        desc = " ".join(rec[cols["description"]].split())
        base = hashlib.sha256(f"{d.isoformat()}|{desc}|{pa[0]}|{pa[1]}".encode()).hexdigest()
        seen[base] = seen.get(base, 0) + 1
        k = seen[base]
        ref = (rec.get(cols.get("reference", ""), "") or "").strip() or base[:10] + f"-{k}"
        out.append(Row(ref, d, desc, pa[0], pa[1], hashlib.sha256(f"{base}|{k}".encode()).hexdigest(), k, k > 1))
    return out
