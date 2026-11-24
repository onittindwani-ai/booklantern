from __future__ import annotations

from booklantern.models import Bill, Customer, Invoice, Reminder, Vendor


def iso(v):
    return v.isoformat() if v is not None else None


def bill_row(b: Bill, vendor: Vendor | None = None, flags: list[dict] | None = None, fx: dict | None = None) -> dict:
    return {"id": b.id, "vendor": vendor.name if vendor else b.vendor_name_read, "vendor_id": b.vendor_id, "number": b.number, "issue_date": iso(b.issue_date), "due_date": iso(b.due_date), "currency": b.currency,
            "po_number": b.po_number, "bill_to": b.bill_to, "bank_account": b.bank_account, "subtotal_minor": b.subtotal_minor, "tax_minor": b.tax_minor, "total_minor": b.total_minor, "paid_minor": b.paid_minor,
            "status": b.status, "document_id": b.document_id, "flags": flags or [], "fx": fx}


def invoice_row(i: Invoice, fx: dict | None = None) -> dict:
    return {"id": i.id, "number": i.number, "customer": i.customer.name, "customer_id": i.customer_id, "issue_date": iso(i.issue_date), "due_date": iso(i.due_date), "currency": i.currency, "total_minor": i.total_minor,
            "paid_minor": i.paid_minor, "outstanding_minor": i.total_minor - i.paid_minor, "status": i.status, "disputed": i.disputed, "dispute_note": i.dispute_note, "payment_link_url": i.payment_link_url, "fx": fx}


def reminder_row(r: Reminder) -> dict:
    return {"id": r.id, "invoice_id": r.invoice_id, "invoice": r.invoice.number, "customer": r.invoice.customer.name, "step": r.step, "tone": r.tone, "status": r.status, "scheduled_for": iso(r.scheduled_for),
            "sent_at": iso(r.sent_at), "subject": r.subject, "body": r.body, "cancel_reason": r.cancel_reason}


def customer_row(c: Customer) -> dict:
    return {"id": c.id, "name": c.name, "email": c.email, "timezone": c.timezone, "bankruptcy_flag": c.bankruptcy_flag, "opted_out": c.opted_out, "terms_days": c.terms_days}
