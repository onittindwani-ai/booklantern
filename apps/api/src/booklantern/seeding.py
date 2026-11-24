"""Load the seed data into a database. Used by the demo, the tests and tools/score_seed.py."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import fxservice
from booklantern.models import Account, BankAccount, Bill, Customer, Invoice, PromiseToPay, RecurringItem, Reminder, Vendor
from booklantern.reminders import LADDER

DEFAULT_DATA = Path(__file__).resolve().parents[4] / "data"
ACCOUNTS = [("1000", "Operating bank account", "asset"), ("1200", "Accounts receivable", "asset"), ("2000", "Accounts payable", "liability"), ("4000", "Sales", "income"),
            ("5000", "Cost of goods", "expense"), ("6000", "Rent", "expense"), ("6100", "Payroll", "expense"), ("6200", "Software and subscriptions", "expense"), ("6900", "Bank fees", "expense")]  # a small generic default list for the demo, not advice: replace it with the client's own chart of accounts


def read_seed(data_dir: Path | None = None) -> dict:
    return json.loads(((data_dir or DEFAULT_DATA) / "seed.json").read_text())


def load_seed(session: Session, seed: dict, now: datetime) -> dict:
    for code, name, kind in ACCOUNTS:
        session.add(Account(code=code, name=name, kind=kind))
    vendors = {v["key"]: Vendor(key=v["key"], name=v["name"], address=v["addr"], currency=v["currency"], tax_rate_bp=v["tax_bp"], requires_po=v["requires_po"], bank_account=v["account"], terms_days=v["terms_days"]) for v in seed["vendors"]}
    session.add_all(vendors.values())
    customers = {c["key"]: Customer(key=c["key"], name=c["name"], email=c["email"], timezone=c["tz"], terms_days=c["terms_days"], bankruptcy_flag=c["flag"] == "bankruptcy", opted_out=c["flag"] == "opt_out") for c in seed["customers"]}
    session.add_all(customers.values())
    session.flush()
    invs: dict[str, Invoice] = {}
    for i in seed["invoices"]:
        inv = Invoice(customer_id=customers[i["customer"]].id, number=i["number"], issue_date=date.fromisoformat(i["issue"]), due_date=date.fromisoformat(i["due"]), currency=i["currency"], total_minor=i["total_minor"],
                      paid_minor=i["paid_minor"], status="paid" if i["status"] == "paid" else "open", disputed=i["flag"] == "dispute", dispute_note="Customer says the delivery was short." if i["flag"] == "dispute" else "",
                      paid_on=date.fromisoformat(i["paid_on"]) if i["paid_on"] else None)
        invs[i["number"]] = inv
        session.add(inv)
    for b in seed["bills_hist"]:
        v = vendors[b["vendor"]]
        session.add(Bill(vendor_id=v.id, vendor_name_read=v.name, number=b["number"], issue_date=date.fromisoformat(b["issue"]), due_date=date.fromisoformat(b["due"]), currency=b["currency"], bill_to=seed["company"]["name"],
                         bank_account=v.bank_account, subtotal_minor=b["subtotal_minor"], tax_minor=b["tax_minor"], total_minor=b["total_minor"], paid_minor=b["total_minor"], status="paid", paid_on=date.fromisoformat(b["paid_on"])))
    session.add(BankAccount(name=seed["bank_account"]["name"], currency="USD", opening_minor=seed["bank_account"]["opening_minor"], opening_date=date.fromisoformat(seed["bank_account"]["opening_date"])))
    for r in seed["recurring"]:
        session.add(RecurringItem(name=r["name"], direction=r["direction"], amount_minor=r["amount_minor"], cadence=r["cadence"], day=r["day"], match_text=r["match"]))
    session.flush()
    for p in seed["promises"]:
        session.add(PromiseToPay(invoice_id=invs[p["invoice"]].id, promised_on=date.fromisoformat(p["promised_on"]), amount_minor=p["amount_minor"], status=p["status"]))
    tone = {s: t for s, _, t in LADDER}
    for r in seed["reminders"]:
        when = datetime.fromisoformat(r["sent_on"] + "T14:00:00+00:00")
        session.add(Reminder(invoice_id=invs[r["invoice"]].id, step=r["step"], tone=tone[r["step"]], status="sent", scheduled_for=when, sent_at=when, subject=f"Reminder for invoice {r['invoice']}", body="(sent before the demo started)"))
    session.flush()
    fxservice.load_seed_rates(session, seed, now)
    return {"invoices": len(invs), "vendors": len(vendors), "customers": len(customers)}
