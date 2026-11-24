"""Text in a document that tries to give orders. A bill is text from outside: a vendor, or anyone who can email you, wrote it.

This scan runs on EVERY document, whether the offline rules or a model read it. It looks for the shapes such text takes (orders to a reader or a model, a request to pay
somewhere else, a request to skip a check). A hit never changes a field and never stops the reader: it raises a blocking exception, `suspicious_text`, so a person looks before
anything is approved. It is a net, not a wall: the real protection is that nothing a document says can pay, post, approve or change a field (see docs/13 and the model path tests).
"""

from __future__ import annotations

import re

PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|rules?|text|prompts?|messages?)",
    r"disregard\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier)?\s*(?:instructions?|rules?|checks?|warnings?)",
    r"\b(?:system|assistant|developer)\s+(?:prompt|message|instruction)s?\b",
    r"\bnew\s+instructions?\b",
    r"\byou\s+(?:must|should|are\s+to|will|need\s+to)\s+(?:now\s+|immediately\s+)?(?:pay|transfer|send|wire|approve|post|mark|ignore|change|update|set|skip|forward)\b",
    r"\b(?:pay|transfer|send|wire|remit)\b[^.\n]{0,80}\b(?:to|into)\b[^.\n]{0,40}\b(?:another|a\s+different|a\s+new|this|the\s+following)\s+(?:bank\s+)?account",
    r"\b(?:new|updated|changed|correct|revised)\s+(?:bank|account|payment|wire)\s+(?:details|number|instructions)",
    r"\bapprove\s+(?:this|the)\s+(?:bill|invoice|payment)\b",
    r"\bdo\s+not\s+(?:flag|mention|tell|report|check|verify|raise|alert)\b",
    r"\b(?:mark|set)\s+(?:this|it)\s+as\s+(?:paid|approved|verified|reviewed|checked)\b",
    r"\bwithout\s+(?:asking|telling|checking|review|approval)\b",
    r"</?\s*(?:system|instructions?|assistant|untrusted_data|untrusted)\b",
    r"BEGIN\s+UNTRUSTED|END\s+UNTRUSTED",
]
_RES = [re.compile(p, re.I) for p in PATTERNS]


def scan(text: str) -> list[str]:
    """Short snippets of the text that look like orders (at most 5, 120 characters each). Empty when nothing does."""
    hits: list[str] = []
    for rx in _RES:
        m = rx.search(text)
        if m:
            a = max(m.start() - 20, 0)
            hits.append(" ".join(text[a : m.end() + 60].split())[:120])
        if len(hits) >= 5:
            break
    return hits
