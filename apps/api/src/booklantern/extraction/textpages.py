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


MAX_COLUMN = 220  # a printed line is never laid out wider than this many characters: a cell placed far off the page cannot make the text longer
MAX_LINES_PER_PAGE = 400


def layout_text(pages: list[Page], max_chars: int = 24000) -> str:
    """The text layer laid out in columns: each cell starts at the column its left edge sits at, at least two spaces after the cell before it. Pages are split by a form feed.

    Every size is bounded before it is built, not after: a column is clamped to the page width and to MAX_COLUMN, a page keeps at most MAX_LINES_PER_PAGE lines, and the
    work stops as soon as `max_chars` are reached. A file that places a letter 100 million points to the right makes the same short text as one that does not (a 1.4 KB
    PDF used to need hundreds of megabytes here).
    """
    out: list[str] = []
    total = 0
    for pg in pages:
        limit = max(1, min(MAX_COLUMN, int(pg.width / CHAR_W)))
        lines: list[str] = []
        for cells in pg.rows()[:MAX_LINES_PER_PAGE]:
            line = ""
            for c in cells:
                col = min(max(int(round(max(min(c.x0, 1e7), 0.0) / CHAR_W)) - int(MARGIN / CHAR_W), 0), limit)
                line += " " * max(col - len(line), 2 if line else col) + c.text
                if len(line) > limit + 400:  # the cells of one row are not allowed to stretch it without end either
                    line = line[: limit + 400]
                    break
            lines.append(line.rstrip())
            total += len(line) + 1
            if total >= max_chars:
                break
        out.append("\n".join(lines))
        if total >= max_chars:
            break
    return PAGE_BREAK.join(out)[:max_chars]
