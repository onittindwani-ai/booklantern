"""Booklantern tables. They sit on the shared Base, so the core tables and these migrate together.

Money columns end in `_minor` and hold integer minor units (cents). Percentages are integers in basis points.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sendora_core.db import Base, UTCDateTime, utcnow

BILL_STATUSES = ("inbox", "needs_review", "approved", "posted_draft", "paid", "rejected")
DOC_STATUSES = ("new", "extracted", "unreadable", "linked")
INVOICE_STATUSES = ("open", "paid", "void")
REMINDER_STATUSES = ("drafted", "approved", "sending", "sent", "cancelled")
PROMISE_STATUSES = ("open", "kept", "broken")
SEVERITIES = ("info", "warning", "block")


class State(Base):
    __tablename__ = "ll_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class FxRate(Base):
    """A manual exchange rate: units of the company currency for one unit of `currency`, valid from `rate_date`. The rate is Decimal text, never a float."""
    __tablename__ = "ll_fx_rate"
    __table_args__ = (UniqueConstraint("currency", "rate_date", name="uq_ll_fx_rate_currency_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    rate_date: Mapped[date] = mapped_column(Date)
    rate: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(String(160), default="")
    entered_by: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Vendor(Base):
    __tablename__ = "ll_vendor"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    address: Mapped[str] = mapped_column(String(240), default="")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    tax_rate_bp: Mapped[int] = mapped_column(Integer, default=0)
    requires_po: Mapped[bool] = mapped_column(Boolean, default=False)
    bank_account: Mapped[str] = mapped_column(String(80), default="")
    terms_days: Mapped[int] = mapped_column(Integer, default=30)


class Customer(Base):
    __tablename__ = "ll_customer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    email: Mapped[str] = mapped_column(String(200), default="")
    timezone: Mapped[str] = mapped_column(String(60), default="America/New_York")
    terms_days: Mapped[int] = mapped_column(Integer, default=30)
    bankruptcy_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)


class Document(Base):
    __tablename__ = "ll_document"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True)
    file_name: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    mime: Mapped[str] = mapped_column(String(80), default="application/pdf")
    source: Mapped[str] = mapped_column(String(20), default="upload")  # upload or inbox
    from_addr: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(240), default="")
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    has_text_layer: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    read_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # how many times reading was started: a file that keeps killing the reader is given up on (intake.MAX_READ_ATTEMPTS)
    extraction: Mapped[dict] = mapped_column(JSON, default=dict)  # fields with value, confidence, page and box
    extractor: Mapped[str] = mapped_column(String(60), default="")
    stored_path: Mapped[str] = mapped_column(String(400), default="")
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Bill(Base):
    """A bill from a vendor (accounts payable)."""
    __tablename__ = "ll_bill"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("ll_vendor.id"), nullable=True, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("ll_document.id"), nullable=True)
    vendor_name_read: Mapped[str] = mapped_column(String(200), default="")
    number: Mapped[str] = mapped_column(String(80), default="", index=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    po_number: Mapped[str] = mapped_column(String(60), default="")
    bill_to: Mapped[str] = mapped_column(String(200), default="")
    bank_account: Mapped[str] = mapped_column(String(80), default="")
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    tax_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="inbox", index=True)
    posted_external_id: Mapped[str] = mapped_column(String(80), default="")
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    edited_by: Mapped[str] = mapped_column(String(120), default="")
    had_block: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # set the first time any blocking finding fires on this bill and never cleared: editing the finding away does not undo it
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    lines: Mapped[list[BillLine]] = relationship(back_populates="bill", cascade="all, delete-orphan", order_by="BillLine.position")


class BillLine(Base):
    __tablename__ = "ll_bill_line"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("ll_bill.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(String(240), default="")
    quantity_milli: Mapped[int] = mapped_column(BigInteger, default=1000)
    unit_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    bill: Mapped[Bill] = relationship(back_populates="lines")


class Invoice(Base):
    """A sales invoice to a customer (accounts receivable)."""
    __tablename__ = "ll_invoice"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("ll_customer.id"), index=True)
    number: Mapped[str] = mapped_column(String(40), unique=True)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    total_minor: Mapped[int] = mapped_column(BigInteger)
    paid_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    disputed: Mapped[bool] = mapped_column(Boolean, default=False)
    dispute_note: Mapped[str] = mapped_column(String(240), default="")
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_link_url: Mapped[str] = mapped_column(String(300), default="")
    customer: Mapped[Customer] = relationship()


class Payment(Base):
    """Cash received or paid, recorded from a bank line."""
    __tablename__ = "ll_payment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    direction: Mapped[str] = mapped_column(String(3))  # in or out
    paid_on: Mapped[date] = mapped_column(Date)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    bank_txn_id: Mapped[int | None] = mapped_column(ForeignKey("ll_bank_txn.id"), nullable=True)


class PaymentAllocation(Base):
    __tablename__ = "ll_payment_allocation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("ll_payment.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("ll_invoice.id"), nullable=True)
    bill_id: Mapped[int | None] = mapped_column(ForeignKey("ll_bill.id"), nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)


class Reminder(Base):
    __tablename__ = "ll_reminder"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("ll_invoice.id"), index=True)
    step: Mapped[int] = mapped_column(Integer)
    tone: Mapped[str] = mapped_column(String(20), default="friendly")
    channel: Mapped[str] = mapped_column(String(10), default="email")
    status: Mapped[str] = mapped_column(String(12), default="drafted", index=True)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    subject: Mapped[str] = mapped_column(String(240), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    payment_link_url: Mapped[str] = mapped_column(String(300), default="")
    cancel_reason: Mapped[str] = mapped_column(String(120), default="")
    invoice: Mapped[Invoice] = relationship()


class PromiseToPay(Base):
    __tablename__ = "ll_promise"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("ll_invoice.id"), index=True)
    promised_on: Mapped[date] = mapped_column(Date)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), default="open")
    note: Mapped[str] = mapped_column(String(240), default="")
    invoice: Mapped[Invoice] = relationship()


class Account(Base):
    """Chart of accounts entry. The defaults are a small generic list for the demo, not advice; the implementer replaces them with the client's own chart."""
    __tablename__ = "ll_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # asset, liability, income, expense


class BankAccount(Base):
    __tablename__ = "ll_bank_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    opening_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    opening_date: Mapped[date] = mapped_column(Date)


class BankTransaction(Base):
    __tablename__ = "ll_bank_txn"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("ll_bank_account.id"), index=True)
    ref: Mapped[str] = mapped_column(String(40), index=True)
    posted_on: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(300))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(14), default="unmatched", index=True)  # unmatched, suggested, matched, exception, ignored
    row_hash: Mapped[str] = mapped_column(String(64), index=True)
    batch: Mapped[str] = mapped_column(String(40), default="")


class Match(Base):
    __tablename__ = "ll_match"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_txn_id: Mapped[int] = mapped_column(ForeignKey("ll_bank_txn.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(12))  # invoice, bill, recurring
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("ll_invoice.id"), nullable=True)
    bill_id: Mapped[int | None] = mapped_column(ForeignKey("ll_bill.id"), nullable=True)
    recurring_id: Mapped[int | None] = mapped_column(ForeignKey("ll_recurring.id"), nullable=True)
    allocated_minor: Mapped[int] = mapped_column(BigInteger)
    score: Mapped[int] = mapped_column(Integer, default=0)  # 0 to 100
    method: Mapped[str] = mapped_column(String(12), default="auto")  # auto or manual
    status: Mapped[str] = mapped_column(String(12), default="suggested")  # suggested, confirmed
    reason: Mapped[str] = mapped_column(String(240), default="")
    __table_args__ = (UniqueConstraint("bank_txn_id", "target_type", "invoice_id", "bill_id", "recurring_id"),)


class RecurringItem(Base):
    __tablename__ = "ll_recurring"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    direction: Mapped[str] = mapped_column(String(3))  # in or out
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    cadence: Mapped[str] = mapped_column(String(20))  # monthly, twice_monthly, weekly
    day: Mapped[int] = mapped_column(Integer, default=1)
    match_text: Mapped[str] = mapped_column(String(120), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Scenario(Base):
    __tablename__ = "ll_scenario"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    adjustments: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Forecast(Base):
    __tablename__ = "ll_forecast"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("ll_scenario.id"), nullable=True)
    weeks: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ExceptionItem(Base):
    __tablename__ = "ll_exception"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(10), default="warning")
    ref_type: Mapped[str] = mapped_column(String(12))  # bill, invoice, bank_txn, document
    ref_id: Mapped[int] = mapped_column(Integer, index=True)
    detail: Mapped[str] = mapped_column(String(400), default="")
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)
    resolved_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    __table_args__ = (UniqueConstraint("kind", "ref_type", "ref_id"),)
