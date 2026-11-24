"""Write the synthetic seed: PDFs, the bank file, the receivables, and the answer key with every planted problem.

Run: python tools/make_seed.py   (deterministic, safe to run again). Everything in the output is fictional.
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from booklantern.money import line_total, mul_bp  # noqa: E402
from tools.seedgen.docspec import COMPANY, OTHER_COMPANY, DocSpec, Line  # noqa: E402
from tools.seedgen.layouts_dev import DEV_LAYOUTS  # noqa: E402
from tools.seedgen.layouts_heldout import HELDOUT_LAYOUTS  # noqa: E402
from tools.seedgen.world import AS_OF, CUSTOMERS, FX_EUR_USD_BP, VENDORS, build_world  # noqa: E402

DATA = ROOT / "data"
VM = {v.key: v for v in VENDORS}
LADDER_DAYS = (1, 7, 14, 30)


def _spec(did: str, layout: str, v, rng: random.Random, k: int, hist: dict, issue: date | None = None) -> DocSpec:
    med = statistics.median(h["subtotal_minor"] for h in hist[v.key])
    for _ in range(300):
        picks = rng.sample(v.items, k=min(len(v.items), rng.choice([1, 2, 2, 3])))
        lines = []
        for desc, unit, q in picks:
            qq = max(1000, int(q * rng.choice([0.5, 0.75, 1, 1, 1.25, 1.5])) // 1000 * 1000) if q >= 4000 else q
            lines.append(Line(desc, qq, unit, line_total(qq, unit)))
        sub = sum(x.total_minor for x in lines)
        if 0.6 * med <= sub <= 1.6 * med:
            break
    issue = issue or AS_OF - timedelta(days=rng.randint(3, 60))
    tax = mul_bp(sub, v.tax_bp)
    po = f"PO-{rng.randint(1000, 9999)}" if (v.requires_po or rng.random() < 0.4) else None
    return DocSpec(did, layout, v.name, v.addr, v.account, f"{v.name[:3].upper()}-{4000 + k}", issue, issue + timedelta(days=v.terms_days), v.currency, po, COMPANY, lines, v.tax_bp, sub, tax, sub + tax)


def _resum(s: DocSpec) -> None:
    s.subtotal_minor = sum(x.total_minor for x in s.lines)
    s.tax_minor = mul_bp(s.subtotal_minor, s.tax_rate_bp)
    s.total_minor = s.subtotal_minor + s.tax_minor


def make_dev(world) -> list[DocSpec]:
    rng = random.Random(77)
    hist: dict[str, list[dict]] = {}
    for b in world.bills_hist:
        hist.setdefault(b["vendor"], []).append(b)
    layouts = ["A", "B", "C", "D"]
    vend_cycle = [VM[k] for k in ("V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08")]
    specs: list[DocSpec] = []
    po_vendors = [VM["V03"], VM["V04"]]
    for k in range(54):
        v = vend_cycle[k % 8]
        if k in (31, 32, 33):
            v = po_vendors[k % 2]
        if k == 36:
            v = VM["V07"]
        if k == 37:
            v = VM["V01"]
        s = _spec(f"D{k + 1:03d}", layouts[k % 4], v, rng, k, hist)
        if k in (40, 41):  # exact duplicates of earlier documents, drawn in another layout
            src = specs[(3, 9)[k - 40]]
            s = DocSpec(**{**src.__dict__, "doc_id": s.doc_id, "layout": layouts[(layouts.index(src.layout) + 1) % 4], "problems": ["duplicate_exact"], "duplicate_of": src.doc_id})
        elif k in (42, 43, 44):  # near duplicates: same vendor and amount, number or date slightly different
            src = specs[(5, 12, 17)[k - 42]]
            kw = {**src.__dict__, "doc_id": s.doc_id, "layout": layouts[(layouts.index(src.layout) + 2) % 4], "problems": ["duplicate_near"], "duplicate_of": src.doc_id}
            if k == 42:
                kw["number"] = src.number + "A"
            elif k == 43:
                kw["number"] = src.number[:-2] + src.number[-1] + src.number[-2]  # two digits swapped
            else:
                kw["issue"], kw["due"] = src.issue + timedelta(days=1), src.due + timedelta(days=1)
            s = DocSpec(**kw)
        elif k in (20, 21, 22):
            s.total_minor += (10000, -4500, 25000)[k - 20]; s.problems = ["wrong_total"]
        elif k in (23, 24):
            s.tax_minor += s.subtotal_minor * (3 if k == 23 else 2) // 100 + 100; s.total_minor = s.subtotal_minor + s.tax_minor; s.problems = ["wrong_tax"]
        elif k in (25, 26):
            s.lines[0].total_minor += 5000 if k == 25 else 1800; s.problems = ["line_sum_mismatch"]
        elif k in (27, 28):
            s.account = f"FICT-9{k}-7788"; s.problems = ["bank_change"]
        elif k in (29, 30):
            for ln in s.lines:
                ln.qty_milli = max(ln.qty_milli, 1000) * 8; ln.total_minor = line_total(ln.qty_milli, ln.unit_minor)
            _resum(s); s.problems = ["amount_8x"]
        elif k in (31, 32, 33):
            s.po = None; s.problems = ["missing_po"]
        elif k in (34, 35):
            s.issue = AS_OF + timedelta(days=10 + k - 34); s.due = s.issue + timedelta(days=30); s.problems = ["future_date"]
        elif k in (36, 37):
            s.currency = "USD" if k == 36 else "EUR"; s.problems = ["currency_mismatch"]
        elif k in (38, 39):
            s.bill_to = OTHER_COMPANY; s.problems = ["wrong_company"]
        specs.append(s)
    scan_plans = [None, None, "wrong_total", None, "amount_8x", None]
    for j, pl in enumerate(scan_plans):
        v = vend_cycle[(j + 3) % 8]
        s = _spec(f"D{55 + j:03d}", "S", v, rng, 100 + j, hist)
        if pl == "wrong_total":
            s.total_minor += 7000
        elif pl == "amount_8x":
            for ln in s.lines:
                ln.qty_milli = max(ln.qty_milli, 1000) * 8; ln.total_minor = line_total(ln.qty_milli, ln.unit_minor)
            _resum(s)
        s.problems = [pl] if pl else []
        specs.append(s)
    return specs


def make_heldout(world) -> list[DocSpec]:
    rng = random.Random(4242)
    hist: dict[str, list[dict]] = {}
    for b in world.bills_hist:
        hist.setdefault(b["vendor"], []).append(b)
    out = []
    vs = [VM[k] for k in ("V01", "V03", "V05", "V06", "V07", "V02", "V04", "V08")]
    for k in range(24):
        lay = "EFGH"[k % 4]
        v = VM["V07"] if lay == "H" and k % 8 in (3, 7) else vs[(k * 3) % 8]
        s = _spec(f"H{k + 1:03d}", lay, v, rng, 200 + k, hist)
        if k % 5 == 0 and not v.requires_po:
            s.po = None
        out.append(s)
    return out


def write_pdfs(specs: list[DocSpec], layouts: dict, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for s in specs:
        layouts[s.layout](s, str(folder / f"{s.doc_id}.pdf"))


def aging_expected(world) -> dict:
    b = {"current": 0, "1-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    for i in world.invoices:
        out = i["total_minor"] - i["paid_minor"]
        if i["status"] != "open" or out <= 0:
            continue
        late = (AS_OF - date.fromisoformat(i["due"])).days
        key = "current" if late <= 0 else "1-30" if late <= 30 else "31-60" if late <= 60 else "61-90" if late <= 90 else "90+"
        b[key] += out
    return b


def reminder_history(world) -> list[dict]:
    flagged = {c.key for c in CUSTOMERS if c.flag}
    out = []
    for i in world.invoices:
        if i["status"] != "open" or i["customer"] in flagged or i["flag"]:
            continue
        due = date.fromisoformat(i["due"])
        for n, d in enumerate(LADDER_DAYS, start=1):
            when = due + timedelta(days=d)
            promised = next((p for p in world.promises if p["invoice"] == i["number"]), None)
            if when < AS_OF and not (promised and when >= AS_OF - timedelta(days=12)):
                out.append({"invoice": i["number"], "step": n, "sent_on": when.isoformat()})
    return out


def main() -> None:
    w = build_world()
    dev, held = make_dev(w), make_heldout(w)
    write_pdfs(dev, DEV_LAYOUTS, DATA / "documents")
    write_pdfs(held, HELDOUT_LAYOUTS, DATA / "heldout" / "documents")
    total_flow = sum(t["amount_minor"] for t in w.bank)
    closing_target = 3_200_000  # a fictional balance chosen so the 13 week forecast has a visible low point
    opening = closing_target - total_flow
    seed = {
        "fictional": True, "company": {"name": COMPANY, "currency": "USD"}, "as_of": AS_OF.isoformat(),
        "vendors": [{"key": v.key, "name": v.name, "addr": v.addr, "currency": v.currency, "tax_bp": v.tax_bp, "requires_po": v.requires_po, "account": v.account, "terms_days": v.terms_days} for v in VENDORS],
        "customers": [c.__dict__ for c in CUSTOMERS], "invoices": w.invoices, "bills_hist": w.bills_hist,
        "bank_account": {"name": "Operating account (fictional)", "opening_minor": opening, "opening_date": "2025-12-01"},
        "fx_rates_bp": {"EUR": FX_EUR_USD_BP}, "bank_csv": "bank_statement.csv", "recurring": w.recurring, "promises": w.promises, "reminders": reminder_history(w),
        "documents": [{"id": s.doc_id, "file": f"documents/{s.doc_id}.pdf", "source": "inbox" if int(s.doc_id[1:]) % 3 else "upload",
                       "from": f"billing@{s.vendor.split()[0].lower()}.example.test", "subject": f"Invoice {s.number}"} for s in dev],
    }
    key = {
        "fictional": True,
        "documents": {s.doc_id: {"file": f"documents/{s.doc_id}.pdf", "layout": s.layout, "scan": s.layout == "S", "fields": s.truth(), "problems": s.problems, "duplicate_of": s.duplicate_of} for s in dev},
        "heldout": {s.doc_id: {"file": f"heldout/documents/{s.doc_id}.pdf", "layout": s.layout, "fields": s.truth()} for s in held},
        "reconciliation": w.key,
        "aging": {"as_of": AS_OF.isoformat(), "buckets_minor": aging_expected(w)},
        "collections": {"promises": w.promises, "disputes": [i["number"] for i in w.invoices if i["flag"] == "dispute"],
                        "bankruptcy_customers": [c.key for c in CUSTOMERS if c.flag == "bankruptcy"], "opt_out_customers": [c.key for c in CUSTOMERS if c.flag == "opt_out"]},
    }
    problems: dict[str, int] = {}
    for s in dev:
        for p in s.problems:
            problems[p] = problems.get(p, 0) + 1
    counts = {"dev_documents": len(dev), "dev_scans": sum(s.layout == "S" for s in dev), "heldout_documents": len(held), "planted_document_problems": problems,
              "vendors": len(VENDORS), "customers": len(CUSTOMERS), "invoices": len(w.invoices), "open_invoices": sum(i["status"] == "open" for i in w.invoices), "vendor_history_bills": len(w.bills_hist),
              "bank_lines": len(w.bank), "bank_planted": {"duplicate_lines": 3, "unmatched_lines": 3, "split_deposits": sum(v["kind"] == "split" for v in w.key.values())}}
    lines = ["Date,Description,Amount,Currency,Reference"] + [f'{t["date"]},"{t["description"]}",{t["amount_minor"] // 100}.{abs(t["amount_minor"]) % 100:02d},{t["currency"]},{t["ref"]}' for t in w.bank]
    (DATA / "bank_statement.csv").write_text("\n".join(lines) + "\n")
    def amt(a: int) -> str:
        return f"{'-' if a < 0 else ''}{abs(a) // 100}.{abs(a) % 100:02d}"

    rows = ["Date,Description,Amount,Currency,Reference"] + [f'{t["date"]},"{t["description"]}",{amt(t["amount_minor"])},{t["currency"]},{t["ref"]}' for t in w.bank]
    (DATA / "bank_statement.csv").write_text("\n".join(rows) + "\n")
    (DATA / "seed.json").write_text(json.dumps(seed, indent=1) + "\n")
    (DATA / "answer_key.json").write_text(json.dumps(key, indent=1) + "\n")
    (DATA / "seed_counts.json").write_text(json.dumps(counts, indent=1) + "\n")
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
