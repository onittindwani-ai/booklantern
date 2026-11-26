"""Bank side in the database: CSV import, matching, manual links, and the balance."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from booklantern import bankcsv, reconcile as RC
from booklantern.exceptions import raise_exception
from booklantern.money import format_minor
from booklantern.models import ExceptionItem, BankAccount, BankTransaction, Bill, Customer, Invoice, Match, Payment, PaymentAllocation, RecurringItem, Vendor
from sendora_core.audit import record_audit


def import_csv(session: Session, text: str, batch: str, account_id: int | None = None) -> dict:
    accounts = list(session.scalars(select(BankAccount).order_by(BankAccount.id)))
    if not accounts:
        raise bankcsv.CsvError("There is no bank account yet. Add one first (Bank accounts, or POST /api/bank/accounts) with its currency and opening balance.")
    if account_id is None and len(accounts) > 1:
        raise bankcsv.CsvError("There is more than one bank account, so say which one this statement belongs to (account_id). Names: " + "; ".join(f"{a.id} {a.name} ({a.currency})" for a in accounts[:10]) + ".")
    acct = next((a for a in accounts if a.id == account_id), None) if account_id is not None else accounts[0]
    if acct is None:
        raise bankcsv.CsvError(f"There is no bank account with the number {account_id}.")
    rows = bankcsv.parse(text, acct.currency, acct.id)
    for n, r in enumerate(rows, start=2):
        if r.currency.upper() != acct.currency.upper():
            raise bankcsv.CsvError(f"Line {n}: this account is in {acct.currency} and the line is in {r.currency}. Import one account and one currency per file.")
        if r.amount_minor == 0:
            raise bankcsv.CsvError(f"Line {n}: the amount is zero. A bank line needs an amount.")
    have = set(session.scalars(select(BankTransaction.row_hash).where(BankTransaction.bank_account_id == acct.id)))  # this account only: the same line in another account is another line
    added = skipped = dups = before_opening = 0
    for r in rows:
        if r.row_hash in have:
            skipped += 1  # the same file again, nothing new
            continue
        if r.legacy_hash in have:
            # Saved by an earlier version, whose key had no account number: it is the same line. It gets the new key, so it never blocks the same line in another account.
            session.execute(update(BankTransaction).where(BankTransaction.bank_account_id == acct.id, BankTransaction.row_hash == r.legacy_hash).values(row_hash=r.row_hash).execution_options(synchronize_session=False))
            have.discard(r.legacy_hash)
            have.add(r.row_hash)
            skipped += 1
            continue
        t = BankTransaction(bank_account_id=acct.id, ref=r.ref, posted_on=r.posted_on, description=r.description, amount_minor=r.amount_minor, currency=r.currency, row_hash=r.row_hash, batch=batch)
        session.add(t)
        session.flush()
        added += 1
        before_opening += r.posted_on < acct.opening_date
        if r.possible_duplicate:
            t.status = "exception"
            raise_exception(session, "possible_duplicate_line", "warning", "bank_txn", t.id, "An identical line (same date, text and amount) comes earlier in this file. Check the statement before you keep both.")
            dups += 1
    out = {"added": added, "skipped_already_imported": skipped, "possible_duplicates": dups}
    if before_opening:
        out["ignored_before_opening_date"] = before_opening
        out["note"] = (f"{before_opening} of the lines are dated before this account's opening date ({acct.opening_date.isoformat()}). They are kept and can still be matched to invoices and bills, "
                       "but they are not added to the balance: the opening balance already holds them.")
    return out


def balance(session: Session, account_id: int | None = None) -> int:
    """The opening balance plus every line from the opening date on. A line dated before the opening date is already inside the opening balance, so counting it again would
    overstate the cash (and with it the forecast)."""
    acct = session.get(BankAccount, account_id) if account_id else session.scalars(select(BankAccount)).first()
    if acct is None:
        return 0
    total = session.scalar(select(func.coalesce(func.sum(BankTransaction.amount_minor), 0)).where(BankTransaction.bank_account_id == acct.id, BankTransaction.currency == acct.currency, BankTransaction.posted_on >= acct.opening_date))
    return acct.opening_minor + int(total)


def _targets(session: Session) -> list[RC.Target]:
    """What a bank line may be matched to. Invoices that are open and bills that are approved or posted as a draft come first: their open amount is the total less what is already
    paid and less what matches (suggested or confirmed) have reserved but no payment has recorded yet, so a partly paid invoice offers only what is still owed. Invoices and bills
    already marked paid stay on the list marked `settled` (a statement can cover payments the books already hold), but the matcher always prefers an open one, so a later deposit of
    the same amount from the same customer pays the invoice that is still open."""
    reserved: dict[tuple[str, int], int] = {}
    for m in session.scalars(select(Match).where(Match.target_type != "recurring")):
        k = ("invoice", m.invoice_id) if m.invoice_id else ("bill", m.bill_id)
        reserved[k] = reserved.get(k, 0) + m.allocated_minor
    recorded: dict[tuple[str, int], int] = {}
    for pa in session.scalars(select(PaymentAllocation)):
        k = ("invoice", pa.invoice_id) if pa.invoice_id else ("bill", pa.bill_id)
        recorded[k] = recorded.get(k, 0) + pa.amount_minor

    def open_left(kind: str, row_id: int, total: int, paid: int, settled: bool) -> int:
        taken = reserved.get((kind, row_id), 0)
        if settled:
            return total - taken  # already paid in full: what is left is the part no bank line has been linked to yet
        pending = max(taken - recorded.get((kind, row_id), 0), 0)  # matched but not yet turned into a payment, so not yet in paid_minor
        return total - paid - pending

    out = []
    names = {v.id: v.name for v in session.scalars(select(Vendor))}
    for i in session.scalars(select(Invoice).where(Invoice.status.in_(("open", "paid")))):
        settled = i.status == "paid"
        out.append(RC.Target("invoice", i.id, i.number, i.customer.name, open_left("invoice", i.id, i.total_minor, i.paid_minor, settled), i.issue_date, i.due_date, i.currency, settled))
    for b in session.scalars(select(Bill).where(Bill.status.in_(("paid", "approved", "posted_draft")))):
        settled = b.status == "paid"
        out.append(RC.Target("bill", b.id, b.number, names.get(b.vendor_id, b.vendor_name_read), open_left("bill", b.id, b.total_minor, b.paid_minor, settled), b.issue_date, b.due_date, b.currency, settled))
    return out


def run_matching(session: Session, ctx) -> dict:
    """Match every line that is still unmatched. Auto matches at 85 and above, suggestions from 60, the rest become exceptions."""
    # The lines are locked while they are matched (Postgres: FOR UPDATE; SQLite has one writer anyway), so the API and the worker running at the same time
    # cannot both match the same line, which would count one payment twice.
    todo = list(session.scalars(select(BankTransaction).where(BankTransaction.status.in_(("unmatched", "exception"))).order_by(BankTransaction.posted_on, BankTransaction.id).with_for_update()))
    dup_ids = set(session.scalars(select(ExceptionItem.ref_id).where(ExceptionItem.ref_type == "bank_txn", ExceptionItem.kind == "possible_duplicate_line")))
    txns = [RC.Txn(t.id, t.posted_on, t.description, t.amount_minor, t.currency, t.id in dup_ids) for t in todo]
    rec = [RC.RecurringT(r.id, r.name, r.match_text, -r.amount_minor if r.direction == "out" else r.amount_minor) for r in session.scalars(select(RecurringItem))]
    results = RC.match_all(txns, _targets(session), rec, ctx.rates(session))
    by_id = {t.id: t for t in todo}
    counts = {"matched": 0, "suggested": 0, "unmatched": 0, "duplicate": 0, "recurring": 0}
    for r in results:
        t = by_id[r.txn_id]
        counts[r.outcome] += 1
        if r.outcome == "duplicate":
            continue
        if r.outcome == "unmatched":
            t.status = "exception"
            raise_exception(session, "unmatched_line", "warning", "bank_txn", t.id, "No invoice, bill or repeating item fits this line. Link it by hand, or leave a note.")
            continue
        t.status = "matched" if r.outcome in ("matched", "recurring") else "suggested"
        for lk in r.links:
            session.add(Match(bank_txn_id=t.id, target_type=lk.kind, invoice_id=lk.id if lk.kind == "invoice" else None, bill_id=lk.id if lk.kind == "bill" else None, recurring_id=lk.id if lk.kind == "recurring" else None,
                              allocated_minor=lk.allocated_minor, score=lk.score, method="auto", status="confirmed" if r.outcome in ("matched", "recurring") else "suggested", reason=lk.reason))
    session.flush()
    return counts


def confirm_match(session: Session, match_id: int, who: str) -> Match:
    m = session.get(Match, match_id)
    m.status = "confirmed"
    t = session.get(BankTransaction, m.bank_txn_id)
    if all(x.status == "confirmed" for x in session.scalars(select(Match).where(Match.bank_txn_id == t.id))):
        t.status = "matched"
    record_audit(session, who, "match.confirmed", f"match:{m.id}", {})
    return m


def link_manually(session: Session, txn_id: int, kind: str, target_id: int, amount_minor: int, who: str) -> Match:
    """A person links one bank line to an invoice or bill. The amount may be less than the line (a part payment) but never more than the line, and never more than is still open.
    The line and the target must be in the same currency and the target must still be open. Both rows are locked while the sums are checked."""
    t = session.scalars(select(BankTransaction).where(BankTransaction.id == txn_id).with_for_update()).first()
    if t is None:
        raise ValueError("No such bank line.")
    model = Invoice if kind == "invoice" else Bill
    tgt = session.scalars(select(model).where(model.id == target_id).with_for_update()).first()
    if tgt is None:
        raise ValueError(f"No such {kind}.")
    if t.currency != tgt.currency:
        raise ValueError(f"The bank line is in {t.currency} and the {kind} is in {tgt.currency}. A link between two currencies is not made by hand: add the exchange rate and let the matcher convert, or ask your accountant.")
    if kind == "invoice" and tgt.status != "open":
        raise ValueError("This invoice is not open, so it cannot take a payment.")
    if kind == "bill" and tgt.status not in ("approved", "posted_draft", "needs_review"):
        raise ValueError("This bill is not waiting to be paid (rejected or already paid), so it cannot take a payment.")
    used = int(session.scalar(select(func.coalesce(func.sum(Match.allocated_minor), 0)).where(Match.bank_txn_id == txn_id)) or 0)
    if amount_minor <= 0 or used + amount_minor > abs(t.amount_minor):
        raise ValueError("The linked amount cannot be more than the bank line.")
    already = int(session.scalar(select(func.coalesce(func.sum(Match.allocated_minor), 0)).where(Match.invoice_id == target_id if kind == "invoice" else Match.bill_id == target_id)) or 0)
    recorded = int(session.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount_minor), 0)).where(PaymentAllocation.invoice_id == target_id if kind == "invoice" else PaymentAllocation.bill_id == target_id)) or 0)
    # What the document already holds as paid counts too: an invoice imported with part of it paid has `paid_minor` that no bank line here explains. Matches whose payment is
    # already recorded are inside `paid_minor`, so only the ones still waiting are added to it.
    committed = tgt.paid_minor + max(already - recorded, 0)
    if committed + amount_minor > tgt.total_minor:
        raise ValueError("That would pay more than the amount on the document" + (f" (it already shows {format_minor(tgt.paid_minor, tgt.currency)} paid)." if tgt.paid_minor else "."))
    m = Match(bank_txn_id=txn_id, target_type=kind, invoice_id=target_id if kind == "invoice" else None, bill_id=target_id if kind == "bill" else None, allocated_minor=amount_minor, score=100, method="manual", status="confirmed", reason="linked by a person")
    session.add(m)
    t.status = "matched"
    record_audit(session, who, "match.manual", f"bank_txn:{txn_id}", {"kind": kind, "target": target_id})
    session.flush()
    return m


def unlink(session: Session, match_id: int, who: str) -> None:
    """Remove a match. If it had already been turned into a payment, that payment is taken back too: the allocation goes, the invoice is open again when it no longer
    holds its full amount, and a payment record with no allocation left is removed. Without this a wrongly confirmed match would leave an invoice paid for good."""
    m = session.get(Match, match_id)
    t = session.get(BankTransaction, m.bank_txn_id)
    payment = session.scalars(select(Payment).where(Payment.bank_txn_id == t.id)).first()
    if payment is not None and m.target_type != "recurring":
        alloc = session.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id, PaymentAllocation.invoice_id == m.invoice_id, PaymentAllocation.bill_id == m.bill_id,
                                                                 PaymentAllocation.amount_minor == m.allocated_minor)).first()
        if alloc is not None:
            session.delete(alloc)
            session.flush()
            if m.invoice_id:
                inv = session.get(Invoice, m.invoice_id)
                # Take the money back only when this payment is what put it there: the invoice is still open (a part payment), or this payment is the one that made it paid
                # (it carries that payment's date). An invoice that was already marked paid before the line was linked to it stays as it was.
                if inv.status == "open" or (inv.status == "paid" and inv.paid_on == payment.paid_on):
                    inv.paid_minor = max(0, inv.paid_minor - m.allocated_minor)
                    if inv.status == "paid" and inv.paid_minor < inv.total_minor:
                        inv.status, inv.paid_on = "open", None
            elif m.bill_id:
                bill = session.get(Bill, m.bill_id)
                bill.paid_minor = max(0, bill.paid_minor - m.allocated_minor)
                if bill.status == "paid" and bill.paid_minor < bill.total_minor:  # it was approved before it was paid (only such a bill is ever marked paid): payable again, in the state it had before the payment
                    bill.status, bill.paid_on = ("posted_draft" if bill.posted_external_id else "approved"), None
        if not session.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)).first():
            session.delete(payment)
    session.delete(m)
    session.flush()
    if not session.scalars(select(Match).where(Match.bank_txn_id == t.id)).first():
        t.status = "unmatched"
    record_audit(session, who, "match.removed", f"bank_txn:{t.id}", {})


def record_payments(session: Session) -> int:
    """Turn confirmed matches into payment records. Each new payment adds its allocation to the invoice it pays (on top of anything the invoice already had paid when it was
    imported), and an invoice that holds its full amount becomes paid, with the date of the payment that completed it."""
    n = 0
    for t in session.scalars(select(BankTransaction).where(BankTransaction.status == "matched")):
        if session.scalars(select(Payment).where(Payment.bank_txn_id == t.id)).first():
            continue
        p = Payment(direction="in" if t.amount_minor > 0 else "out", paid_on=t.posted_on, amount_minor=abs(t.amount_minor), currency=t.currency, bank_txn_id=t.id)
        session.add(p)
        session.flush()
        for m in session.scalars(select(Match).where(Match.bank_txn_id == t.id, Match.target_type != "recurring")):
            session.add(PaymentAllocation(payment_id=p.id, invoice_id=m.invoice_id, bill_id=m.bill_id, amount_minor=m.allocated_minor))
            inv = session.get(Invoice, m.invoice_id) if m.invoice_id else None
            if inv is not None and inv.status == "open":  # a payment against an invoice already marked paid is only linked: it must not move the date it was paid or its amounts
                inv.paid_minor = min(inv.paid_minor + m.allocated_minor, inv.total_minor)
                if inv.paid_minor >= inv.total_minor:
                    inv.status, inv.paid_on = "paid", t.posted_on
        n += 1
    session.flush()
    _settle_bills(session)
    return n


def _settle_bills(session: Session) -> None:
    """Bills paid by a matched bank line: paid_minor follows the allocations, and a bill that holds its full amount is paid (with the date of its last payment).
    Without this a paid bill stayed in payables and in the forecast, whose bank balance had already dropped, so the same money was counted twice."""
    for bill in session.scalars(select(Bill).where(Bill.id.in_(select(PaymentAllocation.bill_id).where(PaymentAllocation.bill_id.is_not(None))), Bill.status.not_in(("rejected", "posting")))):
        got = int(session.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount_minor), 0)).where(PaymentAllocation.bill_id == bill.id)) or 0)
        if got <= bill.paid_minor:
            continue
        bill.paid_minor = min(got, bill.total_minor)
        # Only a bill a person already approved becomes paid. A bill still waiting for review keeps its status (the money went out, but approving it is still a person's decision
        # and a taken back match must never turn it into an approved one).
        if bill.paid_minor >= bill.total_minor and bill.status in ("approved", "posted_draft"):
            last = session.scalar(select(func.max(Payment.paid_on)).join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id).where(PaymentAllocation.bill_id == bill.id))
            bill.status, bill.paid_on = "paid", last
