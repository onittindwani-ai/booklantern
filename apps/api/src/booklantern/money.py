"""The only place money is handled. Amounts are integers in minor units (cents) with a currency code. No floats.

Rounding rule (one rule, everywhere): a fraction of a minor unit rounds half away from zero. 0.5 cents becomes 1 cent, -0.5 cents
becomes -1 cent. Percentages are integers in basis points (1 bp = 0.01 percent), so a 7.25 percent rate is 725 bp.
Splitting a total across parts uses the largest remainder method, so the parts always add up to the total exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

# ISO 4217 minor unit digits for the currencies a small business is likely to be billed in. Add the ones you need; an unknown code is refused, never guessed.
CURRENCY_EXPONENT = {c: 2 for c in ("USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "INR", "SGD", "HKD", "ZAR", "NOK", "SEK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN", "TRY", "AED", "SAR", "ILS",
                                    "CNY", "MXN", "BRL", "MYR", "THB", "PHP", "IDR", "EGP", "NGN", "KES")}
CURRENCY_EXPONENT.update({"JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "ISK": 0, "UGX": 0, "BHD": 3, "KWD": 3, "OMR": 3, "JOD": 3, "TND": 3})
SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
# The currencies a symbol may stand for: "$" is the mark of every dollar, so a Canadian dollar account may print it. A symbol that cannot belong to the stated currency refuses the amount.
SYMBOL_CURRENCIES = {"$": {"USD", "CAD", "AUD", "NZD", "SGD", "HKD", "MXN", "CLP"}, "€": {"EUR"}, "£": {"GBP"}}
SYMBOL_FOR = {"USD": "$", "EUR": "€", "GBP": "£"}


class MoneyError(ValueError):
    pass


def exponent(currency: str) -> int:
    if currency not in CURRENCY_EXPONENT:
        raise MoneyError(f"Unknown currency {currency!r}. Add it to CURRENCY_EXPONENT first.")
    return CURRENCY_EXPONENT[currency]


def div_round(numerator: int, denominator: int) -> int:
    """Integer division that rounds half away from zero. The denominator must be positive."""
    if denominator <= 0:
        raise MoneyError("The denominator must be positive.")
    sign = -1 if numerator < 0 else 1
    q, r = divmod(abs(numerator), denominator)
    if 2 * r >= denominator:
        q += 1
    return sign * q


def mul_bp(amount_minor: int, bp: int) -> int:
    """amount times a rate in basis points, rounded once."""
    return div_round(amount_minor * bp, 10_000)


def tax_for(subtotal_minor: int, rate_bp: int) -> int:
    return mul_bp(subtotal_minor, rate_bp)


def line_total(quantity_milli: int, unit_minor: int) -> int:
    """Quantity is kept in thousandths (2.5 hours is 2500) so no float is needed."""
    return div_round(quantity_milli * unit_minor, 1000)


def to_minor(value: Decimal | str | int, currency: str) -> int:
    """Exact conversion of a decimal amount in major units to minor units, half up. A float is refused on purpose."""
    if isinstance(value, float):
        raise MoneyError("Do not pass a float. Pass a string, an int or a Decimal.")
    try:
        d = Decimal(str(value))
    except InvalidOperation as exc:
        raise MoneyError(f"{value!r} is not an amount.") from exc
    scaled = d * (Decimal(10) ** exponent(currency))
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


# Every dash that is meant as a minus: the hyphen, the real minus sign, the en dash, the figure dash, the small hyphen minus and the full width hyphen minus.
MINUS = "-\u2212\u2013\u2012\ufe63\uff0d"
_SPACES = re.compile(r"[\u00a0\u2007\u2009\u202f]")
_CODE = re.compile(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])")
_DRCR = re.compile(r"(?i)(?<![A-Za-z])(DR|CR)\.?\s*$")
_DIGITS = re.compile(r"\d{1,3}(?:[ '\u2019]\d{3})+(?:[.,]\d+)?|[\d.,]*\d[\d.,]*")


def parse_amount(text: str, currency: str | None = None, *, debit_credit: bool = False) -> tuple[int, str] | None:
    """Read an amount as written on a document or in a statement. Handles 1,234.50 and 1.234,50, a currency symbol or code, a minus in any of its forms (including the real
    minus sign and the en dash that banks and spreadsheets write), brackets and a trailing minus. Returns (minor, currency), or None.

    It reads only what it fully understands: any other character (a letter, a second sign, a stray symbol) makes the whole text "not an amount" instead of being dropped, so a
    sign can never be lost silently and turn a payment out into money in. DR and CR are read only when `debit_credit` is true (a bank statement: DR is money out, CR is money
    in); anywhere else they are not an amount. A sign together with DR or CR, or two signs, is refused as unclear."""
    if not text or not text.strip():
        return None
    t = _SPACES.sub(" ", text).strip()
    side = None
    m = _DRCR.search(t)
    if m:
        if not debit_credit:
            return None
        side, t = m.group(1).upper(), t[: m.start()].strip()
    cur = currency
    codes = [c for c in _CODE.findall(t) if c in CURRENCY_EXPONENT]
    if len(codes) > 1:
        return None
    if codes:
        cur = codes[0]
        t = re.sub(rf"(?<![A-Za-z]){codes[0]}(?![A-Za-z])", " ", t, count=1)
    symbols = [s for s in SYMBOLS if s in t]
    if len(symbols) > 1 or sum(t.count(s) for s in SYMBOLS) > 1:
        return None
    for sym in symbols:
        if cur and cur not in SYMBOL_CURRENCIES[sym]:
            return None  # the sign says one currency and the currency given (or the code in the text) says another: never pick one silently
        cur = cur or SYMBOLS[sym]
        t = t.replace(sym, " ")
    t = " ".join(t.split())
    if not t:
        return None
    signs = 0
    negative = False
    if t.startswith("(") and t.endswith(")"):
        t, signs, negative = t[1:-1].strip(), signs + 1, True
    if t and t[0] in MINUS + "+":
        negative, signs, t = t[0] in MINUS, signs + 1, t[1:].strip()
    if t and t[-1] in MINUS:
        negative, signs, t = True, signs + 1, t[:-1].strip()
    if signs > 1 or (signs and side):
        return None
    if side:
        negative = side == "DR"
    if not _DIGITS.fullmatch(t):
        return None
    s = re.sub(r"[ '\u2019]", "", t).rstrip(".,")
    if not re.search(r"\d", s):
        return None
    known = cur is not None  # a currency was given, or the text carried a code or a sign
    cur = cur or "USD"
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    if last_dot > -1 and last_comma > -1:
        dec_sep = "." if last_dot > last_comma else ","
    elif last_dot > -1 or last_comma > -1:
        sep = "." if last_dot > -1 else ","
        tail = s.rsplit(sep, 1)[1]
        if s.count(sep) > 1:
            dec_sep = None  # a repeated separator is a thousands mark
        elif len(tail) == 3:
            # One separator and exactly three digits after it: thousands in a currency with 0 or 2 decimals (1,234 USD is one thousand two hundred thirty four), decimals in one with
            # 3 (12.345 KWD is twelve and a bit). With no currency at all it cannot be told, so it is refused instead of guessed: that guess was a 1000 times error.
            if not known:
                return None
            dec_sep = sep if CURRENCY_EXPONENT.get(cur) == 3 else None
        else:
            dec_sep = sep
    else:
        dec_sep = None
    if dec_sep:
        whole, frac = s.rsplit(dec_sep, 1)
        whole = re.sub(r"[.,]", "", whole)
    else:
        whole, frac = re.sub(r"[.,]", "", s), ""
    try:
        minor = to_minor(f"{whole or '0'}.{frac}" if frac else (whole or "0"), cur)
    except MoneyError:
        return None
    return (-minor if negative else minor), cur


def convert(minor: int, from_currency: str, to_currency: str, rate: Decimal) -> int:
    """Turn an amount in one currency into another at a manual rate (units of `to_currency` for one unit of `from_currency`).

    The scale between the two currencies' minor units is applied (JPY has none, USD has two), the product is exact in Decimal,
    and it is rounded once, half away from zero. A float rate is refused. The same currency passes through untouched.
    """
    if isinstance(rate, float) or not isinstance(rate, Decimal):
        raise MoneyError("The rate must be a Decimal, never a float.")
    if not rate.is_finite() or rate <= 0:
        raise MoneyError("The rate must be above zero.")
    if from_currency == to_currency:
        return minor
    scale = Decimal(10) ** (exponent(to_currency) - exponent(from_currency))
    with localcontext() as ctx:
        ctx.prec = 60
        exact = Decimal(abs(minor)) * rate * scale
        q = int(exact.to_integral_value(rounding=ROUND_HALF_UP))
    return -q if minor < 0 else q


def format_minor(minor: int, currency: str = "USD", symbol: bool = True) -> str:
    e = exponent(currency)
    sign = "-" if minor < 0 else ""
    n = abs(minor)
    whole, frac = divmod(n, 10**e) if e else (n, 0)
    body = f"{whole:,}" + (f".{frac:0{e}d}" if e else "")
    return f"{sign}{SYMBOL_FOR.get(currency, '') if symbol else ''}{body}" + ("" if symbol and currency in SYMBOL_FOR else (f" {currency}" if symbol else ""))


def to_major_number(minor: int, currency: str) -> float:
    """The one place a float is made: a JSON number for a vendor API that wants one. It comes from an integer through Decimal and is never read back as money."""
    return float(Decimal(minor).scaleb(-exponent(currency)))


def allocate(total: int, weights: list[int]) -> list[int]:
    """Split `total` across parts in proportion to `weights` (non negative ints). The parts add up to `total` exactly (largest remainder)."""
    if not weights or any(w < 0 for w in weights):
        raise MoneyError("Weights must be a non empty list of non negative integers.")
    w = sum(weights)
    if w == 0:
        raise MoneyError("At least one weight must be above zero.")
    sign = -1 if total < 0 else 1
    t = abs(total)
    base = [t * x // w for x in weights]
    rem = [(t * x) % w for x in weights]
    left = t - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-rem[i], i))
    for i in order[:left]:
        base[i] += 1
    return [sign * b for b in base]


def allocate_capped(amount: int, capacities: list[int]) -> list[int]:
    """Pay a list of open balances in order. Never gives a part more than its capacity and never more than `amount` in total."""
    out, left = [], max(amount, 0)
    for cap in capacities:
        take = min(left, max(cap, 0))
        out.append(take)
        left -= take
    return out


@dataclass(frozen=True)
class Money:
    minor: int
    currency: str = "USD"

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor - other.minor, self.currency)

    def _same(self, other: Money) -> None:
        if other.currency != self.currency:
            raise MoneyError(f"Cannot mix {self.currency} and {other.currency}.")

    def __str__(self) -> str:
        return format_minor(self.minor, self.currency)
