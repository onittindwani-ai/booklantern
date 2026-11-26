"""Record the model answers for the seed bills and a few word tasks into data/llm_fixtures/, so the demo can replay them with LLM_BACKEND=fixture.

IMPORTANT: these are NOT answers of a real model. The recording goes through the real anthropic code path (request building, schema, response parsing, the checks by code)
against a local mock server that answers with the offline stand in. So the fixtures prove the replay path and the request shape, not model quality. Replace them with a
recording from a real key (LLM_RECORD=true) when you have one.

Run: python tools/record_llm_fixtures.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(ROOT))

from booklantern import model_tasks  # noqa: E402
from booklantern.config import Settings  # noqa: E402
from booklantern.extraction.live import extract_with_model  # noqa: E402
from booklantern.extraction.cells import page_count, read_page  # noqa: E402
from booklantern.offline_llm import OfflineBackend  # noqa: E402
from mock.anthropic_mock import StubAnthropic  # noqa: E402
from sendora_core.llm import build_llm, reset_budgets  # noqa: E402

OUT = ROOT / "data" / "llm_fixtures"
FORECAST = {"opening": "$12,400.00", "closing": "$18,950.00", "low": "$9,800.00", "low_week": 4, "receipts": "$31,200.00", "runs_out": None, "beyond": "", "weeks": 13}
MONTH = {"open_invoices": 14, "receivable": "$21,300.00", "bills_to_review": 5, "unmatched": 3, "exceptions": 9}
REMINDER = {"number": "INV-1042", "amount": "$480.00", "due": "2026-10-20", "late": 14, "customer": "Example Customer Ltd"}


def stand_in(body: dict) -> str:
    return OfflineBackend().complete(model=body["model"], system=body.get("system", ""), prompt=body["messages"][0]["content"], max_tokens=body["max_tokens"]).text


def documents() -> list[Path]:
    return sorted((ROOT / "data" / "documents").glob("*.pdf"))


def record() -> dict:
    if OUT.exists():
        shutil.rmtree(OUT)
    n = 0
    with StubAnthropic(stand_in) as stub:
        settings = Settings(_env_file=None, llm_backend="anthropic", anthropic_api_key="stub-key-for-local-server", anthropic_base_url=stub.url, llm_record=True, llm_fixtures_dir=str(OUT), database_url="sqlite://")
        reset_budgets()
        llm = build_llm(settings, None)
        for path in documents():
            data = path.read_bytes()
            count = page_count(data)
            extract_with_model(llm, [read_page(data, i) for i in range(min(count, 8))], count)
            n += 1
        model_tasks.explain_forecast(llm, FORECAST)
        model_tasks.summarise_month(llm, MONTH)
        for tone in ("friendly", "firm", "firmer", "final"):
            facts = {**REMINDER, "tone": tone}
            model_tasks.write_reminder(llm, facts, ("fallback", "fallback"))
    files = len(list(OUT.glob("*.json")))
    (OUT / "README.txt").write_text(
        "Recorded from a LOCAL MOCK server that answers with the offline stand in. Not answers of a real model.\n"
        "They prove the replay path and the request shape only. Regenerate: python tools/record_llm_fixtures.py\n", encoding="utf-8")
    return {"documents_read": n, "files": files, "requests_to_mock_server": len(stub.requests)}


if __name__ == "__main__":
    print(json.dumps(record()))
