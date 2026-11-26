"""Size limits for everything read out of a document or typed into a form, so a hostile or damaged file can never overflow a column.

Amounts are minor units (cents). One trillion minor units (ten billion in a normal currency) is far above any real bill and far below what a 64 bit column holds.
"""

from __future__ import annotations

from booklantern.money import CURRENCY_EXPONENT

MAX_MINOR = 10**12
MAX_QUANTITY_MILLI = 10**12  # 10^9 units
MAX_LINES = 500
MAX_DIGITS = 15  # a printed number with more digits than this is not read as an amount


def in_range(n: int, limit: int = MAX_MINOR) -> bool:
    return -limit <= n <= limit


def text(value: object, size: int) -> str:
    """A plain string that fits a column of `size` characters."""
    return str(value if value is not None else "").strip()[:size]


def currency(value: object, fallback: str) -> str:
    """A known three letter currency code, otherwise the fallback."""
    code = str(value or "").strip().upper()
    return code if code in CURRENCY_EXPONENT else fallback
