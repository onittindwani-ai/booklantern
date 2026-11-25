"""Read an amount as a person writes it on a bill, into integer minor units. No floats anywhere.

Separators: a comma or dot may be the decimal mark or a thousands mark, and a space, a thin space or an apostrophe is always a thousands mark.
Rules (general, not tied to any layout): when both a dot and a comma appear, the last one is the decimal mark; one kind that repeats is a thousands
mark (so Indian grouping 12,34,567.00 reads right); one kind that appears once with exactly three digits after it is a thousands mark; with one or two
digits after it, it is the decimal mark; a currency with no minor unit (yen) never has a decimal mark. Negative: a leading minus, brackets, a trailing
minus or a trailing CR. A trailing DR or no sign is positive.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from booklantern.money import CURRENCY_EXPONENT, MINUS

MAX_DIGITS = 15  # same limit as limits.MAX_DIGITS (not imported: limits.py imports money, this module is read by the extractors)

SYMBOL_CURRENCY = {"€": "EUR", "£": "GBP", "¥": "JPY", "円": "JPY", "₹": "INR", "zł": "PLN", "Kč": "CZK", "₩": "KRW", "R$": "BRL", "Fr.": "CHF", "Rs.": "INR", "Rs": "INR"}
CODE_RE = re.compile(r"\b(" + "|".join(sorted(CURRENCY_EXPONENT, key=len, reverse=True)) + r")\b")
_MC = re.escape(MINUS)  # every dash that means a minus (the same list the bank statement reader uses), so a real minus sign or an en dash is never dropped
_AMOUNT = re.compile(r"""(?P<neg1>[""" + _MC + r"""(]\s?)?(?:[$€£¥₹₩]|R\$|Rs\.?|zł|Kč|Fr\.)?\s?(?P<num>\d{1,3}(?:[ \u00a0\u202f'’]\d{3})+(?:[.,]\d+)?|\d[\d.,'’]*)(?P<tail>\)|\s?[""" + _MC + r"""](?!\d)|\s?CR\b|\s?DR\b)?""")
_TOKEN = re.compile(r"(?<![\w/.:" + _MC + r"])" + _AMOUNT.pattern, re.X)


def _negative_tail(tail: str) -> bool:
    return tail == "CR" or (tail != "" and tail in set(MINUS))


def to_minor_units(num: str, exp: int) -> int | None:
    """The digits of one number (no sign) into minor units, half up."""
    s = re.sub(r"[   '’]", "", num).strip(".,")
    if not s or not re.fullmatch(r"[\d.,]+", s):
        return None
    if len(re.sub(r"\D", "", s)) > MAX_DIGITS:
        return None  # no real bill has an amount this long: it is not read, so it can never overflow a column
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    dec = None
    if exp > 0:
        if last_dot > -1 and last_comma > -1:
            dec = "." if last_dot > last_comma else ","
        elif last_dot > -1 or last_comma > -1:
            sep = "." if last_dot > -1 else ","
            tail = s.rsplit(sep, 1)[1]
            dec = None if (s.count(sep) > 1 or len(tail) == 3) else sep
    elif last_dot > -1 and last_comma > -1:
        return None
    if dec:
        whole, frac = s.rsplit(dec, 1)
        whole = re.sub(r"[.,]", "", whole)
    else:
        whole, frac = re.sub(r"[.,]", "", s), ""
    if not whole and not frac:
        return None
    d = Decimal(f"{whole or '0'}.{frac}" if frac else (whole or "0"))
    return int((d * (Decimal(10) ** exp)).to_integral_value(rounding=ROUND_HALF_UP))


def parse_money(text: str, exp: int = 2) -> int | None:
    """One amount in a cell or at the end of a line, signed. None when the text is not an amount."""
    t = text.strip()
    m = _AMOUNT.fullmatch(re.sub(r"\b[A-Z]{3}\b", "", t).strip())
    if not m:
        return None
    n = to_minor_units(m.group("num"), exp)
    if n is None:
        return None
    tail = (m.group("tail") or "").strip()
    neg = bool(m.group("neg1")) or _negative_tail(tail) or (m.group("neg1") or "").strip() == "(" and tail == ")"
    return -n if neg else n


def money_tokens(line: str, exp: int = 2) -> list[tuple[int, int, int]]:
    """Every amount inside a line of text: (start, end, minor). Plain integers with no separator are amounts only when they sit at the end of the line or follow a currency mark."""
    out = []
    for m in _TOKEN.finditer(line):
        raw = m.group("num")
        n = to_minor_units(raw, exp)
        if n is None:
            continue
        has_sep = bool(re.search(r"[.,'   ’]", raw))
        marked = m.group(0).strip()[:1] in "$€£¥₹₩" or bool(re.search(r"[A-Z]{3}\s?$", line[: m.start()]))
        if not has_sep and not marked and line[m.end():].strip():
            continue
        tail = (m.group("tail") or "").strip()
        neg = bool(m.group("neg1")) or _negative_tail(tail)
        out.append((m.start(), m.end(), -n if neg else n))
    return out


def find_currency(text: str) -> str | None:
    m = CODE_RE.search(text)
    if m:
        return m.group(1)
    for sym in ("€", "£", "₹", "zł", "Kč", "₩", "¥", "円"):
        if sym in text:
            return SYMBOL_CURRENCY[sym]
    return "USD" if "$" in text else None
