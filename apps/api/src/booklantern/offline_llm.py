"""Offline stand in for the model. Plain rules and templates, NOT a language model. It speaks the same JSON shape a live model would, so the whole model path runs with no account.

  extract_invoice   runs the offline reader (extraction/offline.py) on the text it is sent and answers in the model's schema, with the row each value was read from as its source
  explain_forecast, summarise_month   the plain templates, wording only numbers that code already computed
  write_reminder    the default reminder wording for the tone
"""

from __future__ import annotations

import json
import re

from booklantern import hostile, model_tasks as M, reminders as R
from booklantern.extraction import offline
from booklantern.extraction.textpages import pages_from_text
from sendora_core.llm import LLMResponse
from sendora_core.safety import UNTRUSTED_CLOSE, UNTRUSTED_OPEN


def _block(prompt: str, source: str) -> str:
    m = re.search(re.escape(UNTRUSTED_OPEN) + r" source=" + re.escape(source) + r"\n(.*?)\n" + re.escape(UNTRUSTED_CLOSE), prompt, re.S)
    return m.group(1) if m else ""


def _facts(prompt: str) -> dict:
    return json.loads(prompt.split("FACTS:", 1)[1].strip().split("\nEND", 1)[0])


def _extract_json(text: str) -> dict:
    ex = offline.extract_pages(pages_from_text(text))
    cited = lambda k: {"value": str(ex.value(k) or ""), "confidence": ex.fields[k].confidence if k in ex.fields else 0, "source": ex.fields[k].source if k in ex.fields else ""}  # noqa: E731
    num = lambda k: {"value": ex.value(k), "confidence": ex.fields[k].confidence if k in ex.fields else 0, "source": ex.fields[k].source if k in ex.fields else ""}  # noqa: E731
    return {"doc_type": ex.value("doc_type") or "bill", "vendor": cited("vendor"), "number": cited("number"), "issue_date": cited("issue_date"), "due_date": cited("due_date"), "currency": cited("currency"),
            "po": cited("po"), "bill_to": cited("bill_to"), "bank_account": cited("bank_account"), "subtotal_minor": num("subtotal_minor"), "tax_minor": num("tax_minor"), "total_minor": num("total_minor"),
            "tax_rate_bp": num("tax_rate_bp"),
            "lines": [{"description": x.description[:200], "quantity_milli": x.quantity_milli, "unit_minor": x.unit_minor, "total_minor": x.total_minor, "source": ""} for x in ex.lines][:80],
            "instructions_seen": [h[:200] for h in hostile.scan(text)]}


class OfflineBackend:
    def complete(self, *, model: str, system: str, prompt: str, max_tokens: int, schema: dict | None = None) -> LLMResponse:
        task = (re.search(r"\[task:([a-z_]+)\]", prompt) or [None, ""])[1]
        if task == "explain_forecast":
            text = M.forecast_text(_facts(prompt))
        elif task == "summarise_month":
            text = M.month_text(_facts(prompt))
        elif task == "extract_invoice":
            text = json.dumps(_extract_json(_block(prompt, "vendor bill")))
        elif task == "write_reminder":
            f = _facts(prompt)
            body = R.TONE_TEXT[f["tone"]].format(number=f["number"], amount=f["amount"], due=f["due"], late=f["late"])
            text = json.dumps({"subject": f"Invoice {f['number']}: {f['tone']} reminder", "body": body})
        else:
            text = "Offline stand in model: no answer for this task."
        return LLMResponse(text, max(1, len(prompt) // 4), max(1, len(text) // 4), model)
