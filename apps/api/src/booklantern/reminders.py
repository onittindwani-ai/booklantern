"""The reminder ladder and its stop rules. One pure function decides what may happen to one invoice right now.

Decided defaults: the ladder days (1, 7, 14 and 30 after the due date), tones (friendly, firm, firmer, final), minimum gap, maximum count and send window below. The implementer can change them with the settings in docs/04.
Stop rules are checked first and always win. A stop is permanent for as long as its condition holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

LADDER = ((1, 1, "friendly"), (2, 7, "firm"), (3, 14, "firmer"), (4, 30, "final"))  # step, days after the due date, tone


@dataclass(frozen=True)
class Config:
    max_count: int = 4
    min_gap_days: int = 5
    window_start: int = 9  # local hour, inclusive
    window_end: int = 17  # local hour, exclusive
    weekdays_only: bool = True
    ladder: tuple = LADDER


@dataclass
class InvoiceState:
    id: int
    due: date
    outstanding_minor: int
    status: str = "open"  # open, paid, void
    disputed: bool = False
    opted_out: bool = False
    bankruptcy: bool = False
    timezone: str = "America/New_York"
    promises: list[tuple[date, str]] = field(default_factory=list)  # (promised date, status open, kept, broken)
    sent: list[tuple[int, date]] = field(default_factory=list)  # (step, date sent)


@dataclass(frozen=True)
class Decision:
    action: str  # send, draft, wait, stop
    reason: str
    step: int = 0
    tone: str = ""


def stop_reason(inv: InvoiceState, local_today: date, cfg: Config, kill_switch: bool) -> str | None:
    if kill_switch:
        return "kill_switch"
    if inv.status in ("paid", "void") or inv.outstanding_minor <= 0:
        return "paid"
    if inv.opted_out:
        return "opt_out"
    if inv.bankruptcy:
        return "bankruptcy"
    if inv.disputed:
        return "dispute"
    if any(st == "open" and d >= local_today for d, st in inv.promises):
        return "promise_pending"
    if len(inv.sent) >= cfg.max_count:
        return "max_count"
    return None


def decide(inv: InvoiceState, now_utc: datetime, cfg: Config = Config(), mode: str = "draft", kill_switch: bool = False) -> Decision:
    local = now_utc.astimezone(ZoneInfo(inv.timezone))
    why = stop_reason(inv, local.date(), cfg, kill_switch)
    if why:
        return Decision("stop", why)
    done = {s for s, _ in inv.sent}
    nxt = next(((s, d, tone) for s, d, tone in cfg.ladder if s not in done), None)
    if nxt is None:
        return Decision("stop", "max_count")
    step, days, tone = nxt
    late = (local.date() - inv.due).days
    if late < days:
        return Decision("wait", "not_due_yet", step, tone)
    if inv.sent and (local.date() - max(d for _, d in inv.sent)).days < cfg.min_gap_days:
        return Decision("wait", "min_gap", step, tone)
    if cfg.weekdays_only and local.weekday() >= 5:
        return Decision("wait", "quiet_hours", step, tone)
    if not (cfg.window_start <= local.hour < cfg.window_end):
        return Decision("wait", "quiet_hours", step, tone)
    return Decision("send" if mode == "live" else "draft", "due", step, tone)


def still_allowed(inv: InvoiceState, now_utc: datetime, cfg: Config = Config(), kill_switch: bool = False) -> str | None:
    """Checked again at the moment of sending, because a payment, dispute or promise may have been recorded after the draft was made."""
    local = now_utc.astimezone(ZoneInfo(inv.timezone))
    return stop_reason(inv, local.date(), cfg, kill_switch)


TONE_TEXT = {  # default wording, the implementer can replace it with the client's own
    "friendly": "A friendly reminder that invoice {number} for {amount} was due on {due}. If it has already gone out, thank you and please ignore this note.",
    "firm": "Invoice {number} for {amount}, due on {due}, is now {late} days overdue. Please arrange payment this week or tell us when we can expect it.",
    "firmer": "Invoice {number} for {amount} is {late} days overdue. Please pay today, or reply with a date you will pay by. If something is wrong with the invoice, tell us and we will look at it straight away.",
    "final": "Final reminder: invoice {number} for {amount} is {late} days overdue. Without payment or a reply we will have to pass this to our next step. Please contact us today.",
}
