"""Dev layouts A to D (and the scan layout). The offline extractor is built against these."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .docspec import FOOTER, DocSpec, money_us, qty_text

W, H = letter


def _iso(d):
    return d.isoformat()


def _dmy(d):  # 14 Mar 2026
    return d.strftime("%d %b %Y")


def _dmy_dash(d):  # 14-Mar-2026
    return d.strftime("%d-%b-%Y")


def _slash(d):  # 2026/03/14
    return d.strftime("%Y/%m/%d")


def layout_a(s: DocSpec, path: str) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Helvetica-Bold", 22); c.drawString(54, H - 64, s.vendor); c.setFont("Helvetica", 9); c.drawString(54, H - 80, s.vendor_addr)
    c.setFont("Helvetica-Bold", 16); c.drawRightString(558, H - 64, "INVOICE")
    c.setFont("Helvetica", 10)
    for i, (lab, val) in enumerate([("Invoice No:", s.number), ("Invoice Date:", _iso(s.issue)), ("Due Date:", _iso(s.due))] + ([("PO Number:", s.po)] if s.po else [])):
        c.drawString(380, H - 100 - i * 15, lab); c.drawString(470, H - 100 - i * 15, val)
    c.setFont("Helvetica-Bold", 10); c.drawString(54, H - 130, "Bill To:"); c.setFont("Helvetica", 10); c.drawString(54, H - 144, s.bill_to)
    ty = H - 200
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((54, "Description"), (330, "Qty"), (390, "Unit Price"), (500, "Amount")):
        c.drawString(x, ty, t)
    c.line(54, ty - 4, 558, ty - 4); c.setFont("Helvetica", 10)
    for ln in s.lines:
        ty -= 18
        c.drawString(54, ty, ln.desc); c.drawString(330, ty, qty_text(ln.qty_milli)); c.drawRightString(470, ty, money_us(ln.unit_minor, s.currency)); c.drawRightString(558, ty, money_us(ln.total_minor, s.currency))
    ty -= 34
    c.drawString(380, ty, "Subtotal"); c.drawRightString(558, ty, money_us(s.subtotal_minor, s.currency)); ty -= 15
    c.drawString(380, ty, f"Tax ({s.tax_rate_bp / 100:g}%)"); c.drawRightString(558, ty, money_us(s.tax_minor, s.currency)); ty -= 17
    c.setFont("Helvetica-Bold", 11); c.drawString(380, ty, "Total Due"); c.drawRightString(558, ty, f"{s.currency} {money_us(s.total_minor, s.currency)}")
    c.setFont("Helvetica", 9); c.drawString(54, 100, f"Bank: {s.account}"); c.setFont("Helvetica", 7); c.drawString(54, 40, FOOTER)
    c.save()


def layout_b(s: DocSpec, path: str) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Helvetica-Bold", 14); c.drawString(54, H - 60, "TAX INVOICE"); c.setFont("Helvetica", 11); c.drawString(54, H - 78, s.vendor); c.setFont("Helvetica", 9); c.drawString(54, H - 92, s.vendor_addr)
    c.setFont("Helvetica", 10)
    rows = [("Number", s.number), ("Date", _dmy(s.issue)), ("Payment due", _dmy(s.due))] + ([("Purchase order", s.po)] if s.po else []) + [("Customer", s.bill_to)]
    for i, (lab, val) in enumerate(rows):
        c.drawString(54, H - 130 - i * 15, lab); c.drawString(160, H - 130 - i * 15, val)
    ty = H - 240
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((54, "Item"), (330, "Qty"), (400, "Price"), (500, "Total")):
        c.drawString(x, ty, t)
    c.setFont("Helvetica", 10)
    for ln in s.lines:
        ty -= 17
        c.drawString(54, ty, ln.desc); c.drawString(330, ty, qty_text(ln.qty_milli)); c.drawRightString(470, ty, money_us(ln.unit_minor, s.currency)); c.drawRightString(558, ty, money_us(ln.total_minor, s.currency))
    ty -= 30
    c.drawString(390, ty, "Subtotal"); c.drawRightString(558, ty, money_us(s.subtotal_minor, s.currency)); ty -= 15
    c.drawString(390, ty, f"VAT {s.tax_rate_bp / 100:g}%"); c.drawRightString(558, ty, money_us(s.tax_minor, s.currency)); ty -= 17
    c.setFont("Helvetica-Bold", 11); c.drawString(390, ty, "Amount due"); c.drawRightString(558, ty, f"{money_us(s.total_minor, s.currency, sym=True)}")
    c.setFont("Helvetica", 9); c.drawString(54, 100, f"Account: {s.account}"); c.setFont("Helvetica", 7); c.drawString(54, 40, FOOTER)
    c.save()


def layout_c(s: DocSpec, path: str) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Times-Bold", 20); c.drawString(54, H - 64, s.vendor); c.setFont("Times-Roman", 9); c.drawString(54, H - 78, s.vendor_addr)
    c.setFont("Times-Roman", 11)
    rows = [("Invoice #", s.number), ("Issued", _dmy_dash(s.issue)), ("Pay by", _dmy_dash(s.due))] + ([("Customer PO", s.po)] if s.po else []) + [("Billed To", s.bill_to)]
    for i, (lab, val) in enumerate(rows):
        c.setFont("Times-Bold", 11); c.drawString(54, H - 120 - i * 16, lab); c.setFont("Times-Roman", 11); c.drawString(150, H - 120 - i * 16, val)
    ty = H - 235
    c.setFont("Times-Bold", 10)
    for x, t in ((54, "Details"), (340, "Quantity"), (410, "Rate"), (500, "Line amount")):
        c.drawString(x, ty, t)
    c.setFont("Times-Roman", 10)
    for ln in s.lines:
        ty -= 18
        c.drawString(54, ty, ln.desc); c.drawString(350, ty, qty_text(ln.qty_milli)); c.drawRightString(480, ty, money_us(ln.unit_minor, s.currency)); c.drawRightString(558, ty, money_us(ln.total_minor, s.currency))
    ty -= 32
    for lab, v in (("Subtotal", s.subtotal_minor), (f"Tax @ {s.tax_rate_bp / 100:g}%", s.tax_minor)):
        c.drawString(380, ty, lab); c.drawRightString(558, ty, money_us(v, s.currency)); ty -= 15
    c.setFont("Times-Bold", 11); c.drawString(380, ty - 2, "Total"); c.drawRightString(558, ty - 2, f"{money_us(s.total_minor, s.currency)} {s.currency}")
    c.setFont("Times-Roman", 9); c.drawString(54, 100, f"IBAN/Account: {s.account}"); c.setFont("Times-Roman", 7); c.drawString(54, 40, FOOTER)
    c.save()


def layout_d(s: DocSpec, path: str) -> None:
    """Monospaced statement style, one text line per row."""
    c = canvas.Canvas(path, pagesize=letter)
    y = H - 60
    c.setFont("Courier-Bold", 13); c.drawString(54, y, s.vendor.upper()); y -= 14
    c.setFont("Courier", 9); c.drawString(54, y, s.vendor_addr); y -= 28
    c.setFont("Courier", 10)
    head = [f"INVOICE NO   {s.number}", f"INVOICE DATE {_slash(s.issue)}", f"DUE DATE     {_slash(s.due)}"] + ([f"PO NUMBER    {s.po}"] if s.po else []) + [f"BILL TO      {s.bill_to}"]
    for line in head:
        c.drawString(54, y, line); y -= 14
    y -= 14
    c.drawString(54, y, "DESCRIPTION                     QTY      PRICE      AMOUNT"); y -= 4; c.line(54, y, 558, y); y -= 14
    for ln in s.lines:
        c.drawString(54, y, ln.desc[:30]); c.drawString(264, y, qty_text(ln.qty_milli)); c.drawRightString(400, y, money_us(ln.unit_minor, s.currency)); c.drawRightString(500, y, money_us(ln.total_minor, s.currency)); y -= 14
    y -= 14
    c.drawString(300, y, "SUBTOTAL"); c.drawRightString(500, y, money_us(s.subtotal_minor, s.currency)); y -= 14
    c.drawString(300, y, f"TAX {s.tax_rate_bp / 100:g}%"); c.drawRightString(500, y, money_us(s.tax_minor, s.currency)); y -= 14
    c.setFont("Courier-Bold", 10); c.drawString(300, y, "TOTAL DUE"); c.drawRightString(500, y, f"{s.currency} {money_us(s.total_minor, s.currency)}")
    c.setFont("Courier", 9); c.drawString(54, 100, f"PAY TO ACCOUNT {s.account}"); c.setFont("Courier", 7); c.drawString(54, 40, FOOTER)
    c.save()


def layout_scan(s: DocSpec, path: str) -> None:
    """A page that is only a picture: text drawn into a bitmap, slightly noisy, then wrapped in a PDF. There is no text layer."""
    img = Image.new("L", (1224, 1584), 250)
    d = ImageDraw.Draw(img)
    f_big, f = ImageFont.load_default(34), ImageFont.load_default(22)
    d.text((100, 100), s.vendor, font=f_big, fill=20); d.text((100, 150), s.vendor_addr, font=f, fill=60)
    rows = [f"Invoice No: {s.number}", f"Invoice Date: {_iso(s.issue)}", f"Due Date: {_iso(s.due)}"] + ([f"PO Number: {s.po}"] if s.po else []) + [f"Bill To: {s.bill_to}"]
    for i, t in enumerate(rows):
        d.text((100, 230 + i * 34), t, font=f, fill=30)
    y = 480
    for ln in s.lines:
        d.text((100, y), f"{ln.desc}   {qty_text(ln.qty_milli)} x {money_us(ln.unit_minor, s.currency)}   {money_us(ln.total_minor, s.currency)}", font=f, fill=30); y += 34
    y += 30
    for t in (f"Subtotal {money_us(s.subtotal_minor, s.currency)}", f"Tax ({s.tax_rate_bp / 100:g}%) {money_us(s.tax_minor, s.currency)}", f"Total Due {s.currency} {money_us(s.total_minor, s.currency)}", f"Bank: {s.account}"):
        d.text((600, y), t, font=f, fill=30); y += 34
    d.text((100, 1500), FOOTER, font=ImageFont.load_default(16), fill=100)
    img = img.rotate(0.6, fillcolor=250)
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    c = canvas.Canvas(path, pagesize=letter)
    c.drawImage(ImageReader(buf), 0, 0, width=W, height=H)
    c.save()


DEV_LAYOUTS = {"A": layout_a, "B": layout_b, "C": layout_c, "D": layout_d, "S": layout_scan}
