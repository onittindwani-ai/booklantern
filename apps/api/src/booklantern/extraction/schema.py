"""What an extractor returns: fields with a confidence and the place on the page each value came from."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

FIELDS = ("vendor", "number", "issue_date", "due_date", "currency", "po", "bill_to", "subtotal_minor", "tax_minor", "total_minor", "bank_account", "tax_rate_bp")


@dataclass
class FieldValue:
    value: str | int | None
    confidence: int  # 0 to 100, see docs/ARCHITECTURE.md for how it is built
    box: list[float] | None = None  # [x0, y0, x1, y1] as fractions of the page, origin top left
    page: int = 0
    label: str = ""
    reasons: list[str] = field(default_factory=list)
    source: str = ""  # the text the value was read from (the row, or the snippet a model quoted)


@dataclass
class LineItem:
    description: str
    quantity_milli: int
    unit_minor: int
    total_minor: int
    box: list[float] | None = None
    page: int = 0


@dataclass
class Extraction:
    extractor: str
    readable: bool
    fields: dict[str, FieldValue] = field(default_factory=dict)
    lines: list[LineItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # text in the document that tries to give orders, or other things a person must see (see hostile.py)

    def to_json(self) -> dict:
        return {"extractor": self.extractor, "readable": self.readable, "notes": self.notes, "flags": self.flags, "fields": {k: asdict(v) for k, v in self.fields.items()}, "lines": [asdict(x) for x in self.lines]}

    @staticmethod
    def from_json(d: dict) -> Extraction:
        return Extraction(d.get("extractor", ""), d.get("readable", False), {k: FieldValue(**v) for k, v in d.get("fields", {}).items()}, [LineItem(**x) for x in d.get("lines", [])], d.get("notes", []), d.get("flags", []))

    def value(self, name: str):
        f = self.fields.get(name)
        return f.value if f else None
