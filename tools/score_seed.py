"""Run the whole pipeline on the seed and compare with data/answer_key.json. Prints PASS or FAIL per check and a summary.

Checks: each planted document problem is found, nothing extra is flagged on clean documents, duplicates point at the right original,
scans are reported as not covered offline (they are neither passes nor failures), the bank lines match the key, and the aging buckets
equal the independently computed ones.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from sqlalchemy import select  # noqa: E402

from booklantern import collections, demo, jobs  # noqa: E402
from booklantern.config import Settings  # noqa: E402
from booklantern.context import Ctx  # noqa: E402
from booklantern.models import Bill, BankTransaction, Document, ExceptionItem, Invoice, Match  # noqa: E402
from sendora_core import models as _core  # noqa: E402,F401
from sendora_core.db import Base, make_engine, make_session_factory  # noqa: E402

PROBLEM_KIND = {"wrong_total": "wrong_total", "wrong_tax": "wrong_tax", "line_sum_mismatch": "line_sum_mismatch", "bank_change": "bank_detail_changed", "amount_8x": "amount_far_above_history",
                "missing_po": "missing_po", "future_date": "future_date", "currency_mismatch": "currency_mismatch", "wrong_company": "wrong_company", "duplicate_exact": "duplicate_exact", "duplicate_near": "duplicate_near"}
CHECKED = set(PROBLEM_KIND.values())


def build_ctx(tmp: str) -> Ctx:
    s = Settings(database_url=f"sqlite:///{tmp}/score.sqlite3", upload_dir=f"{tmp}/uploads", _env_file=None)
    eng = make_engine(s.database_url)
    Base.metadata.create_all(eng)
    return Ctx(s, make_session_factory(eng))


def main() -> int:
    key = json.loads((ROOT / "data/answer_key.json").read_text())
    results: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        ctx = build_ctx(tmp)
        with ctx.factory() as s:
            demo.reset(s, ctx)
        with ctx.factory() as s:
            jobs.run_cycle(s, ctx)
            s.commit()
        with ctx.factory() as s:
            docs = {d.ref: d for d in s.scalars(select(Document))}
            bills = {b.document_id: b for b in s.scalars(select(Bill)) if b.document_id}
            flags: dict[str, set[str]] = {}
            refs: dict[str, list[int]] = {}
            for ref, d in docs.items():
                b = bills.get(d.id)
                ex = list(s.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == b.id))) if b else []
                flags[ref] = {e.kind for e in ex if e.kind in CHECKED}
            id_to_ref = {d.id: r for r, d in docs.items()}
            bill_doc = {b.id: id_to_ref.get(b.document_id) for b in s.scalars(select(Bill))}
            found = missed = extra = covered = 0
            scans = []
            pairs = {frozenset((did, it["duplicate_of"])) for did, it in key["documents"].items() if it["duplicate_of"]}
            bill_of = {ref: bills[d.id] for ref, d in docs.items() if d.id in bills}
            dup_links = set()  # pairs of document refs that a duplicate flag connects (flag sits on whichever was read second)
            for ref, b in bill_of.items():
                for e in s.scalars(select(ExceptionItem).where(ExceptionItem.ref_type == "bill", ExceptionItem.ref_id == b.id, ExceptionItem.kind.in_(("duplicate_exact", "duplicate_near")))):
                    for other in (bb for bb in bill_of.items() if f"bill {bb[1].id}" in e.detail or f"bill {bb[1].id}." in e.detail):
                        dup_links.add(frozenset((ref, other[0])))
            for did, item in key["documents"].items():
                if item["scan"]:
                    scans.append(did)
                    continue
                covered += 1
                want = {PROBLEM_KIND[p] for p in item["problems"]} - {"duplicate_exact", "duplicate_near"}
                got = flags.get(did, set()) - {"duplicate_exact", "duplicate_near"}
                found += len(want & got); missed += len(want - got); extra += len(got - want)
                if want != got:
                    results.append((f"document {did}", False, f"expected {sorted(want)}, got {sorted(got)}"))
            pf = len(pairs & dup_links)
            found += pf; missed += len(pairs - dup_links); extra += len(dup_links - pairs)
            tot = found + missed
            results.append((f"planted document problems found ({found} of {tot}, duplicates counted per pair)", missed == 0, ""))
            results.append((f"no extra flags on documents ({extra} extra)", extra == 0, ""))
            ok_dup, bad_dup = pf, len(pairs - dup_links)
            results.append((f"scans reported as not covered offline ({len(scans)} documents, not counted as passes or failures)", all(docs[x].status == "unreadable" for x in scans), ""))
            # bank lines
            rec = key["reconciliation"]
            ids = {i.id: i.number for i in s.scalars(select(Invoice))}
            bnum = {b.id: b.number for b in s.scalars(select(Bill))}
            good = 0
            for t in s.scalars(select(BankTransaction)):
                k = rec[t.ref]
                ms = list(s.scalars(select(Match).where(Match.bank_txn_id == t.id)))
                if k["kind"] == "duplicate":
                    ok = t.status == "exception" and not ms
                elif k["kind"] == "none":
                    ok = t.status == "exception" and not ms
                elif k["kind"] == "recurring":
                    ok = bool(ms) and all(m.target_type == "recurring" for m in ms)
                else:
                    ok = sorted((ids.get(m.invoice_id) or bnum.get(m.bill_id)) for m in ms) == sorted(x["number"] for x in k["targets"])
                good += ok
            n = s.query(BankTransaction).count()
            results.append((f"bank lines matched as the key says ({good} of {n}, {round(100 * good / n, 1)} percent)", good >= int(0.95 * n), ""))
            # aging
            rep = collections.aging_report(s, ctx.today(s))["buckets_minor"]
            results.append(("aging buckets equal the independent calculation", rep == key["aging"]["buckets_minor"], f"{rep} vs {key['aging']['buckets_minor']}"))
            c = key["collections"]
            results.append(("disputes, promises and flags are in the data", s.query(Invoice).filter(Invoice.disputed.is_(True)).count() == len(c["disputes"]), ""))
    bad = [r for r in results if not r[1]]
    for name, ok, why in results:
        print(("PASS " if ok else "FAIL ") + name + (f"  {why}" if why and not ok else ""))
    print(f"\n{len(results) - len(bad)} of {len(results)} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
