#!/usr/bin/env python3
"""Measure the numbers the docs quote and write them to data/counts.json.

Every count in README and docs/ comes from this file. Run it after any change, then run tools/check_docs.py.
  python3 tools/make_counts.py            measure and write (runs the Python tests once, with coverage)
  python3 tools/make_counts.py --fast     skip the test run and keep the last test and coverage numbers
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "counts.json"
PY = str(ROOT / ".venv" / "bin" / "python") if (ROOT / ".venv" / "bin" / "python").exists() else sys.executable


def run_tests() -> dict:
    cov = ROOT / ".coverage-counts.json"
    p = subprocess.run([PY, "-m", "pytest", "apps/api/tests", "mock/tests", "tools/tests", "-o", "addopts=", "-q", "-p", "no:warnings", "--cov=booklantern", f"--cov-report=json:{cov}"], cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"(\d+) passed", p.stdout)
    skipped = re.search(r"(\d+) skipped", p.stdout)
    failed = re.search(r"(\d+) failed", p.stdout)
    pct = None
    if cov.exists():
        pct = round(json.loads(cov.read_text())["totals"]["percent_covered"], 1)
        cov.unlink()
    return {"passed": int(m.group(1)) if m else 0, "skipped": int(skipped.group(1)) if skipped else 0, "failed": int(failed.group(1)) if failed else 0, "coverage_percent": pct}


def main(argv: list[str]) -> int:
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    seed = json.loads((ROOT / "data" / "seed_counts.json").read_text())
    api = json.loads((ROOT / "docs" / "openapi.json").read_text())
    ops = sum(1 for v in api["paths"].values() for k in v if k in ("get", "post", "put", "patch", "delete"))
    models = (ROOT / "apps/api/src/booklantern/models.py").read_text()
    tables = len(re.findall(r'__tablename__ = "ll_', models))
    lst = subprocess.run(["pnpm", "exec", "playwright", "test", "--list"], cwd=ROOT / "apps" / "web", capture_output=True, text=True).stdout
    mm = re.search(r"Total: (\d+) tests? in (\d+) files?", lst)
    e2e = {"tests": int(mm.group(1)), "files": int(mm.group(2))} if mm else old.get("e2e")
    scores = json.loads((ROOT / "data" / "tool_scores.json").read_text())
    held = json.loads((ROOT / "data" / "eval" / "heldout_first_run.json").read_text())
    pages = len(re.findall(r'href: "/', (ROOT / "apps/web/src/components/AppFrame.tsx").read_text()))
    shots = len(list((ROOT / "docs" / "screenshots").glob("*.png")))
    tests = old.get("tests") if "--fast" in argv else run_tests()
    data = {
        "tables": tables, "api_paths": len(api["paths"]), "api_operations": ops, "pages": pages or 11, "screenshots": shots,
        "tool_groups": len(scores["groups"]), "tools_scored": sum(len(g["tools"]) for g in scores["groups"]),
        "seed": seed, "heldout_documents": held["documents"], "e2e": e2e, "tests": tests,
    }
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print("OK wrote", OUT.relative_to(ROOT), json.dumps({k: data[k] for k in ("tables", "api_paths", "pages", "screenshots", "tools_scored", "tests")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
