"""Plain text to pages of cells and back. Used by the evaluation tool (the independent sets are text files), by the offline stand in model (it reads the text it is
sent, the way the live model does) and to build the text sent to a live model (the page laid out in columns, like `pdftotext -layout`)."""

from __future__ import annotations

import re

from booklantern.extraction.cells import Cell, Page

CHAR_W, LINE_H, MARGIN = 5.5, 12.0, 54.0
PAGE_BREAK = "\f"


def pages_from_text(text: str) -> list[Page]:
    """Every line becomes a row of cells (two or more spaces start a new cell, the same split as `cells.read_page`), 5.5 points per character, 12 points per line. Pages split on a form feed."""
    out = []
    for raw in text.split(PAGE_BREAK):
        lines = raw.expandtabs(4).splitlines()
        cells: list[Cell] = []
        for i, line in enumerate(lines):
            for m in re.finditer(r"\S+(?: \S+)*", line):
                y = 40 + i * LINE_H
                cells.append(Cell(m.group(), MARGIN + m.start() * CHAR_W, y, MARGIN + m.end() * CHAR_W, y + 9, row=i))
        width = max(612.0, 2 * MARGIN + max((len(x) for x in lines), default=0) * CHAR_W)
        out.append(Page(width, max(792.0, 80 + len(lines) * LINE_H), cells, len(raw)))
    return out


def layout_text(pages: list[Page], max_chars: int = 24000) -> str:
    """The text layer laid out in columns: each cell starts at the column its left edge sits at, at least two spaces after the cell before it. Pages are split by a form feed."""
    out = []
    for pg in pages:
        lines = []
        for cells in pg.rows():
            line = ""
            for c in cells:
                col = max(int(round(c.x0 / CHAR_W)) - int(MARGIN / CHAR_W), 0)
                line += " " * max(col - len(line), 2 if line else col) + c.text
            lines.append(line.rstrip())
        out.append("\n".join(lines))
    return PAGE_BREAK.join(out)[:max_chars]
