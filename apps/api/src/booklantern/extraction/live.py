"""The model reading path: a language model reads the text layer of a bill, and code verifies what it says (see model_tasks.py).

LIVE USE IS UNVERIFIED. Which model answers is chosen by LLM_BACKEND (offline stand in, recorded fixtures, or the real API); this path is selected with EXTRACTOR=live.
The base wrapper takes text only, so a scanned page (a picture) cannot be sent: it stays unreadable and goes to a person. That needs image input in the base (a requested base change).
When the model cannot be used (kill switch on, budget used up, an error, or an answer that does not match the schema) the offline reader reads the bill instead and a note says so.
"""

from __future__ import annotations

from booklantern import model_tasks
from booklantern.extraction import offline
from booklantern.extraction.cells import Page, page_count, read_page
from booklantern.extraction.schema import Extraction
from booklantern.extraction.textpages import layout_text
from sendora_core.llm import LLM, LLMError
from sendora_core.safety import KillSwitchError


def extract_with_model(llm: LLM, pages: list[Page], total_pages: int | None = None) -> Extraction:
    if sum(p.chars for p in pages) < 20:
        return Extraction("model", False, notes=["No text layer. Reading a picture needs image input in the model wrapper, which the base does not have yet."])
    try:
        ex = model_tasks.extract_bill(llm, layout_text(pages))
        if total_pages and total_pages > len(pages):
            ex.notes.append(f"{total_pages} pages: only the first {len(pages)} were read.")
        return ex
    except (LLMError, KillSwitchError, ValueError) as exc:
        ex = offline.extract_pages(pages, total_pages)
        ex.notes.append(f"The model could not be used ({type(exc).__name__}), so the offline rules read this bill instead.")
        return ex


def extract_live(ctx, session, data: bytes) -> Extraction:
    n = page_count(data)
    return extract_with_model(ctx.llm(session), [read_page(data, i) for i in range(min(n, offline.MAX_PAGES))], n)
