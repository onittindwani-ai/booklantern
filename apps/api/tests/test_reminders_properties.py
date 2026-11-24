"""Stop rules hold on random worlds. A world is a seeded random invoice with random events over 90 days."""

import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from booklantern import reminders as R

ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"]


def oracle_blocked(inv: R.InvoiceState, now: datetime, cfg: R.Config) -> str | None:
    """A second, plainer statement of the rules, written separately from the code under test."""
    local = now.astimezone(ZoneInfo(inv.timezone))
    if inv.status != "open" or inv.outstanding_minor <= 0:
        return "paid"
    if inv.opted_out:
        return "opt_out"
    if inv.bankruptcy:
        return "bankruptcy"
    if inv.disputed:
        return "dispute"
    if any(st == "open" and d >= local.date() for d, st in inv.promises):
        return "promise"
    if len(inv.sent) >= cfg.max_count:
        return "max"
    return None


def world(seed: int):
    rng = random.Random(seed)
    due = date(2026, 6, 1) + timedelta(days=rng.randint(0, 20))
    inv = R.InvoiceState(1, due, rng.randint(1000, 10**6), timezone=rng.choice(ZONES), opted_out=rng.random() < 0.1, bankruptcy=rng.random() < 0.08, disputed=rng.random() < 0.12)
    if rng.random() < 0.3:
        inv.promises.append((due + timedelta(days=rng.randint(2, 40)), "open"))
    return rng, inv


def test_a_reminder_is_never_made_when_a_stop_rule_holds_property():
    cfg, made = R.Config(), 0
    for seed in range(400):
        rng, inv = world(seed)
        t = datetime(2026, 6, 1, tzinfo=UTC)
        for _ in range(24 * 90):
            t += timedelta(hours=1)
            if rng.random() < 0.002:
                inv.status, inv.outstanding_minor = "paid", 0
            if rng.random() < 0.002:
                inv.disputed = True
            if rng.random() < 0.003:
                inv.promises.append((t.date() + timedelta(days=rng.randint(1, 10)), "open"))
            d = R.decide(inv, t, cfg, "live", False)
            if d.action in ("send", "draft"):
                made += 1
                local = t.astimezone(ZoneInfo(inv.timezone))
                assert oracle_blocked(inv, t, cfg) is None, f"seed {seed}: sent while {oracle_blocked(inv, t, cfg)}"
                assert local.weekday() < 5 and cfg.window_start <= local.hour < cfg.window_end
                assert (local.date() - inv.due).days >= dict((s, dd) for s, dd, _ in cfg.ladder)[d.step]
                if inv.sent:
                    assert (local.date() - max(x for _, x in inv.sent)).days >= cfg.min_gap_days
                assert d.step not in {s for s, _ in inv.sent} and len(inv.sent) < cfg.max_count
                inv.sent.append((d.step, local.date()))
    assert made > 100  # not vacuous: reminders were allowed in many worlds


def test_stop_rules_win_in_every_mode_and_with_the_kill_switch():
    rng, inv = world(5)
    inv.disputed, inv.bankruptcy, inv.opted_out = False, False, False
    now = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
    inv.due = date(2026, 7, 1)
    assert R.decide(inv, now, mode="live").action == "send"
    assert R.decide(inv, now, mode="draft").action == "draft"
    assert R.decide(inv, now, mode="live", kill_switch=True) == R.Decision("stop", "kill_switch")
    for field, reason in (("opted_out", "opt_out"), ("bankruptcy", "bankruptcy"), ("disputed", "dispute")):
        setattr(inv, field, True)
        assert R.decide(inv, now, mode="live").reason == reason
        setattr(inv, field, False)


def test_a_draft_is_cancelled_by_a_later_payment_dispute_or_promise():
    _, inv = world(9)
    inv.disputed = inv.bankruptcy = inv.opted_out = False
    inv.promises.clear()
    inv.due = date(2026, 7, 1)
    now = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
    assert R.still_allowed(inv, now) is None
    inv.promises.append((date(2026, 8, 9), "open"))
    assert R.still_allowed(inv, now) == "promise_pending"
    inv.promises.clear(); inv.disputed = True
    assert R.still_allowed(inv, now) == "dispute"
    inv.disputed = False; inv.status = "paid"
    assert R.still_allowed(inv, now) == "paid"


def test_waits_outside_the_window_and_on_weekends():
    _, inv = world(11)
    inv.disputed = inv.bankruptcy = inv.opted_out = False
    inv.promises.clear(); inv.sent.clear(); inv.timezone = "America/New_York"; inv.due = date(2026, 7, 1)
    sat = datetime(2026, 8, 8, 15, 0, tzinfo=UTC)
    night = datetime(2026, 8, 5, 3, 0, tzinfo=UTC)
    assert R.decide(inv, sat, mode="live").reason == "quiet_hours" and R.decide(inv, night, mode="live").reason == "quiet_hours"
