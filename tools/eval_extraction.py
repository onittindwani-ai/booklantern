"""Score the offline extractor. python tools/eval_extraction.py --set dev|heldout [--write FILE]

The first held out run is saved untouched in data/eval/heldout_first_run.json and must never be overwritten
(this tool refuses to). The stand in is rule based and is NOT a language model, so these numbers say nothing about a live model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
from booklantern.evals.extraction_eval import run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["dev", "heldout"], default="dev")
    ap.add_argument("--write", default="")
    a = ap.parse_args()
    r = run("documents" if a.set == "dev" else "heldout")
    print(f"{a.set}: {r['readable']} readable of {r['documents']} documents, field accuracy {r['field_accuracy_percent']} percent, {r['documents_fully_correct']} documents fully correct")
    for n, v in r["fields"].items():
        print(f"  {n:16s} {v['correct']:3d}/{v['total']:3d}  {v['accuracy']}%")
    if r["unreadable_scans"]:
        print("  not readable (scans, no OCR):", ", ".join(r["unreadable_scans"]))
    if a.write:
        p = Path(a.write)
        if p.name == "heldout_first_run.json" and p.exists():
            print("refusing to overwrite the saved first held out run")
            return 1
        p.write_text(json.dumps(r, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
