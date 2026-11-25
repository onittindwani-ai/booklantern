"""Receivables work: aging, the reminder ladder in the database, promises, disputes, opt outs, payment links."""

from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import aging, fx as FX, model_tasks, reminders as R
from booklantern.exceptions import raise_exception
from booklantern.models import Customer, Invoice, PromiseToPay, Reminder
from booklantern.money import MoneyError, format_minor
from booklantern.util import is_valid_email
from sendora_core.adapters import AdapterError
from sendora_core.approvals import request_approval
from sendora_core.audit import record_audit
from sendora_core.events import record_event
from sendora_core.safety import SafetyError, guard_write

log = logging.getLogger("booklantern.collections")
DRAFT_LINK_PREFIX = "https://pay.example.test/draft/"  # a placeholder shown in draft mode: it is never stored on an invoice and never put in a reminder


def cfg(settings) -> R.Config:
    return R.Config(max_count=settings.reminder_max_count, min_gap_days=settings.reminder_min_gap_days, window_start=settings.reminder_window_start, window_end=settings.reminder_window_end)


def open_items(session: Session, as_of: date | None = None, rates: FX.RateBook | None = None, report: FX.FxReport | None = None) -> list[aging.OpenItem]:
    """Open invoices as aging items in the company currency. An invoice in another currency is converted at the manual rate of `as_of`
    and recorded in `report`; with no rate it is left out and recorded there. It is never added as if it were in the company currency."""
    book = rates or FX.RateBook("USD")
    report = report if report is not None else FX.FxReport(book.base)
    day = as_of or date.today()
    out = []
    for i in session.scalars(select(Invoice).where(Invoice.status == "open")):
        left = i.total_minor - i.paid_minor
        c = book.try_convert(left, i.currency, day)
        if c is None:
            report.leave_out("invoice", i.id, i.number, left, i.currency, day)
            continue
        out.append(aging.OpenItem(i.id, i.customer_id, i.due_date, report.add("invoice", i.id, i.number, c)))
    return out


def aging_report(session: Session, as_of: date, rates: FX.RateBook | None = None) -> dict:
    """Aging in the company currency, with an `fx` block listing every converted invoice (original amount, rate, rate date) and every one left out."""
    report = FX.FxReport(rates.base if rates else "USD")
    rep = aging.age(open_items(session, as_of, rates, report), as_of)
    names = {c.id: c.name for c in session.scalars(select(Customer))}
    rep["customers"] = [{"customer_id": cid, "name": names[cid], "buckets_minor": b, "total_minor": sum(b.values())} for cid, b in sorted(rep["by_customer"].items(), key=lambda kv: -sum(kv[1].values()))]
    del rep["by_customer"]
    rep["currency"] = report.base
    rep["fx"] = report.to_dict()
    return rep


def state_for(session: Session, inv: Invoice) -> R.InvoiceState:
    ps = [(p.promised_on, p.status) for p in session.scalars(select(PromiseToPay).where(PromiseToPay.invoice_id == inv.id))]
    sent = [(r.step, r.sent_at.date()) for r in session.scalars(select(Reminder).where(Reminder.invoice_id == inv.id, Reminder.status.in_(("sent", "sending"))))]
    c = inv.customer
    return R.InvoiceState(inv.id, inv.due_date, inv.total_minor - inv.paid_minor, inv.status, inv.disputed, c.opted_out, c.bankruptcy_flag, c.timezone, ps, sent)


def reminder_facts(inv: Invoice, step_tone: str, now: datetime) -> dict:
    """The facts a reminder may state, worked out by code. A model that words the reminder may use only these."""
    return {"number": inv.number, "amount": format_minor(inv.total_minor - inv.paid_minor, inv.currency), "due": inv.due_date.isoformat(), "late": max((now.date() - inv.due_date).days, 0), "tone": step_tone, "customer": inv.customer.name}


def default_wording(inv: Invoice, step_tone: str, now: datetime) -> tuple[str, str]:
    f = reminder_facts(inv, step_tone, now)
    return f"Invoice {inv.number}: {step_tone} reminder", R.TONE_TEXT[step_tone].format(number=f["number"], amount=f["amount"], due=f["due"], late=f["late"])


def footer(settings) -> str:
    """Who is writing and how to stop it: the company's name, its postal address and one plain sentence. Added by code to every reminder, whatever wording was used."""
    lines = ["--", settings.company_name.strip()]
    if settings.company_address.strip():
        lines.append(" ".join(settings.company_address.split()))
    lines += ["", "If you would rather not get these reminders, reply to this email and say so, and we will stop them."]
    return "\n".join(lines)


def render(inv: Invoice, step_tone: str, now: datetime, link: str = "", wording: tuple[str, str] | None = None, settings=None) -> tuple[str, str]:
    """The reminder subject and body. `wording` (subject, text) comes from a model that passed the checks in model_tasks.write_reminder; otherwise the default wording is used.
    With `settings` the body is signed with the company name and ends with the compliance footer."""
    subject, text = wording or default_wording(inv, step_tone, now)
    if link.startswith(DRAFT_LINK_PREFIX):
        link = ""  # a draft placeholder is not a page the customer can pay on
    sign = settings.company_name.strip() if settings is not None else "Accounts"
    body = f"Hello {inv.customer.name},\n\n{text}\n" + (f"\nYou can pay online here: {link}\n" if link else "") + f"\nThank you,\n{sign}"
    if settings is not None:
        body += "\n\n" + footer(settings)
    return subject, body


def plan_reminders(session: Session, ctx) -> dict:
    """Decide for every open invoice what may happen now. Only drafts are made. A person approves each one."""
    eff, now = ctx.effective(session), ctx.now(session)
    c, made, stops, waits = cfg(eff), 0, {}, {}
    for inv in session.scalars(select(Invoice).where(Invoice.status == "open").order_by(Invoice.id)):
        d = R.decide(state_for(session, inv), now, c, eff.mode.value, eff.kill_switch)
        if d.action in ("send", "draft"):
            exists = session.scalars(select(Reminder).where(Reminder.invoice_id == inv.id, Reminder.step == d.step, Reminder.status.in_(("drafted", "approved", "sending", "sent")))).first()
            if not exists:
                wording = None
                if eff.reminder_writer == "model":  # UNVERIFIED live; checked in code, falls back to the default wording, and a person still approves
                    wording = model_tasks.write_reminder(ctx.llm(session), reminder_facts(inv, d.tone, now), default_wording(inv, d.tone, now))
                try:
                    subj, body = render(inv, d.tone, now, inv.payment_link_url, wording, eff)
                except MoneyError:
                    log.warning("reminder for invoice %s skipped: its currency is not one the system knows", inv.id)
                    continue
                r = Reminder(invoice_id=inv.id, step=d.step, tone=d.tone, scheduled_for=now, subject=subj, body=body, payment_link_url=inv.payment_link_url)
                session.add(r)
                session.flush()
                request_approval(session, "reminder.send", f"{d.tone} reminder for {inv.number} to {inv.customer.name}", {"reminder_id": r.id, "invoice": inv.number}, "low", "system")
                made += 1
        else:
            (stops if d.action == "stop" else waits)[d.reason] = (stops if d.action == "stop" else waits).get(d.reason, 0) + 1
    return {"drafted": made, "stopped": stops, "waiting": waits}


def cancel_drafts(session: Session, invoice_id: int, reason: str) -> int:
    n = 0
    for r in session.scalars(select(Reminder).where(Reminder.invoice_id == invoice_id, Reminder.status.in_(("drafted", "approved")))):
        r.status, r.cancel_reason = "cancelled", reason
        n += 1
    return n


def send_approved(session: Session, ctx) -> dict:
    """Send approved reminders. The rules are checked again now, because a payment, dispute or promise may have come in since approval."""
    eff, now = ctx.effective(session), ctx.now(session)
    sent = held = cancelled = 0
    for r in list(session.scalars(select(Reminder).where(Reminder.status == "sending"))):  # left over from a stop in the middle of sending: it may or may not have gone out
        raise_exception(session, "reminder_unconfirmed", "warning", "reminder", r.id, f"A reminder for invoice {r.invoice.number} was being sent when the program stopped. Look in the sent mail folder: if it went out, nothing more is needed; if it did not, write to the customer by hand. This system will not send this reminder again by itself. Mark this finding dealt with when you have looked.")
    for r in list(session.scalars(select(Reminder).where(Reminder.status == "approved").order_by(Reminder.id))):
        inv = r.invoice
        why = R.still_allowed(state_for(session, inv), now, cfg(eff), eff.kill_switch)
        if why:
            r.status, r.cancel_reason = "cancelled", why
            cancelled += 1
            continue
        d = R.decide(state_for(session, inv), now, cfg(eff), eff.mode.value, eff.kill_switch)
        if d.action == "wait" and d.reason in ("quiet_hours", "min_gap"):
            held += 1
            continue
        if not is_valid_email(inv.customer.email):
            r.status, r.cancel_reason = "cancelled", "no_valid_email"
            cancelled += 1
            continue
        try:
            guard_write(eff, "email.send")
        except SafetyError:
            held += 1  # draft mode or kill switch: it stays approved and nothing leaves
            continue
        # The intent is saved BEFORE the mail leaves. If the program stops after the mail went out but before "sent" was saved, the reminder is still "sending" and is never
        # sent again by itself (a person is told to look), instead of going to the customer a second time.
        r.status, r.sent_at = "sending", now
        session.commit()
        try:
            ctx.adapters.email.send(from_addr=eff.email_from, to=inv.customer.email, subject=r.subject, body=r.body)
        except (SafetyError, AdapterError) as exc:
            r.status, r.sent_at = "approved", None  # nothing left: the reminder goes back and is tried again later, the others still go out
            session.commit()
            held += 1
            log.warning("reminder %s was not sent: %s", r.id, str(exc)[:200])
            continue
        r.status = "sent"
        record_audit(session, "system", "reminder.sent", f"reminder:{r.id}", {"invoice": inv.number})
        session.commit()  # saved at once, one reminder at a time: a failure later in the loop can never make this one go out again
        sent += 1
    return {"sent": sent, "held": held, "cancelled": cancelled}


def approve_reminder(session: Session, reminder_id: int, who: str) -> Reminder:
    r = session.get(Reminder, reminder_id)
    if r is None or r.status != "drafted":
        raise ValueError("This reminder is not waiting for approval.")
    if not is_valid_email(r.invoice.customer.email):
        raise ValueError(f"{r.invoice.customer.name} has no valid email address on file, so this reminder cannot be sent. Add the address first.")
    r.status = "approved"
    record_audit(session, who, "reminder.approved", f"reminder:{r.id}", {})
    return r


def close_approval(session: Session, reminder_id: int, approve: bool, who: str, role: str) -> None:
    """A reminder is decided in two places (the Drafts tab and the Approvals page). Whichever is used, the pending request for it is closed, so it never waits there for nothing."""
    from sendora_core.approvals import ApprovalError, decide
    from sendora_core.models import Approval

    for a in session.scalars(select(Approval).where(Approval.status == "pending", Approval.action == "reminder.send")):
        if int((a.payload or {}).get("reminder_id", 0)) == reminder_id:
            try:
                decide(session, a.id, approve, who, role, "decided on the Collections page")
            except ApprovalError:
                pass  # the person who asked cannot decide their own request: it stays for someone else


def record_promise(session: Session, invoice_id: int, promised_on: date, amount_minor: int, note: str, who: str) -> PromiseToPay:
    for old in session.scalars(select(PromiseToPay).where(PromiseToPay.invoice_id == invoice_id, PromiseToPay.status == "open")):
        old.status = "replaced"  # the newest promise is the one that counts, for the ladder and for the forecast
    p = PromiseToPay(invoice_id=invoice_id, promised_on=promised_on, amount_minor=amount_minor, note=note[:240])
    session.add(p)
    cancel_drafts(session, invoice_id, "promise_pending")
    record_audit(session, who, "promise.recorded", f"invoice:{invoice_id}", {"on": promised_on.isoformat()})
    session.flush()
    return p


def set_dispute(session: Session, invoice_id: int, disputed: bool, note: str, who: str) -> Invoice:
    inv = session.get(Invoice, invoice_id)
    inv.disputed, inv.dispute_note = disputed, note[:240]
    if disputed:
        cancel_drafts(session, invoice_id, "dispute")
    record_audit(session, who, "invoice.dispute", f"invoice:{invoice_id}", {"disputed": disputed})
    return inv


def set_opt_out(session: Session, customer_id: int, opted_out: bool, who: str) -> Customer:
    c = session.get(Customer, customer_id)
    c.opted_out = opted_out
    if opted_out:
        for inv in session.scalars(select(Invoice).where(Invoice.customer_id == c.id)):
            cancel_drafts(session, inv.id, "opt_out")
    record_audit(session, who, "customer.opt_out", f"customer:{customer_id}", {"opted_out": opted_out})
    return c


def update_promises(session: Session, today: date) -> int:
    """A promise whose date has passed with the invoice still open is broken. One that sees the invoice paid is kept."""
    n = 0
    for p in session.scalars(select(PromiseToPay).where(PromiseToPay.status == "open")):
        inv = p.invoice
        if inv.status == "paid" or inv.total_minor - inv.paid_minor <= 0:
            p.status = "kept"; n += 1
        elif p.promised_on < today:
            p.status = "broken"; n += 1
    return n


def create_payment_link(session: Session, ctx, invoice_id: int, who: str) -> dict:
    inv = session.get(Invoice, invoice_id)
    eff = ctx.effective(session)
    amount = inv.total_minor - inv.paid_minor
    try:
        guard_write(eff, "payments.create_link")
        url = ctx.adapters.payments.create_payment_link(invoice_number=inv.number, amount_minor=amount, currency=inv.currency, description=f"Invoice {inv.number}")
        real = True
    except SafetyError:
        url, real = f"{DRAFT_LINK_PREFIX}{inv.number}", False  # a placeholder: draft mode creates nothing at the payment provider, and the placeholder is not stored
    if real:
        inv.payment_link_url = url
    record_audit(session, who, "payment_link.created", f"invoice:{inv.id}", {"real": real})
    record_event(session, "payment_link", "invoice", inv.id, {"real": real})
    return {"url": url, "real": real}
