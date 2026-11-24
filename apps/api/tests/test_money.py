import random

import pytest

from booklantern import money as M


def test_rounding_is_half_away_from_zero():
    assert M.div_round(5, 10) == 1 and M.div_round(-5, 10) == -1 and M.div_round(4, 10) == 0 and M.div_round(-4, 10) == 0
    assert M.tax_for(1999, 725) == 145  # 144.9275 rounds to 145
    assert M.mul_bp(1, 5000) == 1 and M.mul_bp(-1, 5000) == -1


def test_a_float_is_refused():
    with pytest.raises(M.MoneyError):
        M.to_minor(12.5, "USD")
    assert M.to_minor("12.345", "USD") == 1235 and M.to_minor("12.5", "JPY") == 13


@pytest.mark.parametrize("text,want", [("$1,234.50", (123450, "USD")), ("1.234,50 €", (123450, "EUR")), ("USD 12,000", (1200000, "USD")), ("(5.00)", (-500, "USD")), ("-8.35", (-835, "USD")),
                                       ("1,234", (123400, "USD")), ("€ 1.234.567,89", (123456789, "EUR")), ("99", (9900, "USD"))])
def test_parse_amount_as_written(text, want):
    assert M.parse_amount(text) == want


def test_parse_amount_refuses_words():
    assert M.parse_amount("none") is None and M.parse_amount("") is None


def test_format_and_parse_round_trip():
    rng = random.Random(1)
    for _ in range(500):
        n = rng.randint(-10**9, 10**9)
        assert M.parse_amount(M.format_minor(n, "USD", symbol=False), "USD")[0] == n


def test_allocate_parts_add_up_exactly_property():
    rng = random.Random(2)
    for _ in range(2000):
        total = rng.randint(-10**8, 10**8)
        w = [rng.randint(0, 50) for _ in range(rng.randint(1, 9))]
        if sum(w) == 0:
            continue
        parts = M.allocate(total, w)
        assert sum(parts) == total and len(parts) == len(w)
        assert all(p == 0 for p, x in zip(parts, w) if x == 0)


def test_allocate_capped_never_exceeds_amount_or_capacity_property():
    rng = random.Random(3)
    for _ in range(2000):
        amount = rng.randint(0, 10**7)
        caps = [rng.randint(0, 10**6) for _ in range(rng.randint(1, 8))]
        got = M.allocate_capped(amount, caps)
        assert sum(got) <= amount and all(g <= c for g, c in zip(got, caps))
        assert sum(got) == min(amount, sum(caps))


def test_money_refuses_to_mix_currencies():
    with pytest.raises(M.MoneyError):
        M.Money(1, "USD") + M.Money(1, "EUR")
    assert str(M.Money(150, "USD") + M.Money(50, "USD")) == "$2.00"


def test_line_total_uses_thousandths():
    assert M.line_total(2500, 9500) == 23750 and M.line_total(1000, 33) == 33
