"""OFFLINE STAND IN EXTRACTOR. Plain rules over the text layer of a PDF. It is NOT a language model.

It reads every page (up to 8), finds a field by its label (English, German, French, Spanish, Italian, Dutch, Portuguese, Polish and Japanese words, see
vocab.py), reads amounts in the usual separator styles (numbers.py) and dates in the usual formats (dates.py), and reports a scan with no text layer as
unreadable (no OCR here). Version 2 was written after the first independent test (docs/EXTRACTION-EVAL.md) from general document knowledge and the
system's own seed documents only. Money math stays in code: the reader looks for the one combination of subtotal, tax and total that adds up, and when
none does it reports the printed numbers and lowers their confidence, and the checks in validation.py raise the mismatch for a person.

Confidence is traceable (every number is added or taken away by a named rule, listed in `reasons` of each field):
  label found in this document: 60. The value parsed cleanly: plus 15. Value read to the right of its label or in the same cell: plus 5.
  Value read from the row below the label: plus 0. A cross check agrees (subtotal plus tax equals total, rate matches tax over subtotal): plus 15.
  A cross check disagrees: minus 25. Guessed with no label (vendor name, bank account pattern, a date with no label): 45 plus 10 if it parsed.
  A date whose day and month could be swapped, settled only by a guess: 40. Two different invoice numbers on one page: the page is unreadable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from booklantern import hostile
from booklantern.extraction import vocab
from booklantern.extraction.cells import Cell, Page, page_count, read_page
from booklantern.extraction.dates import fold, other_reading, pick_pair, read_date
from booklantern.extraction.numbers import CODE_RE, find_currency, money_tokens, unknown_mark
from booklantern.extraction.schema import Extraction, FieldValue, LineItem
from booklantern.money import CURRENCY_EXPONENT, tax_for

NAME = "offline-rules-v2 (not a language model)"
MAX_PAGES = 8
ACCOUNT_RE = re.compile(r"\b[A-Z]{2,6}-\d{3,5}-\d{3,5}\b")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{3,5}){3,8}\b")
ACCOUNT_LABEL = re.compile(r"\biban\b\s*[:.]?\s*([A-Z]{2}\d{2}[A-Z0-9 ]{8,32})", re.I)  # only an IBAN is read by its label: other account formats differ by country and are not guessed
RATE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
HEADER_WORDS = ("description", "item", "qty", "quantity", "unit", "price", "amount", "rate", "hours", "particulars", "menge", "preis", "betrag", "bezeichnung", "designation", "cantidad", "descrizione",
                "omschrijving", "opis", "descricao", "品名", "数量", "金額")
MIN_FIELDS_FOR_A_BILL = 2  # of invoice number, invoice date, total


@dataclass
class Row:
    page: int
    pg: Page
    cells: list[Cell]
    text: str
    spans: list[tuple[int, int]]
    nxt: list["Row"]  # the rows right below on the same page, nearest first

    def cell_at(self, pos: int) -> Cell | None:
        return next((c for c, (s, e) in zip(self.cells, self.spans) if s <= pos < e), None)


ROUTING_LABEL = re.compile(r"\b(?:routing|aba|rtn)(?:\s*(?:no\.?|number|#))?\s*[:.#]?\s*(\d{9})\b", re.I)
SORT_LABEL = re.compile(r"\bsort\s*code\s*[:.#]?\s*(\d{2}[- ]?\d{2}[- ]?\d{2})\b", re.I)
SWIFT_LABEL = re.compile(r"\b(?:swift|bic)(?:\s*(?:code|/bic))?\s*[:.#]?\s*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b")
ACCOUNT_NO_LABEL = re.compile(r"\b(?:account|acct|a/c)\s*(?:no\.?|number|num|#)?\s*[:.#]?\s*(\d[\d -]{4,20}\d)\b", re.I)
BANK_WORDS = re.compile(r"\b(?:bank|routing|sort\s*code|swift|bic|remit|wire|ach)\b", re.I)


def labelled_bank_details(rows: list[Row]) -> tuple[str, Cell] | None:
    """Routing and account numbers, a UK sort code or a SWIFT code, read by their labels. An 'account number' on its own is usually the customer's account with the
    vendor, so it counts only when a routing number, sort code or SWIFT code is printed too, or the same line says bank, wire or remit."""
    parts: dict[str, str] = {}
    first: Cell | None = None
    bank_context = False
    for r in rows:
        if BANK_WORDS.search(r.text):
            bank_context = True
        for key, rx in (("routing", ROUTING_LABEL), ("sort", SORT_LABEL), ("swift", SWIFT_LABEL), ("account", ACCOUNT_NO_LABEL)):
            m = rx.search(r.text)
            if m and key not in parts:
                parts[key] = re.sub(r"[^A-Z0-9]", "", m.group(1).upper())
                first = first or r.cell_at(m.start(1)) or r.cells[0]
    strong = any(k in parts for k in ("routing", "sort", "swift"))
    if first is None or not (strong or ("account" in parts and bank_context)):
        return None
    return " ".join(parts[k] for k in ("routing", "sort", "account", "swift") if k in parts), first


def _rate_bp(text: str) -> int:
    whole, _, frac = text.replace(",", ".").partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def parse_date(text: str) -> str | None:
    r = read_date(text)
    return r[0].isoformat() if r else None


def _rows(pages: list[Page]) -> list[Row]:
    out: list[Row] = []
    for pi, pg in enumerate(pages):
        page_rows = []
        for cells in pg.rows():
            text, spans, pos = "", [], 0
            for c in cells:
                if text:
                    text += "  "
                    pos += 2
                spans.append((pos, pos + len(c.text)))
                text += c.text
                pos += len(c.text)
            page_rows.append(Row(pi, pg, cells, text, spans, []))
        for i, r in enumerate(page_rows):
            r.nxt = page_rows[i + 1 : i + 3]
        out.extend(page_rows)
    return out


def _is_label(text: str) -> bool:
    return vocab.label_field(text) is not None or vocab.classify_row(text) != ""


def _value_for(rows: list[Row], name: str):
    """Every (text, cell, how) that belongs to a label of this field: same cell, to the right, or below."""
    for r in rows:
        for ci, c in enumerate(r.cells):
            lf = vocab.label_field(c.text)
            if not lf or lf[0] != name:
                continue
            if lf[1]:
                yield lf[1], c, "same cell"
                continue
            if ci + 1 < len(r.cells) and not _is_label(r.cells[ci + 1].text):
                yield r.cells[ci + 1].text.strip(), r.cells[ci + 1], "right"
                continue
            for below in r.nxt:
                hit = next((x for x in below.cells if abs(x.x0 - c.x0) < 25 and not _is_label(x.text)), None)
                if hit:
                    yield hit.text.strip(), hit, "below"
                    break


def _amount_rows(rows: list[Row], exp: int):
    """(row, kind, label, minor, cell) for every row with a labelled amount at its end."""
    for r in rows:
        toks = money_tokens(r.text, exp)
        if not toks:
            continue
        s, _e, minor = toks[-1]
        label = re.sub(r"\s*\b[A-Z]{3}\b\s*$", "", r.text[:s].strip(" :"))
        yield r, vocab.classify_row(label), label, minor, r.cell_at(max(s, 0)) or r.cells[-1]


def _detect_currency(rows: list[Row], total_rows: list[Row]) -> tuple[str | None, str]:
    for r in total_rows[::-1]:
        m = CODE_RE.search(r.text)
        if m:
            return m.group(1), "code on the total row"
    codes = [m.group(1) for r in rows for m in CODE_RE.finditer(r.text)]
    if codes:
        return max(set(codes), key=codes.count), "most common currency code on the page"
    text = "\n".join(r.text for r in rows)
    cur = find_currency(text)
    return cur, "symbol on the page" if cur else ""


def _foreign_total_mark(total_rows: list[Row], exp: int) -> str | None:
    """A currency code or sign written next to a total that this system has no decimals for (TWD, COP, NT$). Such a bill is never booked in the company currency by itself."""
    for r in total_rows[::-1]:
        toks = money_tokens(r.text, exp)
        mark = unknown_mark(r.text, toks[-1][0], toks[-1][1]) if toks else None
        if mark:
            return mark
    return None


def _solve(subs, taxes, taxtotals, totals):
    """The one combination of subtotal, tax and total that adds up: (sub, tax, total, ok). Falls back to the printed last values with ok False."""
    tax_options = [("sum of the tax lines", sum(t[0] for t in taxes))] if taxes else []
    tax_options += [("total tax line", t[0]) for t in taxtotals] + [("tax line", t[0]) for t in taxes]
    for t in totals[::-1]:
        for s in (subs[::-1] or [None]):
            for _name, x in (tax_options or [("none", 0)]):
                if s is None and not tax_options:
                    continue
                if s is not None and s[0] + x == t[0]:
                    return s, ("sum" if x else None, x), t, True
        for _name, x in tax_options:  # tax included: no subtotal printed, total minus tax is the net
            if not subs and x and t[0] > x:
                return None, ("incl", x), t, True
    t = totals[-1] if totals else None
    s = subs[-1] if subs else None
    x = taxtotals[-1][0] if taxtotals else sum(v[0] for v in taxes) if taxes else None
    return s, ("fallback", x), t, False


def extract(data: bytes) -> Extraction:
    """Read the pages of a PDF (up to 8) and extract the fields (the PDF path of the product)."""
    n = page_count(data)
    return extract_pages([read_page(data, i) for i in range(min(n, MAX_PAGES))], n)


def extract_page(page: Page, pages: int = 1) -> Extraction:
    return extract_pages([page], pages)


def extract_pages(pages: list[Page], total_pages: int | None = None) -> Extraction:
    """The rules on pages that are already read into cells. Tests and the independent evaluation tool build pages from plain text."""
    total_pages = total_pages or len(pages)
    if sum(p.chars for p in pages) < 20:
        return Extraction(NAME, False, notes=["No text layer on this page. This stand in has no OCR, so a person has to key the fields, or a live model has to read the picture."])
    rows = _rows(pages)
    f: dict[str, FieldValue] = {}
    flags = hostile.scan("\n".join(r.text for r in rows))  # text that gives orders is never obeyed and always shown to a person

    def put(name, value, conf, row_or_cell, label, reasons):
        cell = row_or_cell if isinstance(row_or_cell, Cell) else None
        pg, src = pages[0], ""
        if cell is not None:
            row = next((r for r in rows if cell in r.cells), None)
            pg, src = (row.pg, row.text[:200]) if row else (pages[0], "")
        page_no = pages.index(pg) if pg in pages else 0
        f[name] = FieldValue(value, max(0, min(100, conf)), pg.frac(cell) if cell else None, page_no, label, reasons, src)

    # amounts: which currency, then which amounts
    first_pass = list(_amount_rows(rows, 2))
    cur, cur_how = _detect_currency(rows, [r for r, k, *_ in first_pass if k == "total"])
    exp = CURRENCY_EXPONENT.get(cur or "", 2)
    found = list(_amount_rows(rows, exp)) if exp != 2 else first_pass
    kinds = {k: [(m, r, c, lab) for r, kk, lab, m, c in found if kk == k and m is not None] for k in ("subtotal", "tax", "taxtotal", "total")}
    subs, taxes, taxtotals, totals = (kinds[k] for k in ("subtotal", "tax", "taxtotal", "total"))
    sub, (how, tax_amt), tot, ok = _solve(subs, taxes, taxtotals, totals)
    notes: list[str] = []

    # header fields
    numbers = []
    for text, cell, how_read in _value_for(rows, "number"):
        if re.search(r"\d", text) and len(text) <= 40:
            numbers.append((text.strip(), cell, how_read))
    distinct = {fold(re.sub(r"[\s\-_/.]", "", n[0])) for n in numbers}
    if len(distinct) > 1:
        return Extraction(NAME, False, notes=["This page holds more than one invoice number, so it may hold more than one bill. A person has to split it."], flags=flags)
    if numbers:
        t, c, h = numbers[0]
        put("number", t, 60 + 15 + (5 if h != "below" else 0), c, "number", ["label found", "value parsed", f"value read {h}"])
    for name in ("po", "bill_to"):
        for text, cell, h in _value_for(rows, name):
            if text and fold(text) not in ("none", "n/a", "-", "none quoted", "tba"):
                put(name, text, 60 + 15 + (5 if h != "below" else 0), cell, name, ["label found", "value parsed", f"value read {h}"])
                break
    month_first = cur == "USD"
    dates: dict[str, tuple[date, bool, Cell, str] | None] = {}
    for name in ("issue_date", "due_date"):
        dates[name] = None
        for text, cell, h in _value_for(rows, name):
            rd = read_date(text, month_first)
            if rd:
                dates[name] = (rd[0], rd[1], cell, h)
                break
    if dates["issue_date"] is None:  # a date with no label: the first one near the top, not on a due or period line
        for r in rows[:15]:
            if re.search(r"due|period|von|bis|until|valid|expir", fold(r.text)):
                continue
            rd = read_date(r.text, month_first)
            if rd:
                dates["issue_date"] = (rd[0], rd[1], r.cell_at(0) or r.cells[0], "unlabelled")
                break
    due_date = dates["due_date"][0] if dates["due_date"] else None
    for name, v in dates.items():
        if v is None:
            continue
        d, guessed, cell, h = v
        if name == "issue_date":
            d, guessed = pick_pair((d, guessed), due_date)
        if h == "unlabelled":
            put(name, d.isoformat(), 55, cell, name, ["no label, the first date near the top of the page"])
        elif guessed:
            alt = other_reading("", d)
            put(name, d.isoformat(), 40, cell, name, ["label found", f"day and month could be swapped: read as {d.isoformat()}, the other reading is {alt.isoformat() if alt else 'none'}"])
        else:
            put(name, d.isoformat(), 60 + 15 + (5 if h != "below" else 0), cell, name, ["label found", "date parsed", f"value read {h}"])
    # vendor: a seller label, otherwise the first heading line
    seller = next(((t, c, h) for t, c, h in _value_for(rows, "seller") if t), None)
    if seller:
        put("vendor", seller[0], 60 + 15, seller[1], "seller", ["label found", "value parsed"])
    else:
        first = next((r for r in rows[:6] if r.cells and not vocab.TITLE_RE.search(r.cells[0].text) and not _is_label(r.cells[0].text) and re.search(r"[^\W\d_]", r.cells[0].text)), None)
        if first:
            put("vendor", first.cells[0].text.strip(), 45 + 10, first.cells[0], "top of the page", ["no label, taken from the top of the page"])

    # amounts into fields
    negative: list[str] = []  # amounts printed with a minus sign, in brackets or marked CR: the sign is kept as a finding, never dropped quietly

    def money_field(name, item, label):
        m, r, c, lab = item
        if m < 0:
            negative.append(label)
        put(name, m if m >= 0 else -m, 60 + 15 + 5, c, label, ["label found", "amount parsed", "value read to the right"])

    if sub:
        money_field("subtotal_minor", sub, "subtotal")
    if tot:
        money_field("total_minor", tot, "total")
    if how == "incl" and tot:
        put("subtotal_minor", tot[0] - tax_amt, 55, tot[2], "total minus tax", ["not printed (prices include tax), worked out as total minus tax"])
    if tax_amt is not None and tax_amt < 0:
        negative.append("tax")
    if tax_amt is not None and (taxes or taxtotals):
        item = (taxtotals or taxes)[-1]
        put("tax_minor", abs(tax_amt), 60 + 15 + 5, item[2], "tax", ["label found", "amount parsed", f"read as {how}"])
    foreign = _foreign_total_mark([r for r, k, *_ in found if k == "total"], exp)
    if foreign:
        put("currency_unknown", foreign, 90, tot[2] if tot else None, "total", [f"the total is written with {foreign}, a currency this system has no decimals for"])
    if cur and tot:
        put("currency", cur, 60 + 15 if cur_how.startswith(("code", "most")) else 55, tot[2], "total", [f"currency read from the {cur_how}"])
    # tax rate: one rate on one line, or parallel components added up
    rates = [_rate_bp(m.group(1)) for _t, _r, _c, lab in taxes for m in [RATE_RE.search(lab)] if m]
    if rates and len(rates) == len(taxes) and tax_amt is not None:
        rate = rates[0] if len(rates) == 1 else sum(rates)
        label_cell = taxes[0][2]
        put("tax_rate_bp", rate, 60 + 15, label_cell, "tax rate", ["rate printed in the tax label" if len(rates) == 1 else "rates of the parallel tax lines added up"])
    # bank account
    for r in rows:
        m = ACCOUNT_RE.search(r.text) or IBAN_RE.search(r.text)
        lab = None if m else ACCOUNT_LABEL.search(r.text)
        if (m or lab) and "bank_account" not in f:
            pos = (m.start() if m else lab.start(1))
            put("bank_account", (m.group() if m else lab.group(1).strip()), 55, r.cell_at(pos) or r.cells[0], "account pattern", ["no label, found by its shape" if m else "label found"])
    if "bank_account" not in f:  # labelled details in the other usual styles (US routing and account, UK sort code, SWIFT)
        details = labelled_bank_details(rows)
        if details:
            put("bank_account", details[0], 50, details[1], "bank details", ["found by the labels Routing, Sort code, SWIFT or Account next to bank words"])

    # lines
    stop = min((rows.index(r) for r, k, *_ in found if k), default=len(rows))
    lines = _lines(rows[:stop], exp)

    # cross checks, the only thing allowed to raise confidence above the base
    if sub and tot and tax_amt is not None:
        for n in ("subtotal_minor", "tax_minor", "total_minor"):
            if n in f:
                f[n].confidence = min(100, f[n].confidence + 15) if ok else max(0, f[n].confidence - 25)
                f[n].reasons.append("subtotal plus tax equals total" if ok else "subtotal plus tax does not equal total")
    if "tax_rate_bp" in f and sub and tax_amt is not None:
        agree = abs(tax_for(sub[0], f["tax_rate_bp"].value) - tax_amt) <= 1
        f["tax_rate_bp"].confidence = min(100, f["tax_rate_bp"].confidence + 15) if agree else max(0, f["tax_rate_bp"].confidence - 25)
        f["tax_rate_bp"].reasons.append("printed rate matches tax over subtotal" if agree else "printed rate does not match tax over subtotal")
    head = " ".join(r.text for r in rows[:8])
    credit = bool(vocab.CREDIT_RE.search(fold(head))) or bool(negative)
    if negative:
        put("negative_amount", 1, 90, None, "sign", [f"the {', '.join(sorted(set(negative)))} amount is printed as a negative number"])
    put("doc_type", "credit_note" if credit else "bill", 80 if credit else 55, None, "title", ["credit note wording in the heading" if credit else "no credit note wording"])
    if credit:
        notes.append("This looks like a credit note, not a bill to pay.")
    core = sum(1 for n in ("number", "issue_date", "total_minor") if n in f)
    if core < MIN_FIELDS_FOR_A_BILL:
        return Extraction(NAME, False, notes=["The text layer holds too little of an invoice to read it (no invoice number, date or total found). A person has to key the fields."], flags=flags)
    if not lines:
        notes.append("No line items could be read.")
    if total_pages > len(pages):
        notes.append(f"{total_pages} pages: only the first {len(pages)} were read.")
    elif len(pages) > 1:
        notes.append(f"{len(pages)} pages read.")
    return Extraction(NAME, True, f, lines, notes, flags)


def _lines(rows: list[Row], exp: int) -> list[LineItem]:
    """Rows of the table: text, then optionally a quantity and a unit price, then the amount. Starts after a header row of column names when there is one."""
    start = next((i + 1 for i, r in enumerate(rows) if sum(w in fold(r.text) for w in HEADER_WORDS) >= 2), 0)
    out = []
    for r in rows[start:]:
        toks = money_tokens(r.text, exp)
        if not toks or _is_label(r.cells[0].text) or len(r.cells) < 2:
            continue
        label = r.text[: toks[0][0]].strip()
        if re.search(vocab._EXCLUDE, fold(r.text)) or re.search(r"\b(?:page|seite|pagina|strona|p\.)\s*\d", fold(r.text)) or not re.search(r"[^\W\d_]", label) or len(toks) > 4:
            continue
        amount = toks[-1][2]
        qty_milli, unit = 1000, amount
        if len(toks) >= 2 and len(r.cells) >= 3:
            q = r.cells[-3].text.strip().replace(",", ".")
            if re.fullmatch(r"\d+(?:\.\d+)?", q):
                whole, _, frac = q.partition(".")
                qty_milli, unit = int(whole) * 1000 + int((frac + "000")[:3]), toks[-2][2]
        out.append(LineItem(label if len(r.cells) < 3 else " ".join(c.text for c in r.cells[:-3]) or label, qty_milli, unit, amount, r.pg.frac(r.cells[-1]), 0))
    return out
