"""HELD OUT layouts E to H. Written before the extractor existed, with wording and shapes that differ from the dev layouts (A to D).

The extractor is built only against the dev layouts. These are scored once, untouched, and the first result is saved.
Dates here: 14.03.2026, March 14, 2026, 14 March 2026, 2026-03-14 is NOT used.
"""

from __future__ import annotations

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .docspec import FOOTER, MONTHS, DocSpec, money_eu, money_us, qty_text

W, H = letter


def _d_dot(d):  # 14.03.2026
    return d.strftime("%d.%m.%Y")


def _d_long_us(d):  # March 14, 2026
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def _d_long(d):  # 14 March 2026
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def layout_e(s: DocSpec, path: str) -> None:
    """Small grey label above each value, two columns, headers Particulars / Units / Rate / Line total."""
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Helvetica-Bold", 20); c.drawString(54, H - 70, s.vendor)
    c.setFont("Helvetica", 9); c.drawString(54, H - 86, s.vendor_addr)
    pairs = [("Bill ref", s.number), ("Dated", _d_long_us(s.issue)), ("Payable by", _d_long_us(s.due)), ("Order ref", s.po or "none quoted")]
    y = H - 130
    for i, (lab, val) in enumerate(pairs):
        x = 54 if i % 2 == 0 else 330
        yy = y - (i // 2) * 44
        c.setFillGray(0.5); c.setFont("Helvetica", 8); c.drawString(x, yy + 14, lab)
        c.setFillGray(0); c.setFont("Helvetica-Bold", 12); c.drawString(x, yy, val)
    c.setFont("Helvetica", 8); c.setFillGray(0.5); c.drawString(54, H - 230, "Sold to"); c.setFillGray(0); c.setFont("Helvetica", 11); c.drawString(54, H - 244, s.bill_to)
    ty = H - 290
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((54, "Particulars"), (330, "Units"), (400, "Rate"), (490, "Line total")):
        c.drawString(x, ty, t)
    c.line(54, ty - 4, 558, ty - 4)
    c.setFont("Helvetica", 10)
    for ln in s.lines:
        ty -= 20
        c.drawString(54, ty, ln.desc); c.drawString(330, ty, qty_text(ln.qty_milli)); c.drawRightString(470, ty, money_us(ln.unit_minor, s.currency)); c.drawRightString(558, ty, money_us(ln.total_minor, s.currency))
    ty -= 36
    for lab, v in (("Net", s.subtotal_minor), (f"Sales tax ({s.tax_rate_bp / 100:g}%)", s.tax_minor)):
        c.setFont("Helvetica", 10); c.drawString(380, ty, lab); c.drawRightString(558, ty, money_us(v, s.currency)); ty -= 18
    c.setFont("Helvetica-Bold", 12); c.drawString(380, ty, "Grand total"); c.drawRightString(558, ty, f"{s.currency} {money_us(s.total_minor, s.currency)}")
    c.setFont("Helvetica", 9); c.drawString(54, 90, f"Remit to account {s.account}"); c.setFont("Helvetica", 7); c.drawString(54, 40, FOOTER)
    c.save()


def layout_f(s: DocSpec, path: str) -> None:
    """A letter: the facts sit in a paragraph, then a table, then the balance."""
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Times-Bold", 16); c.drawString(54, H - 64, s.vendor)
    c.setFont("Times-Roman", 10); c.drawString(54, H - 80, s.vendor_addr)
    c.setFont("Times-Roman", 11)
    y = H - 130
    for line in (f"To: {s.bill_to}", "", "Dear accounts team,", "",
                 f"We are billing you under reference {s.number}, dated {_d_dot(s.issue)}, for the work set out below.",
                 f"Please settle by {_d_dot(s.due)}." + (f" Your order reference is {s.po}." if s.po else "")):
        c.drawString(54, y, line); y -= 16
    y -= 16
    c.setFont("Times-Bold", 10)
    for x, t in ((54, "Work done"), (360, "Hours"), (420, "Rate"), (500, "Amount")):
        c.drawString(x, y, t)
    c.line(54, y - 4, 558, y - 4)
    c.setFont("Times-Roman", 10)
    for ln in s.lines:
        y -= 18
        c.drawString(54, y, ln.desc); c.drawString(360, y, qty_text(ln.qty_milli)); c.drawRightString(480, y, money_us(ln.unit_minor, s.currency)); c.drawRightString(558, y, money_us(ln.total_minor, s.currency))
    y -= 34
    for lab, v in (("Net amount", s.subtotal_minor), (f"Sales tax at {s.tax_rate_bp / 100:g} percent", s.tax_minor)):
        c.drawString(330, y, lab); c.drawRightString(558, y, money_us(v, s.currency)); y -= 16
    c.setFont("Times-Bold", 11); c.drawString(330, y, "Balance payable"); c.drawRightString(558, y, f"{money_us(s.total_minor, s.currency, sym=True)}")
    c.setFont("Times-Roman", 10); c.drawString(54, y - 50, f"Our bank details: {s.account}"); c.drawString(54, y - 66, "Kind regards, the finance office")
    c.setFont("Times-Roman", 7); c.drawString(54, 40, FOOTER)
    c.save()


def layout_g(s: DocSpec, path: str) -> None:
    """Document facts in a bordered box on the right, the buyer on the left, an Amount payable box at the bottom."""
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Helvetica-Bold", 14); c.drawString(54, H - 60, "Seller"); c.setFont("Helvetica", 11); c.drawString(54, H - 78, s.vendor); c.drawString(54, H - 92, s.vendor_addr)
    c.setFont("Helvetica-Bold", 10); c.drawString(54, H - 140, "Sold to:"); c.setFont("Helvetica", 11); c.drawString(54, H - 156, s.bill_to)
    c.rect(340, H - 190, 218, 120)
    c.setFont("Helvetica", 10)
    for i, (lab, val) in enumerate([("Document no.", s.number), ("Raised on", _d_long(s.issue)), ("Settle by", _d_long(s.due)), ("Buyer ref", s.po or "-")]):
        c.drawString(348, H - 90 - i * 24, lab); c.drawRightString(550, H - 90 - i * 24, val)
    ty = H - 250
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((54, "Item"), (330, "Qty"), (390, "Unit"), (500, "Amount")):
        c.drawString(x, ty, t)
    c.setFont("Helvetica", 10)
    for ln in s.lines:
        ty -= 19
        c.drawString(54, ty, ln.desc); c.drawString(330, ty, qty_text(ln.qty_milli)); c.drawRightString(450, ty, money_us(ln.unit_minor, s.currency)); c.drawRightString(558, ty, money_us(ln.total_minor, s.currency))
    ty -= 40
    c.drawString(350, ty, "Net total"); c.drawRightString(558, ty, money_us(s.subtotal_minor, s.currency)); ty -= 16
    c.drawString(350, ty, f"Tax {s.tax_rate_bp / 100:g}%"); c.drawRightString(558, ty, money_us(s.tax_minor, s.currency)); ty -= 8
    c.rect(340, ty - 36, 218, 30)
    c.setFont("Helvetica-Bold", 12); c.drawString(348, ty - 26, "Amount payable"); c.drawRightString(550, ty - 26, f"{money_us(s.total_minor, s.currency)} {s.currency}")
    c.setFont("Helvetica", 9); c.drawString(54, 100, f"Pay to: {s.account}"); c.setFont("Helvetica", 7); c.drawString(54, 40, FOOTER)
    c.save()


def layout_h(s: DocSpec, path: str) -> None:
    """European style: decimal comma, dotted dates, Client, Net sum, VAT, Total to pay."""
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Helvetica-Bold", 18); c.drawString(54, H - 64, s.vendor); c.setFont("Helvetica", 9); c.drawString(54, H - 80, s.vendor_addr)
    c.setFont("Helvetica", 10)
    rows = [("Doc. nr.", s.number), ("Date of issue", _d_dot(s.issue)), ("Payment deadline", _d_dot(s.due)), ("Order no.", s.po or "n/a"), ("Client", s.bill_to)]
    for i, (lab, val) in enumerate(rows):
        c.drawString(54, H - 130 - i * 18, lab + ":"); c.drawString(170, H - 130 - i * 18, val)
    ty = H - 260
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((54, "Position"), (320, "Pcs"), (380, "Price"), (490, "Sum")):
        c.drawString(x, ty, t)
    c.setFont("Helvetica", 10)
    for ln in s.lines:
        ty -= 18
        c.drawString(54, ty, ln.desc); c.drawString(320, ty, qty_text(ln.qty_milli)); c.drawRightString(460, ty, money_eu(ln.unit_minor, s.currency)); c.drawRightString(558, ty, money_eu(ln.total_minor, s.currency))
    ty -= 36
    c.drawString(350, ty, "Net sum"); c.drawRightString(558, ty, money_eu(s.subtotal_minor, s.currency)); ty -= 16
    c.drawString(350, ty, f"VAT {s.tax_rate_bp / 100:g} %"); c.drawRightString(558, ty, money_eu(s.tax_minor, s.currency)); ty -= 18
    c.setFont("Helvetica-Bold", 11); c.drawString(350, ty, "Total to pay"); c.drawRightString(558, ty, money_eu(s.total_minor, s.currency))
    c.setFont("Helvetica", 9); c.drawString(54, 100, f"Bank: {s.account}"); c.setFont("Helvetica", 7); c.drawString(54, 40, FOOTER)
    c.save()


HELDOUT_LAYOUTS = {"E": layout_e, "F": layout_f, "G": layout_g, "H": layout_h}
