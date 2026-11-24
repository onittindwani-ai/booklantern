"""Score the offline bill reader and the checks on an independent test set (written by people who never saw the code).

A set folder holds `docs/doc_NNN.txt` (the text layer of one bill each, pages split by a form feed), `key.json` (one object per file) and `context.json`
(the client name, the reference date and a vendor master). The reader is rules written by the build. It is NOT a language model, and these numbers say
nothing about a live model.

How a text file becomes input (fixed before the first run): every line becomes a row of cells (a cell is a run of text, two or more spaces start a new cell,
the same split as `cells.read_page`), 5.5 points per character and 12 points per line. A page holds the lines up to the next form feed. The reader is given
the page the PDF path would give it (the first page today). A page with fewer than 20 characters has no usable text layer.

Fixed mapping choices (written before any run). One scorer bug was fixed after the first runs and is disclosed in docs/EXTRACTION-EVAL.md: a document the reader could not use
was always counted as no_text_layer, but the mapping below says only a page with no text at all is; a page with text the reader cannot use is unreadable_or_low_confidence.
- Field scoring uses the reader's raw value: vendor (fuzzy match against the printed name or its aliases, `validation.similar` >= 0.85), invoice number (exact),
  invoice date, due date (when none is printed, empty or the date the terms give both count), currency, subtotal, tax, total (minor units, absolute value for
  credit notes; an amount the document does not print counts as right when the reader gives none), and the line amounts as a multiset.
- Not extracted by this system, so reported as such and not dropped: document type (bill or credit note) and payment terms.
- A hard document (key `needs_person`) passes when the reader says it cannot read it, or when every field it gives is below the low confidence line (50).
  Any field at 50 or more on such a document is a confident wrong value and a failure.
- Findings go through the system's own code: `validation.validate`, `match_vendor`, the low confidence line of `intake`, the base currency fallback of intake.
  The vendor master is built from `context.json`: default currency, PO flag, account on file; one tax rate on file becomes the vendor rate, a list of rates
  becomes the first (version 2 of the tool also passes the whole list, and maps the new code tax_rate_differs to tax_rate_sanity); history is three totals at the low, middle and high of the typical range, used only when the bill is in the vendor's currency.
  The company name is `client_company` only. `as_of` is the reference date.
- Code names: wrong_total is total_mismatch, wrong_company is wrong_addressee, bank_detail_changed is changed_bank_details, amount_far_above_history is
  amount_vs_history, wrong_tax is tax_rate_sanity, unreadable_document is no_text_layer (nothing to read) or unreadable_or_low_confidence, low_confidence is
  unreadable_or_low_confidence. Any other code the system raises (for example unknown_vendor) is counted on its own line.
- A byte identical copy counts as found when its sha256 merges it at intake. A duplicate pair counts as found when either file of the pair is flagged.
- Calibration: accuracy per confidence band (under 50, 50 to 79, 80 and up) and the number of fields that were 80 or more and wrong.

The first run of a set is saved untouched and is the reported number; this tool refuses to overwrite a `*_first_run.json`. The file lists failing documents by
id and field name only, never values or text. Never tune on a set and call it held out.

Run: python tools/eval_independent.py --set a --out data/eval/independent/set_a_first_run.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from booklantern import intake, validation as V  # noqa: E402
from booklantern.extraction import offline  # noqa: E402
from booklantern.extraction.textpages import pages_from_text  # noqa: E402
from booklantern.extraction.cells import Page  # noqa: E402
from booklantern.extraction.schema import Extraction  # noqa: E402

BASE = ROOT / "data" / "eval" / "independent"
SOURCE = ROOT.parent / "_heldout" / "ledgerlight"
FIELDS = ("vendor", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax", "total", "line_amounts")
NOT_EXTRACTED = ("doc_type", "payment_terms")
BAND = (("under_50", 0, 49), ("50_to_79", 50, 79), ("80_up", 80, 100))
CODE_OF = {"tax_rate_differs": "tax_rate_sanity", "wrong_total": "total_mismatch", "line_sum_mismatch": "line_sum_mismatch", "wrong_tax": "tax_rate_sanity", "duplicate_exact": "duplicate_exact", "duplicate_near": "duplicate_near",
           "future_date": "future_date", "wrong_company": "wrong_addressee", "missing_po": "missing_po", "bank_detail_changed": "changed_bank_details",
           "amount_far_above_history": "amount_vs_history", "currency_mismatch": "currency_mismatch", "low_confidence": "unreadable_or_low_confidence"}
BASE_CURRENCY = "USD"


# ---- loading
def load_set(folder: Path) -> list[dict]:
    key = json.loads((folder / "key.json").read_text(encoding="utf-8"))
    ctx = json.loads((folder / "context.json").read_text(encoding="utf-8"))
    docs = []
    for k in key:
        data = (folder / "docs" / k["file"]).read_bytes()
        docs.append({"key": k, "bytes": data, "pages": pages_from_text(data.decode("utf-8")), "sha": hashlib.sha256(data).hexdigest()})
    return [{**d, "ctx": ctx} for d in docs]


def read_document(pages: list[Page]) -> Extraction:
    """What the system does with the text layer. The newest reader reads every page; the first reader read the first one only."""
    fn = getattr(offline, "extract_pages", None)
    return fn(pages) if fn else offline.extract_page(pages[0], len(pages))


# ---- field scoring
def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def field_results(ex: Extraction, k: dict) -> dict[str, bool]:
    names = [k["vendor"], *k.get("vendor_aliases", [])]
    got = ex.value("vendor")
    out = {"vendor": bool(got) and any(V.similar(str(got), n) >= 0.85 or _norm(n) in _norm(got) for n in names if n)}
    out["invoice_number"] = _norm(ex.value("number")) == _norm(k["invoice_number"])
    out["invoice_date"] = (ex.value("issue_date") or None) == k["invoice_date"]
    due, derived = ex.value("due_date") or None, k.get("due_date_derived_from_terms")
    out["due_date"] = due == k["due_date"] if k["due_date"] else due in (None, derived)
    out["currency"] = _norm(ex.value("currency")) == _norm(k["currency"])
    for ours, theirs, printed in (("subtotal_minor", "subtotal", "subtotal_printed"), ("tax_minor", "tax", "tax_printed"), ("total_minor", "total", "")):
        want, g = k[f"{theirs}_minor"], ex.value(ours)
        gv = abs(int(g)) if g not in (None, "") else None
        out[theirs] = gv == (abs(want) if want is not None else None) or (bool(printed) and not k.get(printed, True) and gv in (None, 0))
    out["line_amounts"] = sorted(abs(x.total_minor) for x in ex.lines) == sorted(abs(x["amount_minor"]) for x in k.get("line_items", []))
    return out


def band(conf: int) -> str:
    return next(n for n, lo, hi in BAND if lo <= conf <= hi)


def hard_passes(ex: Extraction) -> bool:
    return not ex.readable or all(f.confidence < intake.LOW_CONFIDENCE for f in ex.fields.values())


# ---- findings through the system's own code
def vendor_master(ctx: dict) -> dict[str, V.VendorData]:
    out = {}
    for i, (name, v) in enumerate(ctx["vendor_master"].items(), 1):
        rates = v.get("tax_rates_on_file_bps") or [0]
        out[name] = V.VendorData(i, name, v["default_currency"], rates[0], bool(v["requires_po"]), v.get("iban_on_file") or "", tuple(rates))
    return out


def findings_for(ex: Extraction, ctx: dict, vendors: dict, earlier: list[V.BillData], bill_id: int, chars: int = 0) -> tuple[list[str], list[str], V.BillData | None]:
    """(codes in the key's names, other codes, the bill) for one document. `chars` is the size of the text layer: none is no_text_layer, a layer the reader cannot use is unreadable_or_low_confidence."""
    if not ex.readable:
        return ["no_text_layer" if chars < 20 else "unreadable_or_low_confidence"], [], None
    vlist = list(vendors.values())
    name = str(ex.value("vendor") or "")
    vm = V.match_vendor(name, vlist) if name else None
    d = lambda k: date.fromisoformat(ex.value(k)) if ex.value(k) else None  # noqa: E731
    try:
        bill = V.BillData(bill_id, vm.id if vm else None, str(ex.value("number") or ""), d("issue_date"), str(ex.value("currency") or BASE_CURRENCY), str(ex.value("po") or ""),
                          str(ex.value("bill_to") or ""), str(ex.value("bank_account") or ""), int(ex.value("subtotal_minor") or 0), int(ex.value("tax_minor") or 0), int(ex.value("total_minor") or 0),
                          [x.total_minor for x in ex.lines], ex.value("tax_rate_bp"))
    except ValueError:
        return ["unreadable_or_low_confidence"], [], None
    master = next((v for n, v in ctx["vendor_master"].items() if vm and n == vm.name), None)
    hist = []
    if master and bill.currency == master["default_currency"] and master.get("typical_total_minor_range"):
        lo, hi = master["typical_total_minor_range"]
        hist = [lo, (lo + hi) // 2, hi]
    found = V.validate(bill, vm, earlier, hist, ctx["client_company"], date.fromisoformat(ctx["reference_today"]))
    codes = [f.kind for f in found] + (["suspicious_text"] if ex.flags else [])
    if any(f.confidence < intake.LOW_CONFIDENCE for f in ex.fields.values()):
        codes.append("low_confidence")
    mapped = [CODE_OF[c] for c in codes if c in CODE_OF]
    return mapped, [c for c in codes if c not in CODE_OF], bill


def expected_codes(k: dict) -> set[str]:
    return {e if isinstance(e, str) else e.get("code") for e in k.get("expected_findings", [])}


# ---- the whole run
def evaluate(docs: list[dict]) -> dict:
    ctx = docs[0]["ctx"]
    vendors = vendor_master(ctx)
    fcount: dict[str, list[int]] = {n: [0, 0] for n in FIELDS}
    cal: dict[str, list[int]] = {b: [0, 0] for b, _, _ in BAND}
    confident_wrong = whole = easy = 0
    doc_type = {"correct": 0, "total": 0}
    hard_total = hard_ok = hard_confident_wrong = 0
    failures: dict[str, list[str]] = {}
    by_tag: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    tp, fn, fp = Counter(), Counter(), Counter()
    other: Counter = Counter()
    seen: dict[str, str] = {}
    created: list[tuple[str, V.BillData]] = []
    raised: dict[str, set[str]] = {}
    extractor = ""
    for n, d in enumerate(docs, 1):
        k, ex = d["key"], read_document(d["pages"])
        extractor = ex.extractor
        if k["needs_person"]:
            hard_total += 1
            ok = hard_passes(ex)
            hard_ok += ok
            hard_confident_wrong += any(f.confidence >= intake.LOW_CONFIDENCE for f in ex.fields.values())
            if not ok:
                failures[k["doc_id"]] = ["confident_on_hard_document"]
        else:
            res = field_results(ex, k)
            for name, ok in res.items():
                fcount[name][0] += ok
                fcount[name][1] += 1
            for name, f in ex.fields.items():  # calibration over the fields that the key scores
                m = {"issue_date": "invoice_date", "number": "invoice_number", "subtotal_minor": "subtotal", "tax_minor": "tax", "total_minor": "total"}.get(name, name)
                if m in res:
                    cal[band(f.confidence)][0] += res[m]
                    cal[band(f.confidence)][1] += 1
                    confident_wrong += f.confidence >= 80 and not res[m]
            if ex.value("doc_type"):  # reported on its own: the first reader had no such field, so it is not part of the all fields right count
                doc_type["total"] += 1
                doc_type["correct"] += ex.value("doc_type") == ("credit_note" if k["doc_type"] == "credit_note" else "bill")
            all_ok = all(res.values())
            whole += all_ok
            easy += 1
            if not all_ok:
                failures[k["doc_id"]] = [x for x, ok in res.items() if not ok]
            for t in k.get("tags", []):
                by_tag[t][0] += all_ok
                by_tag[t][1] += 1
        merged = d["sha"] in seen
        seen.setdefault(d["sha"], k["file"])
        codes: list[str] = []
        if merged:
            codes = ["duplicate_exact"]
        else:
            earlier = [b for _, b in created]
            codes, extra, bill = findings_for(ex, ctx, vendors, earlier, n, sum(p.chars for p in d["pages"]))
            other.update(extra)
            if bill is not None:
                created.append((k["file"], bill))
        raised[k["file"]] = set(codes)
    # pair rule: a duplicate counts as found when either file of the pair carries the code
    pairs = {d["key"]["file"]: d["key"].get("duplicate_of") for d in docs if d["key"].get("duplicate_of")}
    partner = {**pairs, **{v: f for f, v in pairs.items()}}
    for d in docs:
        k = d["key"]
        want, got = expected_codes(k), set(raised[k["file"]])
        if k["file"] in partner:
            for c in ("duplicate_exact", "duplicate_near"):
                if c in want:
                    got |= raised.get(partner[k["file"]], set()) & {c}
        pair_codes = {"duplicate_exact", "duplicate_near"}
        for c in want:
            (tp if c in got else fn)[c] += 1
        for c in got - want:
            if c in pair_codes and k["file"] in partner:  # the original of a duplicate pair may be flagged too
                continue
            fp[c] += 1
    codes_all = sorted(set(tp) | set(fn) | set(fp))
    findings = {c: {"found": tp[c], "missed": fn[c], "false_flags": fp[c]} for c in codes_all}
    return {
        "extractor": extractor, "documents": len(docs), "readable_attempted": easy, "hard_documents": hard_total,
        "fields": {n: {"correct": v[0], "total": v[1], "percent": round(100 * v[0] / max(v[1], 1), 1)} for n, v in fcount.items()},
        "field_percent": round(100 * sum(v[0] for v in fcount.values()) / max(sum(v[1] for v in fcount.values()), 1), 1),
        "documents_all_fields_right": whole, "documents_all_fields_right_percent": round(100 * whole / max(easy, 1), 1),
        "hard": {"passed": hard_ok, "total": hard_total, "confident_on_hard": hard_confident_wrong},
        "calibration": {b: {"right": v[0], "total": v[1], "percent": round(100 * v[0] / max(v[1], 1), 1)} for b, v in cal.items()}, "confident_wrong_fields": confident_wrong,
        "findings": findings, "findings_found": sum(tp.values()), "findings_expected": sum(tp.values()) + sum(fn.values()), "false_flags_total": sum(fp.values()),
        "other_codes_raised": dict(other), "not_extracted": [n for n in NOT_EXTRACTED if not (n == "doc_type" and doc_type["total"])], "doc_type": doc_type,
        "by_tag_all_fields_right": {t: {"right": v[0], "total": v[1]} for t, v in sorted(by_tag.items())},
        "failing_documents": failures,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["a", "b"], required=True)
    ap.add_argument("--source", default="", help="a set folder (default: the copy under data/eval/independent)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = Path(a.out) if a.out else None
    if out and out.name.endswith("_first_run.json") and out.exists():
        print("refusing to overwrite a saved first run")
        return 1
    folder = Path(a.source) if a.source else BASE / f"set_{a.set}"
    r = evaluate(load_set(folder))
    print(f"set {a.set}: {r['documents']} documents, {r['hard']['passed']} of {r['hard']['total']} hard documents handled, field accuracy {r['field_percent']} percent, "
          f"{r['documents_all_fields_right']} of {r['readable_attempted']} documents with every field right, findings {r['findings_found']} of {r['findings_expected']}, "
          f"{r['false_flags_total']} false flags, {r['confident_wrong_fields']} fields 80 or more and wrong")
    for n, v in r["fields"].items():
        print(f"  {n:15s} {v['correct']:3d}/{v['total']:3d} {v['percent']}%")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
