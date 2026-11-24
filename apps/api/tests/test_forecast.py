import random
from datetime import date, timedelta

from booklantern import forecast as F
from booklantern.money import mul_bp

AS_OF = date(2026, 12, 1)


def world(seed: int) -> F.Inputs:
    rng = random.Random(seed)
    ar = [F.ArItem(i, rng.randint(1, 5), AS_OF + timedelta(days=rng.randint(-100, 90)), rng.randint(1000, 900000), (AS_OF + timedelta(days=rng.randint(1, 40))) if rng.random() < 0.2 else None,
                   "dispute" if rng.random() < 0.1 else "") for i in range(rng.randint(0, 30))]
    ap = [F.ApItem(i, AS_OF + timedelta(days=rng.randint(-20, 100)), rng.randint(1000, 400000)) for i in range(rng.randint(0, 20))]
    rec = [F.Recurring("rent", "out", 320000, "monthly", rng.randint(1, 31)), F.Recurring("pay", "out", 650000, "twice_monthly", 15), F.Recurring("fee", "out", 2500, "weekly", 1)]
    return F.Inputs(AS_OF, rng.randint(-100000, 9000000), ar, ap, rec, {c: rng.randint(-3, 30) for c in range(1, 6)}, new_sales_weekly_minor=rng.randint(0, 300000))


def test_same_inputs_give_the_same_answer_property():
    for seed in range(200):
        a, b = F.run(world(seed)), F.run(world(seed))
        assert a == b


def test_cash_adds_up_week_by_week_property():
    for seed in range(300):
        inp = world(seed)
        r = F.run(inp)
        cash = inp.opening_cash_minor
        for w in r["weeks"]:
            assert w["opening_minor"] == cash
            assert w["net_minor"] == w["receipts_minor"] + w["new_sales_minor"] + w["bills_minor"] + w["recurring_in_minor"] + w["recurring_out_minor"] + w["other_minor"]
            cash += w["net_minor"]
            assert w["closing_minor"] == cash
        assert r["closing_minor"] == cash and len(r["weeks"]) == 13
        assert r["low_point_minor"] == min(w["closing_minor"] for w in r["weeks"])


def test_receipts_equal_the_sum_of_per_invoice_rounding_property():
    for seed in range(300):
        inp = world(seed)
        sc = F.Scenario()
        expect = beyond = 0
        for it in inp.ar:
            got = F.expected_receipt(it, inp, sc)
            if got:
                if F.week_of(got[0], AS_OF) is None:
                    beyond += got[1]
                else:
                    expect += got[1]
        r = F.run(inp, sc)
        assert sum(w["receipts_minor"] for w in r["weeks"]) == expect and r["beyond_horizon_minor"] == beyond


def test_disputed_invoices_count_for_nothing():
    it = F.ArItem(1, 1, AS_OF, 100000, None, "dispute")
    r = F.run(F.Inputs(AS_OF, 0, [it]))
    assert r["total_receipts_minor"] == 0 and r["beyond_horizon_minor"] == 0


def test_collecting_later_moves_cash_without_changing_the_total_except_spill_property():
    for seed in range(200):
        inp = world(seed)
        inp.new_sales_weekly_minor = 0
        base, late = F.run(inp), F.run(inp, F.Scenario(collect_delay_days=10))
        assert late["total_receipts_minor"] + late["beyond_horizon_minor"] == base["total_receipts_minor"] + base["beyond_horizon_minor"]
        assert late["total_receipts_minor"] <= base["total_receipts_minor"]
        # cash never arrives earlier
        run_b = run_l = 0
        for wb, wl in zip(base["weeks"], late["weeks"]):
            run_b += wb["receipts_minor"]; run_l += wl["receipts_minor"]
            assert run_l <= run_b


def test_scenarios_do_what_they_say():
    inp = world(7)
    base = F.run(inp)
    hire = F.run(inp, F.Scenario(hires=((500000, 2),)))
    assert hire["closing_minor"] == base["closing_minor"] - 500000 * 3  # weeks 2, 6 and 10
    one = F.run(inp, F.Scenario(one_offs=((3, -100000),)))
    assert one["closing_minor"] == base["closing_minor"] - 100000
    slow = F.run(inp, F.Scenario(pay_delay_days=14))
    assert slow["closing_minor"] >= base["closing_minor"]


def test_a_promise_is_used_at_its_date_and_probability():
    it = F.ArItem(1, 1, AS_OF - timedelta(days=50), 100000, AS_OF + timedelta(days=9))
    r = F.run(F.Inputs(AS_OF, 0, [it]))
    assert r["weeks"][1]["receipts_minor"] == mul_bp(100000, F.PROMISE_PROB_BP)


def test_recurring_dates():
    assert F.occurrences(F.Recurring("r", "out", 1, "monthly", 31), date(2026, 12, 1), date(2027, 2, 28)) == [date(2026, 12, 31), date(2027, 1, 31), date(2027, 2, 28)]
    assert len(F.occurrences(F.Recurring("w", "out", 1, "weekly"), AS_OF, AS_OF + timedelta(days=90))) == 13
