"""Score an extractor against an answer key, field by field. The key holds what is printed on each page."""

from __future__ import annotations

import json
from pathlib import Path

from booklantern.extraction.offline import extract as offline_extract
from booklantern.extraction.schema import Extraction
from booklantern.seeding import REPO_DATA as DATA  # a development tool: it needs a source checkout

SCORED = ("vendor", "number", "issue_date", "due_date", "currency", "po", "bill_to", "subtotal_minor", "tax_minor", "total_minor", "bank_account", "tax_rate_bp")


def _norm(v):
    return v.strip().casefold() if isinstance(v, str) else v


def field_ok(name: str, got, want) -> bool:
    if name == "po":
        got = "" if _norm(got) in (None, "", "none quoted", "-", "n/a") else got
    return _norm(got if got is not None else "") == _norm(want if want is not None else "")


def score_document(ex: Extraction, truth: dict) -> dict[str, bool]:
    out = {n: field_ok(n, ex.value(n), truth.get(n)) for n in SCORED}
    out["line_totals"] = [x.total_minor for x in ex.lines] == sorted(truth["line_totals_minor"], key=lambda _: 0) or sorted(x.total_minor for x in ex.lines) == sorted(truth["line_totals_minor"])
    return out


def run(key_name: str = "documents", extractor=offline_extract, data_dir: Path = DATA) -> dict:
    key = json.loads((data_dir / "answer_key.json").read_text())[key_name]
    per_field: dict[str, list[bool]] = {}
    docs = {}
    unreadable = []
    for did, item in key.items():
        ex = extractor((data_dir / item["file"]).read_bytes())
        if not ex.readable:
            unreadable.append(did)
            continue
        sc = score_document(ex, item["fields"])
        docs[did] = sc
        for n, ok in sc.items():
            per_field.setdefault(n, []).append(ok)
    fields = {n: {"correct": sum(v), "total": len(v), "accuracy": round(100 * sum(v) / len(v), 1)} for n, v in per_field.items()}
    allv = [x for v in per_field.values() for x in v]
    whole = sum(all(s.values()) for s in docs.values())
    return {"set": key_name, "documents": len(key), "readable": len(docs), "unreadable_scans": unreadable, "fields": fields,
            "field_accuracy_percent": round(100 * sum(allv) / max(len(allv), 1), 1), "documents_fully_correct": whole, "extractor": getattr(extractor, "__module__", "")}
