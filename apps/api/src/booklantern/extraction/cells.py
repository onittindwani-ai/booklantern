"""Read the text layer of a PDF page into cells (one run of text each) with exact boxes, using pdfium's own text rectangles."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pypdfium2 as pdfium

MAX_RECTS = 4000  # text runs read from one page: a real bill page has a few hundred, so a file with a million tiny runs cannot keep the reader busy
MAX_CELL_CHARS = 300
ROW_TOL = 3.5  # points: runs whose vertical centres are closer than this share a row


@dataclass
class Cell:
    text: str
    x0: float
    y0: float  # top edge, points from the top of the page
    x1: float
    y1: float
    row: int = 0


@dataclass
class Page:
    width: float
    height: float
    cells: list[Cell]
    chars: int

    def rows(self) -> list[list[Cell]]:
        out: dict[int, list[Cell]] = {}
        for c in self.cells:
            out.setdefault(c.row, []).append(c)
        return [sorted(v, key=lambda c: c.x0) for _, v in sorted(out.items())]

    def frac(self, c: Cell) -> list[float]:
        return [round(c.x0 / self.width, 4), round(c.y0 / self.height, 4), round(c.x1 / self.width, 4), round(c.y1 / self.height, 4)]


def page_count(data: bytes) -> int:
    try:
        return len(pdfium.PdfDocument(data))
    except Exception:  # a damaged file has no pages we can read
        return 1


def read_page(data: bytes, index: int = 0) -> Page:
    pdf = pdfium.PdfDocument(data)
    page = pdf[index]
    w, h = page.get_size()
    tp = page.get_textpage()
    cells: list[Cell] = []
    for i in range(min(tp.count_rects(), MAX_RECTS)):
        l, b, r, t = tp.get_rect(i)
        text = tp.get_text_bounded(l, b, r, t).replace("\r", " ").replace("\n", " ")[:MAX_CELL_CHARS]
        if not text.strip():
            continue
        # a monospaced line can hold several columns separated by runs of spaces: split them and share the box by character position
        parts = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+(?: \S+)*", text)]
        total = max(len(text), 1)
        for s, e, piece in parts:
            cells.append(Cell(piece, l + (r - l) * s / total, h - t, l + (r - l) * e / total, h - b))
    cells.sort(key=lambda c: ((c.y0 + c.y1) / 2, c.x0))
    row, last = -1, -99.0
    for c in cells:
        mid = (c.y0 + c.y1) / 2
        if abs(mid - last) > ROW_TOL:
            row += 1
            last = mid
        c.row = row
    return Page(w, h, cells, tp.count_chars())
