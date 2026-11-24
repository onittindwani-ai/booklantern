"""Read a date as a person writes it on a bill. General date knowledge, no layout in mind.

Handles year first (2026-10-14, 2026/10/14, 2026.10.14, 20261014), day or month first with a separator (14/10/2026, 10/14/2026, 14.10.2026, 14-10-2026,
12.10.26), month names in English, German, French, Spanish, Italian, Dutch, Portuguese and Polish (14 Oct 2026, 14-Oct-26, October 14, 2026, 14th September
2026, 14 de marzo de 2026, 12. Oktober 2026), and year, month, day in Japanese (2026年10月14日).

A numeric date where both numbers are 12 or less is ambiguous. A dot is read day first (the usual European way), a slash follows the country hint given by
the caller (month first for US style, day first otherwise). `read_date` returns the date and whether the reading was a guess, so the reader can lower its
confidence and show the other reading. `pick_pair` uses a second date (the due date) to settle an ambiguous issue date when only one reading makes sense.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

MONTHS = {
    "jan": 1, "january": 1, "januar": 1, "janvier": 1, "enero": 1, "gennaio": 1, "januari": 1, "janeiro": 1, "stycznia": 1, "styczen": 1, "janv": 1, "ene": 1, "gen": 1,
    "feb": 2, "february": 2, "februar": 2, "fevrier": 2, "febrero": 2, "febbraio": 2, "februari": 2, "fevereiro": 2, "lutego": 2, "luty": 2, "fev": 2,
    "mar": 3, "march": 3, "marz": 3, "maerz": 3, "mars": 3, "marzo": 3, "maart": 3, "marco": 3, "marca": 3, "marzec": 3, "mrt": 3, "mär": 3,
    "apr": 4, "april": 4, "avril": 4, "abril": 4, "aprile": 4, "kwietnia": 4, "kwiecien": 4, "avr": 4, "abr": 4,
    "may": 5, "mai": 5, "mayo": 5, "maggio": 5, "mei": 5, "maio": 5, "maja": 5, "maj": 5, "mag": 5,
    "jun": 6, "june": 6, "juni": 6, "juin": 6, "junio": 6, "giugno": 6, "junho": 6, "czerwca": 6, "czerwiec": 6, "giu": 6,
    "jul": 7, "july": 7, "juli": 7, "juillet": 7, "julio": 7, "luglio": 7, "julho": 7, "lipca": 7, "lipiec": 7, "juil": 7, "lug": 7,
    "aug": 8, "august": 8, "aout": 8, "agosto": 8, "augustus": 8, "sierpnia": 8, "sierpien": 8, "ago": 8,
    "sep": 9, "sept": 9, "september": 9, "septembre": 9, "septiembre": 9, "settembre": 9, "setembro": 9, "wrzesnia": 9, "wrzesien": 9, "set": 9,
    "oct": 10, "october": 10, "oktober": 10, "octobre": 10, "octubre": 10, "ottobre": 10, "okt": 10, "outubro": 10, "pazdziernika": 10, "pazdziernik": 10, "out": 10, "ott": 10,
    "nov": 11, "november": 11, "novembre": 11, "noviembre": 11, "listopada": 11, "listopad": 11, "novembro": 11,
    "dec": 12, "december": 12, "dezember": 12, "decembre": 12, "diciembre": 12, "dicembre": 12, "grudnia": 12, "grudzien": 12, "dez": 12, "dezembro": 12, "dic": 12, 
}
_WORD = r"[^\W\d_]{3,12}\.?"


def fold(s: str) -> str:
    """Lower case without accents, so 'février' and 'Fevrier' match."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def _month(word: str) -> int | None:
    return MONTHS.get(fold(word).strip("."))


def _year(y: str) -> int:
    n = int(y)
    return n if len(y) == 4 else 2000 + n if n < 70 else 1900 + n


def _ok(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def read_date(text: str, month_first: bool = False) -> tuple[date, bool] | None:
    """(date, guessed) or None. `guessed` is true when day and month could be swapped."""
    t = fold(text).replace(" ", " ").strip()
    if (m := re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text)):
        d = _ok(int(m[1]), int(m[2]), int(m[3]))
        return (d, False) if d else None
    if (m := re.search(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", t)) or (m := re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", t)):
        d = _ok(int(m[1]), int(m[2]), int(m[3]))
        return (d, False) if d else None
    if (m := re.search(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th|er|\.|º)?\s*(?:de\s+|of\s+)?[-\s.]?(" + _WORD + r")[-\s.,]*(?:de\s+)?(\d{4}|\d{2})(?!\d)", t)) and _month(m[2]):
        d = _ok(_year(m[3]), _month(m[2]), int(m[1]))
        return (d, False) if d else None
    if (m := re.search(r"(" + _WORD + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)", t)) and _month(m[1]):
        d = _ok(int(m[3]), _month(m[1]), int(m[2]))
        return (d, False) if d else None
    if (m := re.search(r"(?<!\d)(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})(?!\d)", t)):
        a, sep, b, y = int(m[1]), m[2], int(m[3]), _year(m[4])
        day_first, month_first_read = _ok(y, b, a), _ok(y, a, b)
        if a > 12 or not month_first_read:
            return (day_first, False) if day_first else None
        if b > 12 or not day_first:
            return (month_first_read, False) if month_first_read else None
        guessed = a != b
        return ((month_first_read if month_first and sep == "/" else day_first), guessed)
    return None


def other_reading(text: str, chosen: date) -> date | None:
    """The day and month swapped, when that is a real date and different."""
    try:
        d = date(chosen.year, chosen.day, chosen.month)
    except ValueError:
        return None
    return d if d != chosen else None


def pick_pair(issue: tuple[date, bool], due: date | None) -> tuple[date, bool]:
    """An ambiguous issue date is settled when only one reading puts the due date 0 to 120 days after it."""
    d, guessed = issue
    if not guessed or due is None:
        return issue
    alt = other_reading("", d)
    ok = lambda x: x is not None and timedelta(0) <= due - x <= timedelta(days=120)  # noqa: E731
    if ok(d) and not ok(alt):
        return d, False
    if ok(alt) and not ok(d):
        return alt, False
    return issue
